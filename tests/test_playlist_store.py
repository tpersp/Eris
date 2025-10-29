from datetime import datetime

from daemon.controllers.scheduler import PlaylistStore


def test_playlist_store_resolve(tmp_path):
    store_path = tmp_path / "playlists.json"
    store = PlaylistStore(store_path, logger=_DummyLogger())

    playlist = store.upsert_playlist(
        {
            "id": "loop",
            "name": "Loop",
            "items": [
                {"media_id": "local:demo.mp4", "duration": 45},
                {"media_id": "local:promo.png"}
            ]
        }
    )
    assert playlist.playlist_id == "loop"

    schedule = store.upsert_schedule(
        {
            "id": "weekday-morning",
            "playlist_id": "loop",
            "start": "08:00",
            "end": "12:00",
            "days": ["mon", "tue", "wed"]
        }
    )
    assert schedule.schedule_id == "weekday-morning"

    monday_morning = datetime(2024, 1, 1, 9, 0)  # Monday
    resolved = store.resolve(monday_morning)
    assert resolved["mode"] == "playlist"
    assert resolved["playlist_id"] == "loop"
    assert resolved["schedule_id"] == "weekday-morning"

    sunday = datetime(2024, 1, 7, 10, 0)
    store.set_fallback({"mode": "playlist", "playlist_id": "loop"})
    fallback = store.resolve(sunday)
    assert fallback["mode"] == "playlist"
    assert fallback["schedule_id"] is None


class _DummyLogger:
    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def exception(self, *args, **kwargs):
        pass
