import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import List, Optional


class ChromiumAdapter:
    """Manages a Chromium kiosk subprocess."""

    def __init__(
        self,
        homepage: str,
        flags_file: str,
        binary: str = "/usr/bin/chromium-browser",
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.homepage = homepage
        self.flags_path = Path(flags_file)
        self.binary = binary
        self.logger = logger or logging.getLogger(__name__)

        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._monitor_thread: Optional[threading.Thread] = None
        self._stopping = False
        self._last_url = homepage

    # Public API -----------------------------------------------------------
    def start(self, url: Optional[str] = None) -> None:
        target_url = url or self.homepage
        with self._lock:
            if self._process and self._process.poll() is None:
                self.logger.info("Chromium already running, skipping start.")
                return
            self._launch(target_url)
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

    def restart(self, url: Optional[str] = None) -> None:
        self.stop()
        self.start(url or self._last_url)

    def reload(self) -> None:
        self._log_placeholder("reload")

    def back(self) -> None:
        self._log_placeholder("back")

    def forward(self) -> None:
        self._log_placeholder("forward")

    def home(self) -> None:
        self.logger.info("Navigating Chromium to homepage: %s", self.homepage)
        self.restart(self.homepage)

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
        ]
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

            time.sleep(2)
            try:
                with self._lock:
                    self._launch(self._last_url)
            except Exception:
                self.logger.exception("Failed to relaunch Chromium.")
                time.sleep(5)

    def _log_placeholder(self, action: str) -> None:
        if self.is_alive():
            self.logger.info("Chromium action requested: %s", action)
        else:
            self.logger.info(
                "Chromium action '%s' ignored because process is not running.", action
            )

