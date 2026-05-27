"""
platform.py - Detección de plataforma de runtime.

`IS_ANDROID` se evalúa una sola vez al importar. Buildozer/python-for-android
inyecta la variable `ANDROID_ARGUMENT` en el entorno antes de lanzar la app,
así que su presencia es una forma confiable de detectar Android sin importar
módulos opcionales (jnius/android) que no existen en desktop.
"""

import os

IS_ANDROID = "ANDROID_ARGUMENT" in os.environ
