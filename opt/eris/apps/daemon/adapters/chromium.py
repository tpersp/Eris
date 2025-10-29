import itertools
import json
import logging
import os
import socket
import subprocess
import threading
import time
from contextlib import closing, suppress
from pathlib import Path
from typing import Dict, List, Optional
from urllib.error import URLError
from urllib.request import urlopen

import websocket


class ChromiumAdapter:
    """Manages a Chromium kiosk subprocess."""

    def __init__(
        self,
        homepage: str,
        flags_file: str,
        binary: str = "/usr/bin/chromium-browser",
        debug_port: int = 9222,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.homepage = homepage
        self.flags_path = Path(flags_file)
        self.binary = binary
        self.debug_port = debug_port
        self.logger = logger or logging.getLogger(__name__)

        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._monitor_thread: Optional[threading.Thread] = None
        self._stopping = False
        self._last_url = homepage
        self._devtools_lock = threading.Lock()
        self._message_counter = itertools.count(1)
        self._ws_url: Optional[str] = None
        self._devtools_enabled = False

    # Public API -----------------------------------------------------------
    def start(self, url: Optional[str] = None) -> None:
        target_url = url or self.homepage
        with self._lock:
            if self._process and self._process.poll() is None:
                self.logger.info("Chromium already running, skipping start.")
                return
            self._reset_devtools()
            self._launch(target_url)
        try:
            self._initialise_devtools()
        except Exception:
            self.logger.exception("Chromium launched but DevTools handshake failed; stopping.")
            self.stop()
            raise
        self._ensure_monitor()

    def stop(self) -> None:
        with self._lock:
            if not self._process:
                return
            self.logger.info("Stopping Chromium process.")
            self._stopping = True
            self._terminate_process()
            self._process = None
            self._stopping = False
        self._reset_devtools()

    def restart(self, url: Optional[str] = None) -> None:
        self.stop()
        self.start(url or self._last_url)

    def reload(self) -> None:
        self._require_alive()
        self.logger.info("Reloading Chromium page.")
        self._send_devtools_command("Page.reload", {"ignoreCache": False})

    def back(self) -> None:
        self._require_alive()
        self.logger.info("Navigating Chromium back.")
        result = self._send_devtools_command("Page.goBack")
        if not result.get("success", True):
            raise RuntimeError("No previous page in Chromium history.")

    def forward(self) -> None:
        self._require_alive()
        self.logger.info("Navigating Chromium forward.")
        result = self._send_devtools_command("Page.goForward")
        if not result.get("success", True):
            raise RuntimeError("No forward entry in Chromium history.")

    def home(self) -> None:
        self._require_alive()
        self.logger.info("Navigating Chromium to homepage: %s", self.homepage)
        self._send_devtools_command("Page.navigate", {"url": self.homepage})
        self._last_url = self.homepage

    def is_alive(self) -> bool:
        with self._lock:
            return bool(self._process and self._process.poll() is None)

    # Private helpers ------------------------------------------------------
    def _launch(self, url: str) -> None:
        self._last_url = url
        cmd = self._build_command(url)
        self.logger.info("Launching Chromium: %s", " ".join(cmd))
        try:
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except FileNotFoundError as exc:
            self.logger.error("Chromium binary not found at %s", self.binary)
            raise exc
        except Exception:
            self.logger.exception("Failed to launch Chromium.")
            raise

    def _terminate_process(self, timeout: float = 5.0) -> None:
        if not self._process:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.logger.warning("Chromium did not exit in time; killing.")
            self._process.kill()
        finally:
            self._process = None
            self._reset_devtools()

    def _build_command(self, url: str) -> List[str]:
        flags = [
            "--kiosk",
            url,
            "--noerrdialogs",
            "--incognito",
            "--disable-translate",
            "--autoplay-policy=no-user-gesture-required",
            "--disable-infobars",
            "--start-maximized",
            "--no-first-run",
            "--disable-features=TranslateUI",
        ]
        if self.debug_port and self.debug_port > 0:
            flags.append(f"--remote-debugging-port={self.debug_port}")
            flags.append("--remote-allow-origins=*")

        flags.extend(self._load_flag_file())

        env = os.environ.get("DISPLAY")
        if not env:
            # Ensure DISPLAY is set for headless launches when X is available.
            os.environ.setdefault("DISPLAY", ":0")

        return [self.binary, *flags]

    def _load_flag_file(self) -> List[str]:
        if not self.flags_path.exists():
            return []
        try:
            content = self.flags_path.read_text().strip().splitlines()
            return [line.strip() for line in content if line.strip()]
        except Exception:
            self.logger.exception("Failed to read Chromium flags file %s", self.flags_path)
            return []

    def _initialise_devtools(self, timeout: float = 10.0) -> None:
        if not self.debug_port or self.debug_port <= 0:
            return

        deadline = time.time() + timeout
        last_error: Optional[str] = None
        while time.time() < deadline:
            try:
                ws_url = self._fetch_websocket_url()
                if ws_url:
                    with self._devtools_lock:
                        self._ws_url = ws_url
                        self._devtools_enabled = False
                    self._enable_devtools()
                    self.logger.debug("Chromium DevTools connected (%s).", ws_url)
                    return
            except Exception as exc:
                last_error = str(exc) or exc.__class__.__name__
                self.logger.debug("DevTools handshake attempt failed: %s", last_error)
            time.sleep(0.4)

        message = last_error or "no DevTools target exposed"
        raise TimeoutError(f"Timed out establishing Chromium DevTools connection: {message}")

    def _enable_devtools(self) -> None:
        if not self.debug_port or self.debug_port <= 0:
            return
        with self._devtools_lock:
            if self._devtools_enabled:
                return
        try:
            self._send_devtools_command("Page.enable")
            self._send_devtools_command("Runtime.enable")
        except Exception as exc:
            self.logger.debug("Failed enabling Chromium DevTools APIs: %s", exc)
            self._invalidate_ws_url()
            raise
        else:
            with self._devtools_lock:
                self._devtools_enabled = True

    def _fetch_websocket_url(self) -> Optional[str]:
        if not self.debug_port or self.debug_port <= 0:
            return None
        endpoint = f"http://127.0.0.1:{self.debug_port}/json"
        try:
            with closing(urlopen(endpoint, timeout=2.0)) as response:
                try:
                    payload = json.loads(response.read().decode("utf-8"))
                except json.JSONDecodeError as exc:
                    self.logger.debug("Failed to parse DevTools JSON payload: %s", exc)
                    return None
        except (URLError, ConnectionError, socket.error):
            return None

        if isinstance(payload, dict):
            targets = payload.get("targets") or payload.get("data") or []
        else:
            targets = payload

        if not isinstance(targets, list):
            return None

        for target in targets:
            if isinstance(target, dict) and target.get("type") == "page":
                ws_url = target.get("webSocketDebuggerUrl")
                if ws_url:
                    return ws_url
        return None

    def _ensure_ws_url(self) -> str:
        with self._devtools_lock:
            ws_url = self._ws_url
        if ws_url:
            return ws_url

        ws_url = self._fetch_websocket_url()
        if not ws_url:
            raise RuntimeError("Chromium DevTools target unavailable.")

        with self._devtools_lock:
            self._ws_url = ws_url
        return ws_url

    def _invalidate_ws_url(self) -> None:
        with self._devtools_lock:
            self._ws_url = None
            self._devtools_enabled = False

    def _send_devtools_command(self, method: str, params: Optional[Dict[str, object]] = None) -> Dict[str, object]:
        if not self.debug_port or self.debug_port <= 0:
            raise RuntimeError("Chromium launched without remote debugging support.")

        ws_url = self._ensure_ws_url()
        with self._devtools_lock:
            message_id = next(self._message_counter)
        request = {
            "id": message_id,
            "method": method,
            "params": params or {},
        }

        ws = None
        try:
            ws = websocket.create_connection(ws_url, timeout=4.0)
        except Exception as exc:
            self._invalidate_ws_url()
            raise RuntimeError(f"Failed to connect to Chromium DevTools: {exc}") from exc

        try:
            ws.send(json.dumps(request))
            while True:
                response_raw = ws.recv()
                message = json.loads(response_raw)
                if message.get("id") == message_id:
                    if "error" in message:
                        error_message = message["error"].get("message", "Unknown Chrome error")
                        raise RuntimeError(error_message)
                    return message.get("result", {})
        except websocket.WebSocketException as exc:
            self._invalidate_ws_url()
            raise RuntimeError(f"Chromium DevTools command failed: {exc}") from exc
        finally:
            if ws is not None:
                with suppress(Exception):
                    ws.close()

    def _reset_devtools(self) -> None:
        with self._devtools_lock:
            self._ws_url = None
            self._devtools_enabled = False
            self._message_counter = itertools.count(1)

    def _require_alive(self) -> None:
        if not self.is_alive():
            raise RuntimeError("Chromium process is not running.")

    def _ensure_monitor(self) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        while True:
            with self._lock:
                process = self._process
            if not process:
                return

            return_code = process.wait()
            with self._lock:
                if self._stopping:
                    self.logger.info("Chromium exited (intentional stop).")
                    self._process = None
                    return

                self.logger.warning(
                    "Chromium crashed or exited unexpectedly (code=%s). Restarting.",
                    return_code,
                )
                self._process = None
                self._reset_devtools()

            time.sleep(2)
            try:
                with self._lock:
                    self._launch(self._last_url)
                self._initialise_devtools()
            except Exception:
                self.logger.exception("Failed to relaunch Chromium.")
                time.sleep(5)
