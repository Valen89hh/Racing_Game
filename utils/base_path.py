"""
base_path.py - Centralized path resolution for source and frozen (PyInstaller) modes.
"""

import os
import sys


def get_base_dir():
    """Return the project root directory."""
    if getattr(sys, "frozen", False):
        # Running as PyInstaller bundle: exe is inside game/ folder
        return os.path.dirname(sys.executable)
    # Running from source
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BASE_DIR = get_base_dir()
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
TRACKS_DIR = os.path.join(BASE_DIR, "tracks")
BRUSHES_DIR = os.path.join(BASE_DIR, "brushes")
