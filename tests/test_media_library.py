from pathlib import Path

from daemon.adapters.media import MediaLibrary
from daemon.utils.media_store import MediaMetadataStore


def test_media_library_scans_with_metadata(tmp_path):
    local_root = tmp_path / "media" / "local"
    cache_root = tmp_path / "media" / "cache"
    local_root.mkdir(parents=True)
    cache_root.mkdir(parents=True)

    sample_file = local_root / "demo.mp4"
    sample_file.write_text("sample", encoding="utf-8")

    metadata_path = tmp_path / "metadata.json"
    metadata_store = MediaMetadataStore(metadata_path, logger=_DummyLogger())
    metadata_store.set_tags("local:demo.mp4", ["promo", "launch"])

    library = MediaLibrary(
        roots=[("local", local_root), ("cache", cache_root)],
        logger=_DummyLogger(),
        metadata_store=metadata_store,
        ffprobe_timeout=0.1,
    )

    items = library.scan(force=True)
    assert len(items) == 1
    item = items[0]
    assert item.name == "demo.mp4"
    assert item.tags == ["launch", "promo"]


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
