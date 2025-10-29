import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional

from adapters.chromium import ChromiumAdapter
from adapters.media import MediaItem, MediaLibrary, MediaPlayer


class ContentRouter:
    """Coordinates between Chromium and media playback adapters."""

    def __init__(
        self,
        chromium: ChromiumAdapter,
        media_player: MediaPlayer,
        library: MediaLibrary,
        homepage: str,
        state_path: Path,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._lock = threading.Lock()
        self.chromium = chromium
        self.media_player = media_player
        self.library = library
        self.homepage = homepage
        self.state_path = state_path
        self.logger = logger or logging.getLogger("eris.content")

        self.mode: str = "web"
        self.current_url: str = homepage
        self.current_media: Optional[MediaItem] = None
        self._current_media_path: Optional[str] = None
        self._paused: bool = False

        self._loop = None
        self._notifier: Optional[Callable[[Dict[str, object]], None]] = None
        self._media_finished_handler: Optional[Callable[[Optional[MediaItem]], bool]] = None

        self.media_player.set_on_stop(self._handle_media_stop)
        self._load_state()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def bind_notifier(self, loop, notifier: Callable[[Dict[str, object]], None]) -> None:
        self._loop = loop
        self._notifier = notifier

    def set_media_finished_handler(self, handler: Optional[Callable[[Optional[MediaItem]], bool]]) -> None:
        self._media_finished_handler = handler

    def ensure_web(self, url: Optional[str] = None) -> None:
        target = url or self.current_url or self.homepage
        with self._lock:
            self.media_player.stop()
            self.current_media = None
            self._current_media_path = None
            self.mode = "web"
            self.current_url = target
            self._paused = False
        self.chromium.restart(target)
        self._save_state()
        self._notify()

    def navigate(self, url: str) -> None:
        with self._lock:
            self.mode = "web"
            self.current_url = url
            self.current_media = None
            self._current_media_path = None
            self._paused = False
        self.chromium.restart(url)
        self._save_state()
        self._notify()

    def play_media(self, identifier: str) -> MediaItem:
        item = self._resolve_media(identifier)
        if not item:
            raise FileNotFoundError(f"Media item '{identifier}' not found.")

        with self._lock:
            self.mode = "media"
            self.current_media = item
            self._current_media_path = str(item.path)
            self._paused = False

        self.chromium.stop()
        self.media_player.play(item)
        self._save_state()
        self._notify()
        return item

    def stop_media(self, fallback: bool = True) -> None:
        with self._lock:
            was_playing = self.mode == "media"
            resume_url = self.current_url or self.homepage
        self.media_player.stop()
        if not was_playing:
            return

        if fallback:
            self.ensure_web(resume_url)
        else:
            with self._lock:
                self.current_media = None
                self._current_media_path = None
                self._paused = False
            self._save_state()
            self._notify()

    def pause_media(self) -> None:
        self.media_player.pause()
        with self._lock:
            if self.mode == "media":
                self._paused = True
                self._save_state()
        self._notify()

    def resume_media(self) -> None:
        self.media_player.resume()
        with self._lock:
            if self.mode == "media":
                self._paused = False
                self._save_state()
        self._notify()

    def status(self) -> Dict[str, object]:
        with self._lock:
            payload = {
                "mode": self.mode,
                "url": self.current_url,
                "paused": self._paused,
                "media": self.current_media.to_dict() if self.current_media else None,
            }
        payload["player"] = self.media_player.status()
        return payload

    def restore(self) -> None:
        with self._lock:
            mode = self.mode
            url = self.current_url or self.homepage
            media_path = self._current_media_path

        if mode == "media" and media_path:
            item = self._resolve_media_by_path(Path(media_path))
            if not item:
                self.logger.warning("Persisted media %s missing; falling back to web mode.", media_path)
                self.ensure_web(url)
                return
            try:
                self.chromium.stop()
                self.media_player.play(item)
            except Exception:
                self.logger.exception("Failed to resume media playback for %s", media_path)
                self.ensure_web(url)
                return
            with self._lock:
                self.current_media = item
                self.mode = "media"
                self._paused = False
            self._notify()
            self._save_state()
        else:
            try:
                self.chromium.restart(url)
            except Exception:
                self.logger.exception("Failed to restore web session for %s", url)
            self._notify()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _handle_media_stop(self, item: Optional[MediaItem]) -> None:
        with self._lock:
            if self.mode != "media":
                return
            resume_url = self.current_url or self.homepage
            finished_item = item or self.current_media

        handled = False
        if self._media_finished_handler:
            try:
                handled = bool(self._media_finished_handler(finished_item))
            except Exception:  # pragma: no cover - defensive logging
                self.logger.exception("Media finished handler raised an error.")

        if handled:
            return

        with self._lock:
            self.mode = "web"
            self.current_media = None
            self._current_media_path = None
            self._paused = False

        try:
            self.chromium.start(resume_url)
        except Exception:
            self.logger.exception("Failed to relaunch Chromium after media finished.")
        self._save_state()
        self._notify()

    def _resolve_media(self, identifier: str) -> Optional[MediaItem]:
        item = self.library.get_by_identifier(identifier)
        if item:
            return item
        self.library.scan(force=True)
        return self.library.get_by_identifier(identifier)

    def _resolve_media_by_path(self, path: Path) -> Optional[MediaItem]:
        item = self.library.get_by_path(path)
        if item:
            return item
        self.library.scan(force=True)
        return self.library.get_by_path(path)

    def _load_state(self) -> None:
        if not self.state_path.exists():
            return
        try:
            with self.state_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            self.logger.warning("Failed to load persisted state from %s", self.state_path)
            return

        with self._lock:
            self.mode = data.get("mode", "web")
            self.current_url = data.get("url") or self.homepage
            self._current_media_path = data.get("media_path")
            self._paused = data.get("paused", False)

    def _save_state(self) -> None:
        payload = {
            "mode": self.mode,
            "url": self.current_url,
            "media_path": self._current_media_path,
            "paused": self._paused,
            "timestamp": time.time(),
        }
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            with self.state_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle)
        except OSError:
            self.logger.warning("Failed to persist state to %s", self.state_path)

    def _notify(self) -> None:
        if not (self._loop and self._notifier):
            return
        status = self.status()
        try:
            self._loop.call_soon_threadsafe(self._notifier, status)
        except RuntimeError:
            # Event loop may be shutting down; drop the notification.
            self.logger.debug("Event loop unavailable for state notification.")
