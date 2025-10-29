import json
import logging
import threading
from pathlib import Path
from typing import Dict, List


class MediaMetadataStore:
    def __init__(self, path: Path, logger: logging.Logger) -> None:
        self.path = path
        self.logger = logger
        self._lock = threading.Lock()
        self._data: Dict[str, Dict[str, object]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._data = {}
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                self._data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            self.logger.warning("Failed to load media metadata from %s; starting fresh.", self.path)
            self._data = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(self._data, handle, indent=2)

    def get_tags(self, identifier: str) -> List[str]:
        with self._lock:
            entry = self._data.get(identifier, {})
            tags = entry.get("tags") or []
            return list(tags)

    def set_tags(self, identifier: str, tags: List[str]) -> None:
        clean_tags = sorted({tag.strip() for tag in tags if tag and tag.strip()})
        with self._lock:
            entry = self._data.setdefault(identifier, {})
            entry["tags"] = clean_tags
            self._save()

    def remove(self, identifier: str) -> None:
        with self._lock:
            if identifier in self._data:
                self._data.pop(identifier)
                self._save()
