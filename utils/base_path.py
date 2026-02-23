"""
base_path.py - Centralized path resolution for source and frozen (PyInstaller) modes.
"""

import os
import sys


def get_base_dir():
    """Return the directory where bundled data files live.

    - Frozen (PyInstaller): sys._MEIPASS (where datas are extracted/stored).
      In --onedir this is the _internal/ folder; in --onefile a temp dir.
    - Source: project root (parent of utils/).
    """
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_writable_dir():
    """Return a writable directory next to the executable.

    Used for user-created tracks and brushes that must persist across updates.
    In source mode this is the same as get_base_dir().
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BASE_DIR = get_base_dir()
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

# Tracks and brushes are writable — live next to the exe so users keep them
_WRITABLE = get_writable_dir()
TRACKS_DIR = os.path.join(_WRITABLE, "tracks")
BRUSHES_DIR = os.path.join(_WRITABLE, "brushes")
