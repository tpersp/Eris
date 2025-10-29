import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Dict, List, Optional

from adapters.media import MediaItem, MediaLibrary
from controllers.content import ContentRouter

WEEKDAY_MAP = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


def _parse_time(value: str) -> time:
    hours, minutes = value.split(":", 1)
    return time(hour=int(hours), minute=int(minutes))


def _format_time(value: time) -> str:
    return value.strftime("%H:%M")


@dataclass
class PlaylistItemDef:
    media_id: str
    duration: Optional[int] = None


@dataclass
class PlaylistDef:
    playlist_id: str
    name: str
    items: List[PlaylistItemDef] = field(default_factory=list)
    loop: bool = True


@dataclass
class ScheduleDef:
    schedule_id: str
    playlist_id: str
    start: time
    end: time
    days: List[int]

    def is_active(self, now: datetime) -> bool:
        weekday = now.weekday()
        if self.days and weekday not in self.days:
            return False

        start_time = self.start
        end_time = self.end
        current = now.time()

        if start_time <= end_time:
            return start_time <= current < end_time

        # Overnight schedule (e.g., 22:00 -> 06:00)
        return current >= start_time or current < end_time


class PlaylistStore:
    def __init__(self, path: Path, logger: Optional[logging.Logger] = None) -> None:
        self.path = path
        self.logger = logger or logging.getLogger("eris.playlists")
        self._data: Dict[str, object] = {}
        self._mtime: float = 0.0
        self.refresh()

    # Data management --------------------------------------------------
    def refresh(self) -> None:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            self._data = self._default_data()
            self._mtime = 0.0
            return

        if mtime == self._mtime and self._data:
            return

        try:
            with self.path.open("r", encoding="utf-8") as handle:
                self._data = json.load(handle)
            self._mtime = mtime
        except (OSError, json.JSONDecodeError):
            self.logger.warning("Failed to load playlist data from %s; resetting.", self.path)
            self._data = self._default_data()
            self._mtime = 0.0

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(self._data, handle, indent=2)
        self._mtime = self.path.stat().st_mtime

    @staticmethod
    def _default_data() -> Dict[str, object]:
        return {
            "playlists": [],
            "schedules": [],
            "fallback": {"mode": "web", "url": ""},
        }

    # Playlist helpers -------------------------------------------------
    def list_playlists(self) -> List[Dict[str, object]]:
        self.refresh()
        return list(self._data.get("playlists", []))

    def get_playlist(self, playlist_id: str) -> Optional[PlaylistDef]:
        self.refresh()
        for entry in self._data.get("playlists", []):
            if entry.get("id") == playlist_id:
                return self._decode_playlist(entry)
        return None

    def upsert_playlist(self, playlist: Dict[str, object]) -> PlaylistDef:
        self.refresh()
        playlist_id = playlist.get("id")
        if not playlist_id:
            raise ValueError("Playlist id is required")

        decoded = self._decode_playlist(playlist)
        entries = self._data.setdefault("playlists", [])
        for index, entry in enumerate(entries):
            if entry.get("id") == playlist_id:
                entries[index] = self._encode_playlist(decoded)
                break
        else:
            entries.append(self._encode_playlist(decoded))
        self.save()
        return decoded

    def delete_playlist(self, playlist_id: str) -> None:
        self.refresh()
        entries = self._data.setdefault("playlists", [])
        before = len(entries)
        self._data["playlists"] = [entry for entry in entries if entry.get("id") != playlist_id]
        if len(self._data["playlists"]) != before:
            self.save()

    # Schedule helpers -------------------------------------------------
    def list_schedules(self) -> List[Dict[str, object]]:
        self.refresh()
        return list(self._data.get("schedules", []))

    def get_schedule(self, schedule_id: str) -> Optional[ScheduleDef]:
        self.refresh()
        for entry in self._data.get("schedules", []):
            if entry.get("id") == schedule_id:
                return self._decode_schedule(entry)
        return None

    def upsert_schedule(self, schedule: Dict[str, object]) -> ScheduleDef:
        self.refresh()
        schedule_id = schedule.get("id")
        if not schedule_id:
            raise ValueError("Schedule id is required")

        decoded = self._decode_schedule(schedule)
        entries = self._data.setdefault("schedules", [])
        for index, entry in enumerate(entries):
            if entry.get("id") == schedule_id:
                entries[index] = self._encode_schedule(decoded)
                break
        else:
            entries.append(self._encode_schedule(decoded))
        self.save()
        return decoded

    def delete_schedule(self, schedule_id: str) -> None:
        self.refresh()
        entries = self._data.setdefault("schedules", [])
        before = len(entries)
        self._data["schedules"] = [entry for entry in entries if entry.get("id") != schedule_id]
        if len(self._data["schedules"]) != before:
            self.save()

    # Fallback ---------------------------------------------------------
    def get_fallback(self) -> Dict[str, object]:
        self.refresh()
        return dict(self._data.get("fallback", {"mode": "web", "url": ""}))

    def set_fallback(self, fallback: Dict[str, object]) -> None:
        self.refresh()
        allowed_modes = {"web", "playlist"}
        mode = fallback.get("mode", "web")
        if mode not in allowed_modes:
            raise ValueError("Fallback mode must be 'web' or 'playlist'")
        self._data["fallback"] = {"mode": mode, "url": fallback.get("url", ""), "playlist_id": fallback.get("playlist_id")}
        self.save()

    # Resolution -------------------------------------------------------
    def resolve(self, moment: datetime) -> Dict[str, Optional[str]]:
        self.refresh()
        schedules = [self._decode_schedule(entry) for entry in self._data.get("schedules", [])]
        for schedule in schedules:
            if schedule.is_active(moment):
                return {
                    "mode": "playlist",
                    "playlist_id": schedule.playlist_id,
                    "schedule_id": schedule.schedule_id,
                }

        fallback = self.get_fallback()
        if fallback.get("mode") == "playlist" and fallback.get("playlist_id"):
            return {
                "mode": "playlist",
                "playlist_id": fallback.get("playlist_id"),
                "schedule_id": None,
            }

        return {"mode": "web", "url": fallback.get("url"), "playlist_id": None, "schedule_id": None}

    # Decoding helpers -------------------------------------------------
    def _decode_playlist(self, data: Dict[str, object]) -> PlaylistDef:
        items = []
        for item in data.get("items", []):
            media_id = item.get("media_id")
            if not media_id:
                raise ValueError("Playlist items require media_id")
            duration = item.get("duration")
            if duration is not None:
                duration = int(duration)
            items.append(PlaylistItemDef(media_id=media_id, duration=duration))
        return PlaylistDef(
            playlist_id=data.get("id"),
            name=data.get("name", "Unnamed"),
            items=items,
            loop=bool(data.get("loop", True)),
        )

    def _encode_playlist(self, playlist: PlaylistDef) -> Dict[str, object]:
        return {
            "id": playlist.playlist_id,
            "name": playlist.name,
            "loop": playlist.loop,
            "items": [
                {"media_id": item.media_id, **({"duration": item.duration} if item.duration else {})}
                for item in playlist.items
            ],
        }

    def _decode_schedule(self, data: Dict[str, object]) -> ScheduleDef:
        start = _parse_time(data.get("start", "00:00"))
        end = _parse_time(data.get("end", "23:59"))
        raw_days = data.get("days", []) or []
        days = []
        for value in raw_days:
            key = str(value).lower()
            if key in WEEKDAY_MAP:
                days.append(WEEKDAY_MAP[key])
            else:
                raise ValueError(f"Unknown weekday '{value}'")
        return ScheduleDef(
            schedule_id=data.get("id"),
            playlist_id=data.get("playlist_id"),
            start=start,
            end=end,
            days=days,
        )

    def _encode_schedule(self, schedule: ScheduleDef) -> Dict[str, object]:
        inverse_map = {v: k for k, v in WEEKDAY_MAP.items()}
        return {
            "id": schedule.schedule_id,
            "playlist_id": schedule.playlist_id,
            "start": _format_time(schedule.start),
            "end": _format_time(schedule.end),
            "days": [inverse_map[day] for day in schedule.days],
        }


