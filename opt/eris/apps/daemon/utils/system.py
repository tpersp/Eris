import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

import psutil
import yaml

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = os.environ.get("ERIS_CONFIG_PATH", "/etc/eris/config.yaml")
DEFAULT_FLAGS_FILE = os.environ.get(
    "ERIS_CHROMIUM_FLAGS_FILE", "/etc/eris/chromium-flags.conf"
)
DEFAULT_CHROMIUM_BINARY = os.environ.get(
    "ERIS_CHROMIUM_BINARY", "/usr/bin/chromium-browser"
)

DEFAULT_CONFIG: Dict[str, Any] = {
    "ui": {"port": 8080},
    "device": {"homepage": "https://example.com"},
    "display": {
        "name": ":0",
        "launcher": "/usr/bin/xinit /opt/eris/scripts/kiosk-session.sh -- :0 -nolisten tcp",
        "startup_timeout": 12.0,
    },
    "chromium": {
        "flags_file": DEFAULT_FLAGS_FILE,
        "binary": DEFAULT_CHROMIUM_BINARY,
        "debug_port": 9222,
    },
    "media": {
        "use_network": False,
        "network_path": "",
        "mount_point": "/mnt/eris_media",
        "local_path": "/var/lib/eris/media/local",
        "cache_path": "/var/lib/eris/media/cache",
        "mpv_binary": "mpv",
        "imv_binary": "imv",
        "image_duration": 30,
        "metadata_path": "/var/lib/eris/media/metadata.json",
        "max_upload_mb": 200,
    },
    "state": {
        "path": "/var/lib/eris/state.json",
        "playlist_path": "/var/lib/eris/playlists.json",
    },
    "security": {
        "password_hash": "",
        "token_secret": "",
        "token_ttl": 3600,
    },
    "scheduler": {
        "tick_interval": 15,
    },
}


def load_config(path: str = "") -> Dict[str, Any]:
    config = DEFAULT_CONFIG.copy()
    config_path = Path(path or DEFAULT_CONFIG_PATH)
    if not config_path.exists():
        logger.warning("Configuration file %s missing; using defaults.", config_path)
        return config

    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
            _deep_merge(config, data)
    except Exception as exc:
        logging.getLogger(__name__).warning("Failed to load config: %s", exc)
    return config


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def get_cpu_percent() -> float:
    return psutil.cpu_percent(interval=None)


def get_memory_percent() -> float:
    return psutil.virtual_memory().percent


def get_temperature() -> float:
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for entries in temps.values():
                if entries:
                    return float(entries[0].current)
    except Exception:
        pass

    zone_path = Path("/sys/class/thermal/thermal_zone0/temp")
    if zone_path.exists():
        try:
            raw = zone_path.read_text().strip()
            return float(raw) / 1000.0
        except Exception:
            pass
    return float("nan")


def set_display_blank(on: bool) -> None:
    logger = logging.getLogger(__name__)
    state = "on" if on else "off"
    logger.info("Display blanking requested: %s", state)

    display = os.environ.get("DISPLAY") or ":0"
    os.environ.setdefault("DISPLAY", display)

    xset_binary = shutil.which("xset")
    if not xset_binary:
        logger.warning("xset binary not found; cannot toggle display blanking.")
        return

    command = [xset_binary, "-display", display, "dpms", "force", "off" if on else "on"]
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as exc:
        logger.error("DPMS command failed: %s", exc)
