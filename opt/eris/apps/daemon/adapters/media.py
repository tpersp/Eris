import json
import logging
import mimetypes
import os
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Tuple

from utils.media_store import MediaMetadataStore


MEDIA_TYPE_MAP = {
    "video": {
        ".mp4",
        ".mkv",
        ".mov",
        ".webm",
        ".avi",
        ".m4v",
        ".ts",
    },
    "image": {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".webp",
    },
    "audio": {
        ".mp3",
        ".aac",
        ".flac",
        ".wav",
        ".ogg",
    },
}


def _normalise_extension(path: Path) -> str:
    return path.suffix.lower()


def _classify_media(path: Path) -> Optional[str]:
    extension = _normalise_extension(path)
    for media_type, extensions in MEDIA_TYPE_MAP.items():
        if extension in extensions:
            return media_type
    mime_type, _ = mimetypes.guess_type(str(path))
    if mime_type:
        if mime_type.startswith("video/"):
            return "video"
        if mime_type.startswith("audio/"):
            return "audio"
        if mime_type.startswith("image/"):
            return "image"
    return None


@dataclass
class MediaItem:
    identifier: str
    name: str
    source: str
    path: Path
    media_type: str
    size: int
    modified: float
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    mime_type: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["path"] = str(self.path)
        return payload


class MediaLibrary:
    """Indexes media items across local, network, and cache directories."""

    def __init__(
        self,
        roots: Iterable[Tuple[str, Path]],
        logger: Optional[logging.Logger] = None,
        metadata_store: Optional[MediaMetadataStore] = None,
        ffprobe_timeout: float = 5.0,
    ) -> None:
        self.logger = logger or logging.getLogger("eris.media.library")
        self.roots: List[Tuple[str, Path]] = [
            (name, Path(path)) for name, path in roots if path and Path(path).exists()
        ]
        self.ffprobe_timeout = ffprobe_timeout
        self.ffprobe_binary = shutil.which("ffprobe")
        self._cache_items: Optional[List[MediaItem]] = None
        self._cache_by_id: Dict[str, MediaItem] = {}
        self._cache_by_path: Dict[Path, MediaItem] = {}
        self._cache_timestamp: float = 0.0
        self.metadata_store = metadata_store

    def refresh_roots(self, roots: Iterable[Tuple[str, Path]]) -> None:
        self.roots = [(name, Path(path)) for name, path in roots if Path(path).exists()]
        self.invalidate_cache()

    def scan(self, force: bool = False) -> List[MediaItem]:
        if self._cache_items is not None and not force:
            return list(self._cache_items)

        items: List[MediaItem] = []
        for source_name, root in self.roots:
            for file_path in self._iter_files(root):
                media_type = _classify_media(file_path)
                if not media_type:
                    continue
                try:
                    stat_info = file_path.stat()
                except FileNotFoundError:
                    continue
                metadata = self._probe_metadata(file_path, media_type)
                identifier = f"{source_name}:{file_path.relative_to(root)}"
                tags: List[str] = []
                if self.metadata_store:
                    tags = self.metadata_store.get_tags(identifier)
                items.append(
                    MediaItem(
                        identifier=identifier,
                        name=file_path.name,
                        source=source_name,
                        path=file_path,
                        media_type=media_type,
                        size=stat_info.st_size,
                        modified=stat_info.st_mtime,
                        duration=metadata.get("duration"),
                        width=metadata.get("width"),
                        height=metadata.get("height"),
                        mime_type=metadata.get("mime_type"),
                        tags=tags,
                    )
                )
        items.sort(key=lambda item: (item.source, item.name.lower()))
        self._cache_items = items
        self._cache_by_id = {item.identifier: item for item in items}
        self._cache_by_path = {item.path: item for item in items}
        self._cache_timestamp = time.time()
        return list(items)

    def get_by_identifier(self, identifier: str) -> Optional[MediaItem]:
        if self._cache_items is None:
            self.scan()
        return self._cache_by_id.get(identifier)

    def get_by_path(self, path: Path) -> Optional[MediaItem]:
        if self._cache_items is None:
            self.scan()
        return self._cache_by_path.get(path)

    def invalidate_cache(self) -> None:
        self._cache_items = None
        self._cache_by_id = {}
        self._cache_by_path = {}
        self._cache_timestamp = 0.0

    def _iter_files(self, root: Path) -> Iterator[Path]:
        for dirpath, _, filenames in os.walk(root):
            for filename in filenames:
                yield Path(dirpath) / filename

    def _probe_metadata(self, path: Path, media_type: str) -> Dict[str, Optional[float]]:
        result: Dict[str, Optional[float]] = {}
        mime_type, _ = mimetypes.guess_type(str(path))
        if mime_type:
            result["mime_type"] = mime_type

        if not self.ffprobe_binary:
            return result

        try:
            cmd = [
                self.ffprobe_binary,
                "-v",
                "error",
                "-select_streams",
                "v:0" if media_type != "audio" else "a:0",
                "-show_entries",
                "stream=width,height,duration:format=duration",
                "-of",
                "json",
                str(path),
            ]
            process = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=self.ffprobe_timeout,
            )
            if process.returncode != 0:
                return result
            payload = json.loads(process.stdout.decode("utf-8"))
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            return result

        streams = payload.get("streams") or []
        if streams:
            stream = streams[0]
            width = stream.get("width")
            height = stream.get("height")
            duration = stream.get("duration")
            if width:
                try:
                    result["width"] = int(float(width))
                except (TypeError, ValueError):
                    pass
            if height:
                try:
                    result["height"] = int(float(height))
                except (TypeError, ValueError):
                    pass
            if duration:
                try:
                    result["duration"] = float(duration)
                except (TypeError, ValueError):
                    pass

        format_section = payload.get("format") or {}
        if "duration" in format_section and not result.get("duration"):
            try:
                result["duration"] = float(format_section["duration"])
            except (TypeError, ValueError):
                pass

        return result


