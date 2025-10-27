import logging
import os
from pathlib import Path
from typing import Any, Dict

import psutil
import yaml

DEFAULT_CONFIG: Dict[str, Any] = {
    "ui": {"port": 8080},
    "device": {"homepage": "https://example.com"},
    "chromium": {
        "flags_file": "/etc/eris/chromium_flags",
        "binary": "/usr/bin/chromium-browser",
    },
}


def load_config(path: str = "/etc/eris/config.yaml") -> Dict[str, Any]:
    config = DEFAULT_CONFIG.copy()
    config_path = Path(path)
    if not config_path.exists():
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
    state = "on" if on else "off"
    logging.getLogger(__name__).info("Display blanking requested: %s", state)
    # Placeholder for future DPMS/xset integration.
    if not os.environ.get("DISPLAY"):
        os.environ.setdefault("DISPLAY", ":0")

