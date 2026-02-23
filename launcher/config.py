"""
launcher/config.py - Launcher path resolution and configuration.
"""

import json
import os
import sys


def get_dist_root():
    """Return the distribution root directory (where launcher.exe lives)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # Dev mode: project root is one level up from launcher/
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


DIST_ROOT = get_dist_root()
VERSION_FILE = os.path.join(DIST_ROOT, "version.txt")
CONFIG_FILE = os.path.join(DIST_ROOT, "config.json")
GAME_DIR = os.path.join(DIST_ROOT, "game")
GAME_EXE = os.path.join(GAME_DIR, "game.exe")
TEMP_DIR = os.path.join(DIST_ROOT, "game_update_temp")
BACKUP_DIR = os.path.join(DIST_ROOT, "game_backup")


_DEFAULTS = {
    "update_url": "https://api.github.com/repos/OWNER/REPO/releases/latest",
    "version_url": "",
    "check_updates_on_launch": True,
    "auto_download": False,
    "connection_timeout": 10,
    "download_timeout": 300,
}


class LauncherConfig:
    """Loads and exposes config.json values with safe defaults."""

    def __init__(self):
        self._data = dict(_DEFAULTS)
        self._load()

    def _load(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for k, v in raw.items():
                if k in _DEFAULTS:
                    self._data[k] = v
        except (json.JSONDecodeError, OSError) as e:
            print(f"[launcher/config] WARNING: {e}")

    @property
    def update_url(self) -> str:
        return self._data["update_url"]

    @property
    def version_url(self) -> str:
        return self._data["version_url"]

    @property
    def check_on_launch(self) -> bool:
        return self._data["check_updates_on_launch"]

    @property
    def auto_download(self) -> bool:
        return self._data["auto_download"]

    @property
    def connection_timeout(self) -> int:
        return self._data["connection_timeout"]

    @property
    def download_timeout(self) -> int:
        return self._data["download_timeout"]
