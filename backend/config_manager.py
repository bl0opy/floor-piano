"""
Persistent configuration and calibration management.

Settings live in data/settings.json (user overrides on top of defaults).
Calibration data lives in data/calibration.json.
"""

import json
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"

DEFAULTS_PATH = CONFIG_DIR / "defaults.json"
SETTINGS_PATH = DATA_DIR / "settings.json"
CALIBRATION_PATH = DATA_DIR / "calibration.json"


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_defaults() -> Dict[str, Any]:
    with open(DEFAULTS_PATH) as f:
        return json.load(f)


def load_settings() -> Dict[str, Any]:
    """Load defaults, then overlay any user-saved settings on top."""
    settings = load_defaults()
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH) as f:
                user = json.load(f)
            settings.update(user)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[Config] Warning: could not read settings.json: {e}")
    return settings


def save_settings(settings: Dict[str, Any]) -> None:
    _ensure_data_dir()
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)


def load_calibration() -> Dict[str, Any]:
    """Return calibration data, or a blank default if none saved."""
    if CALIBRATION_PATH.exists():
        try:
            with open(CALIBRATION_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[Config] Warning: could not read calibration.json: {e}")
    return {"regions": []}


def save_calibration(calibration: Dict[str, Any]) -> None:
    _ensure_data_dir()
    with open(CALIBRATION_PATH, "w") as f:
        json.dump(calibration, f, indent=2)
