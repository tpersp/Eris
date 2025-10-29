import logging
import os
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Iterable, List, Optional, Sequence


class DisplayManager:
    """Supervises the lightweight X session required for kiosk playback."""

    def __init__(
        self,
        display: str = ":0",
        launcher: Optional[Iterable[str]] = None,
        startup_timeout: float = 12.0,
        socket_dir: Path = Path("/tmp/.X11-unix"),
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.display = display or ":0"
        self.startup_timeout = startup_timeout
        self.socket_dir = socket_dir
        self.logger = logger or logging.getLogger("eris.display")

        self._launcher: Optional[List[str]] = self._normalise_launcher(launcher)
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._external = False
        self._last_error: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Lifecycle helpers                                                  #
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        with self._lock:
            if self._has_active_socket():
                self._external = True
                self.logger.debug(
                    "Display socket %s already present; assuming external session.",
                    self._socket_path(),
                )
                return

            if not self._launcher:
                raise RuntimeError(
                    "No display launcher command configured and no existing X session found."
                )

            if self._process and self._process.poll() is None:
                self.logger.debug("Display session already running; skipping start.")
                return

            self.logger.info("Launching kiosk X session: %s", " ".join(self._launcher))
            self._external = False
            env = os.environ.copy()
            env.setdefault("DISPLAY", self.display)
            runtime_dir = f"/run/user/{os.getuid()}"
            if os.path.isdir(runtime_dir):
                env.setdefault("XDG_RUNTIME_DIR", runtime_dir)
            try:
                self._process = subprocess.Popen(
                    self._launcher,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                )
            except FileNotFoundError as exc:
                self._last_error = f"Launcher binary missing: {exc.filename}"
                self.logger.error(self._last_error)
                raise
            except Exception as exc:  # pragma: no cover - defensive logging
                self._last_error = str(exc) or exc.__class__.__name__
                self.logger.exception("Failed to launch kiosk X session.")
                raise

        self._wait_for_socket()

    def ensure_running(self) -> bool:
        """Verifies the display socket exists and restarts the session if required."""
        with self._lock:
            if self._external:
                ready = self._has_active_socket()
                if not ready:
                    self._last_error = f"Display socket {self._socket_path()} missing."
                return ready

            if self._process and self._process.poll() is None:
                if self._has_active_socket():
                    return True
                self.logger.warning("Display process running but socket missing; restarting.")
                self._terminate_session()

        try:
            self.start()
        except Exception:
            return False
        return True

    def stop(self) -> None:
        with self._lock:
            if self._external:
                return
            self._terminate_session()

    # ------------------------------------------------------------------ #
    # Inspection helpers                                                 #
    # ------------------------------------------------------------------ #
    def is_running(self) -> bool:
        if self._external:
            return self._has_active_socket()
        with self._lock:
            return bool(self._process and self._process.poll() is None)

    def last_error(self) -> Optional[str]:
        return self._last_error

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #
    def _terminate_session(self, timeout: float = 5.0) -> None:
        if not self._process:
            return
        process = self._process
        self.logger.info("Stopping kiosk X session (pid=%s).", process.pid)
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.logger.warning("X session did not exit promptly; killing.")
            process.kill()
        finally:
            self._process = None

    def _wait_for_socket(self) -> None:
        socket_path = self._socket_path()
        deadline = time.time() + self.startup_timeout
        while time.time() < deadline:
            if socket_path.exists():
                self.logger.info("Display socket %s ready.", socket_path)
                self._last_error = None
                return
            time.sleep(0.25)

        message = f"Timed out waiting for display socket {socket_path}"
        self._last_error = message
        raise TimeoutError(message)

    def _has_active_socket(self) -> bool:
        return self._socket_path().exists()

    def _socket_path(self) -> Path:
        display_value = self.display.lstrip(":")
        if not display_value:
            display_value = "0"
        if "." in display_value:
            display_value = display_value.split(".", 1)[0]
        return self.socket_dir / f"X{display_value}"

    @staticmethod
    def _normalise_launcher(launcher: Optional[Iterable[str]]) -> Optional[List[str]]:
        if launcher is None:
            return None
        if isinstance(launcher, (str, bytes)):
            return shlex.split(str(launcher))
        if isinstance(launcher, Sequence):
            return list(launcher)
        return list(launcher or [])