class PlaybackScheduler:
    def __init__(
        self,
        store: PlaylistStore,
        content_router: ContentRouter,
        media_library: MediaLibrary,
        homepage: str,
        logger: Optional[logging.Logger] = None,
        tick_interval: int = 15,
        default_image_duration: int = 30,
    ) -> None:
        self.store = store
        self.content_router = content_router
        self.media_library = media_library
        self.homepage = homepage
        self.logger = logger or logging.getLogger("eris.scheduler")
        self.tick_interval = max(5, tick_interval)
        self.default_image_duration = max(5, default_image_duration)

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._task: Optional[asyncio.Task] = None
        self._image_timer: Optional[asyncio.TimerHandle] = None

        self._playlist_active_flag = asyncio.Event()
        self._current_playlist_id: Optional[str] = None
        self._current_schedule_id: Optional[str] = None
        self._current_index: int = 0

    async def start(self) -> None:
        if self._task:
            return
        self._loop = asyncio.get_running_loop()
        self.content_router.set_media_finished_handler(self._handle_media_finished)
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self.content_router.set_media_finished_handler(None)
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._image_timer:
            self._image_timer.cancel()
            self._image_timer = None
        self._playlist_active_flag.clear()
        self._current_playlist_id = None
        self._current_schedule_id = None

    async def _run(self) -> None:
        try:
            while True:
                await self._evaluate()
                await asyncio.sleep(self.tick_interval)
        except asyncio.CancelledError:
            self.logger.debug("Scheduler loop cancelled")

    async def _evaluate(self) -> None:
        decision = self.store.resolve(datetime.now())
        mode = decision.get("mode")
        if mode == "playlist":
            playlist_id = decision.get("playlist_id")
            schedule_id = decision.get("schedule_id")
            await self._activate_playlist(playlist_id, schedule_id)
        else:
            await self._deactivate_playlist()
            url = decision.get("url") or self.homepage
            await self._ensure_web(url)

    async def _activate_playlist(self, playlist_id: Optional[str], schedule_id: Optional[str]) -> None:
        if not playlist_id:
            return

        if (
            self._playlist_active_flag.is_set()
            and self._current_playlist_id == playlist_id
            and self._current_schedule_id == schedule_id
        ):
            # Already active; nothing to do.
            if self.content_router.status().get("mode") != "media":
                await self._play_current_item()
            return

        playlist = self.store.get_playlist(playlist_id)
        if not playlist or not playlist.items:
            self.logger.warning("Playlist %s is empty or missing.", playlist_id)
            await self._deactivate_playlist()
            return

        self._current_playlist_id = playlist_id
        self._current_schedule_id = schedule_id
        self._current_index = 0
        self._playlist_active_flag.set()
        await self._play_current_item()

    async def _deactivate_playlist(self) -> None:
        if not self._playlist_active_flag.is_set():
            return
        self._playlist_active_flag.clear()
        self._current_playlist_id = None
        self._current_schedule_id = None
        if self._image_timer:
            self._image_timer.cancel()
            self._image_timer = None

    async def _ensure_web(self, url: str) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.content_router.ensure_web, url)

    async def _play_current_item(self) -> None:
        if not self._playlist_active_flag.is_set() or not self._current_playlist_id:
            return

        playlist = self.store.get_playlist(self._current_playlist_id)
        if not playlist or not playlist.items:
            await self._deactivate_playlist()
            return

        if self._current_index >= len(playlist.items):
            self._current_index = 0

        item_def = playlist.items[self._current_index]
        media_item = self._resolve_media(item_def.media_id)
        if not media_item:
            self.logger.warning("Media %s missing for playlist %s", item_def.media_id, playlist.playlist_id)
            self._current_index += 1
            await self._play_current_item()
            return

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.content_router.play_media, media_item.identifier)

        if self._image_timer:
            self._image_timer.cancel()
            self._image_timer = None

        duration = item_def.duration
        if (duration is None or duration <= 0) and media_item.media_type == "image":
            duration = self.default_image_duration

        if duration and duration > 0:
            self._image_timer = self._loop.call_later(duration, self._schedule_next_item)

    def _schedule_next_item(self) -> None:
        if not self._loop:
            return
        self._loop.create_task(self._advance_playlist())

    async def _advance_playlist(self) -> None:
        if not self._playlist_active_flag.is_set():
            return
        self._current_index += 1
        await self._play_current_item()

    def _handle_media_finished(self, item: Optional[MediaItem]) -> bool:
        if not self._playlist_active_flag.is_set() or not self._loop:
            return False

        self._loop.create_task(self._advance_playlist())
        return True

    def status(self) -> Dict[str, object]:
        return {
            "active": self._playlist_active_flag.is_set(),
            "playlist_id": self._current_playlist_id,
            "schedule_id": self._current_schedule_id,
            "index": self._current_index,
        }

    def request_refresh(self) -> None:
        if not self._loop:
            return

        def trigger() -> None:
            self._loop.create_task(self._evaluate())

        self._loop.call_soon_threadsafe(trigger)

    def _resolve_media(self, identifier: str) -> Optional[MediaItem]:
        item = self.media_library.get_by_identifier(identifier)
        if item:
            return item
        self.media_library.scan(force=True)
        return self.media_library.get_by_identifier(identifier)
