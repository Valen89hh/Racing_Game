"""
base_path.py - Centralized path resolution for source, PyInstaller frozen, and Android.

Tres entornos de runtime:

1. **Source (desktop)** — todo vive en el repo. `BASE_DIR` = repo root.
2. **PyInstaller frozen (Windows .exe)** — código bundled en `sys._MEIPASS`,
   data writable (tracks, models entrenados, brushes) next to el `.exe`.
3. **Android APK (Buildozer/p4a)** — código + assets read-only en el app dir.
   Data writable (settings, scores) en `os.environ["ANDROID_PRIVATE"]`.
   Los tracks pre-empacados y los `.onnx` van en read-only dentro de la APK.
"""

import os
import sys


def _is_android() -> bool:
    return "ANDROID_ARGUMENT" in os.environ


def get_base_dir():
    """Directorio con los archivos bundled (assets, código, data read-only)."""
    if _is_android():
        # En p4a, los .py y datos van en /data/data/<pkg>/files/app/. __file__
        # apunta dentro de utils/, así que subir un nivel da el app dir.
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if getattr(sys, "frozen", False):
        # PyInstaller --onedir: _MEIPASS = .../game/_internal/
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_writable_dir():
    """Directorio writable persistente para preferencias y archivos de usuario."""
    if _is_android():
        # p4a inyecta ANDROID_PRIVATE = /data/user/0/<pkg>/files (interno de la app).
        # Es persistente entre updates de la APK y privado al proceso.
        return os.environ.get("ANDROID_PRIVATE", get_base_dir())
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BASE_DIR = get_base_dir()
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

# En Android, tracks y models son read-only (van empacados en la APK).
# En desktop, son writable next al exe para permitir crear pistas y entrenar.
if _is_android():
    TRACKS_DIR = os.path.join(BASE_DIR, "tracks")
    MODELS_DIR = os.path.join(BASE_DIR, "models")
    BRUSHES_DIR = os.path.join(BASE_DIR, "brushes")
else:
    _WRITABLE = get_writable_dir()
    TRACKS_DIR = os.path.join(_WRITABLE, "tracks")
    MODELS_DIR = os.path.join(_WRITABLE, "models")
    BRUSHES_DIR = os.path.join(_WRITABLE, "brushes")