class MediaPlayer:
    """Controls mpv/imv playback for Eris media content."""

    def __init__(
        self,
        mpv_binary: str = "mpv",
        imv_binary: str = "imv",
        ipc_socket: Path = Path("/tmp/eris-mpv.sock"),
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.mpv_binary = mpv_binary
        self.imv_binary = imv_binary
        self.ipc_socket = Path(ipc_socket)
        self.logger = logger or logging.getLogger("eris.media.player")

        self._lock = threading.Lock()
        self._mpv_process: Optional[subprocess.Popen] = None
        self._imv_process: Optional[subprocess.Popen] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._current_item: Optional[MediaItem] = None
        self._paused: bool = False
        self._on_stop: Optional[Callable[[Optional[MediaItem]], None]] = None

    def set_on_stop(self, callback: Callable[[Optional[MediaItem]], None]) -> None:
        self._on_stop = callback

    def play(self, item: MediaItem) -> None:
        with self._lock:
            self.stop()
            if item.media_type in {"video", "audio"}:
                self._launch_mpv(item)
            elif item.media_type == "image":
                self._launch_imv(item)
            else:
                raise ValueError(f"Unsupported media type: {item.media_type}")
            self._current_item = item
            self._paused = False

        self._ensure_monitor_thread()

    def stop(self) -> None:
        with self._lock:
            if self._mpv_process:
                self.logger.info("Stopping mpv playback.")
                self._terminate_process(self._mpv_process)
                self._mpv_process = None
            if self._imv_process:
                self.logger.info("Stopping imv session.")
                self._terminate_process(self._imv_process)
                self._imv_process = None
            self._current_item = None
            self._paused = False

    def pause(self) -> None:
        with self._lock:
            if not self._mpv_process:
                return
            self._send_mpv_command({"command": ["set_property", "pause", True]})
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            if not self._mpv_process:
                return
            self._send_mpv_command({"command": ["set_property", "pause", False]})
            self._paused = False

    def is_playing(self) -> bool:
        with self._lock:
            return bool(self._mpv_process or self._imv_process)

    def status(self) -> Dict[str, object]:
        with self._lock:
            item = self._current_item
            paused = self._paused
            mpv_active = self._mpv_process is not None
        position = None
        if mpv_active:
            response = self._send_mpv_command({"command": ["get_property", "time-pos"]}, expect_response=True)
            if response is not None:
                position = response
        return {
            "playing": bool(item),
            "paused": paused,
            "position": position,
            "item": item.to_dict() if item else None,
        }

    def _launch_mpv(self, item: MediaItem) -> None:
        if not shutil.which(self.mpv_binary):
            raise FileNotFoundError(f"mpv binary '{self.mpv_binary}' not found.")

        if self.ipc_socket.exists():
            try:
                self.ipc_socket.unlink()
            except OSError:
                self.logger.warning("Failed to remove stale mpv IPC socket %s.", self.ipc_socket)

        env = os.environ.copy()
        env.setdefault("DISPLAY", ":0")
        cmd = [
            self.mpv_binary,
            "--fs",
            "--no-border",
            "--really-quiet",
            "--force-window=yes",
            f"--input-ipc-server={self.ipc_socket}",
            str(item.path),
        ]
        self.logger.info("Launching mpv playback for %s", item.path)
        self._mpv_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )

    def _launch_imv(self, item: MediaItem) -> None:
        if not shutil.which(self.imv_binary):
            raise FileNotFoundError(f"imv binary '{self.imv_binary}' not found.")

        env = os.environ.copy()
        env.setdefault("DISPLAY", ":0")
        cmd = [
            self.imv_binary,
            "-f",
            str(item.path),
        ]
        self.logger.info("Launching imv to display %s", item.path)
        self._imv_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )

    def _terminate_process(self, process: subprocess.Popen, timeout: float = 5.0) -> None:
        try:
            process.terminate()
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.logger.warning("Media process did not exit in time; killing.")
            process.kill()
        finally:
            if process is self._mpv_process:
                self._mpv_process = None
            if process is self._imv_process:
                self._imv_process = None

    def _ensure_monitor_thread(self) -> None:
        with self._lock:
            if self._monitor_thread and self._monitor_thread.is_alive():
                return
            self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        while True:
            with self._lock:
                mpv_process = self._mpv_process
                imv_process = self._imv_process
                item = self._current_item
            if not mpv_process and not imv_process:
                return

            process = mpv_process or imv_process
            if process is None:
                time.sleep(0.5)
                continue

            return_code = process.wait()
            self.logger.info("Media process exited with code %s", return_code)
            with self._lock:
                if process is self._mpv_process:
                    self._mpv_process = None
                if process is self._imv_process:
                    self._imv_process = None
                finished_item = self._current_item
                self._current_item = None
                self._paused = False

            if self._on_stop and finished_item:
                try:
                    self._on_stop(finished_item)
                except Exception:  # pragma: no cover - defensive logging
                    self.logger.exception("Media on_stop callback failed.")

    def _send_mpv_command(
        self,
        payload: Dict[str, object],
        expect_response: bool = False,
    ) -> Optional[object]:
        if not self.ipc_socket.exists():
            return None

        data = json.dumps(payload) + "\n"
        response: Optional[object] = None
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(2.0)
                sock.connect(str(self.ipc_socket))
                sock.sendall(data.encode("utf-8"))
                if expect_response:
                    raw = sock.recv(4096)
                    if not raw:
                        return None
                    try:
                        reply = json.loads(raw.decode("utf-8"))
                    except json.JSONDecodeError:
                        return None
                    if isinstance(reply, dict) and "data" in reply:
                        response = reply["data"]
        except (socket.error, OSError):
            return None
        return response
