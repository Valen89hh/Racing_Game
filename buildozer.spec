[app]

# (str) Title shown on the launcher icon
title = Arcade Racing 2D

# (str) Package name (used in the APK file name)
package.name = arcaderacing

# (str) Reverse-DNS package domain
package.domain = pe.tecsup.racing

# (str) Source code directory (where main.py lives)
source.dir = .

# Solo empaquetar los tipos de archivo que el juego usa en runtime.
# `.zip` se excluye (modelos PPO desktop). `.onnx` sí va.
source.include_exts = py,png,jpg,jpeg,wav,ogg,mp3,json,onnx,npz,ttf,otf

# Carpetas completas excluidas del APK (código que no corre en móvil):
#   - venv:       virtualenv de desarrollo
#   - dist/build: outputs de PyInstaller
#   - launcher:   auto-updater Windows
#   - training:   PPO/SB3/PyTorch (no se puede compilar para ARM)
#   - server:     dedicated server (no aplica en cliente móvil)
#   - relay_server: standalone relay (corre en VPS)
#   - tools:      scripts de mantenimiento desktop
#   - .buildozer/.git/bin/__pycache__: artefactos de build
source.exclude_dirs = venv, dist, build, launcher, training, server, relay_server, tools, .buildozer, .git, bin, __pycache__

# Patrones específicos a excluir.
#   - editor.py:     usa teclado/mouse intenso, no portado a táctil
#   - models/*.zip:  modelos PPO (sólo .onnx van al APK)
#   - *.spec/.bat/.sh: scripts de build desktop/server
#   - relay_server*: por si quedó algo suelto
source.exclude_patterns = editor.py, models/*.zip, *.spec, build_*.bat, build_*.sh, deploy_*.sh, server/requirements-server.txt

# (str) Application version
version = 1.3.0

# Dependencias Python.
#   - python3:        runtime (p4a lo cross-compila — la versión la fija p4a;
#                     con python-for-android==2024.1.21 → Python 3.11)
#   - pygame:         upstream pygame (NO pygame_ce). Razón: p4a tiene un
#                     recipe oficial para `pygame` que sí cross-compila para
#                     ARM64. `pygame_ce` no tiene recipe → p4a hace pip install
#                     y mete el wheel x86_64 de PyPI, que crashea en el celular
#                     con "is for EM_X86_64 instead of EM_AARCH64".
#                     El upstream pygame solo rompe con Python 3.12+ (header
#                     longintrepr.h removido); por eso pinneamos p4a al 2024.1
#                     en el workflow, donde el default sigue siendo 3.11.
#   - numpy:          observación, math e inferencia del bot (recipe oficial)
#
# `onnxruntime` se quitó porque tampoco tiene recipe de p4a. El código cae
# automáticamente al backend numpy puro (loads .npz), validado al 100% contra
# onnxruntime en desktop.
requirements = python3,pygame,numpy

# Orientación forzada — el juego está pensado en 1280x720 (16:9) horizontal.
orientation = landscape

# Pantalla completa (sin status bar de Android).
fullscreen = 1

# Permisos.
#   - INTERNET:        modo multijugador relay (conexión saliente al VPS)
#   - WAKE_LOCK:       mantener pantalla activa durante carreras largas
android.permissions = INTERNET, WAKE_LOCK

# (list) Architecturas a buildear. Empezar con arm64-v8a (todos los celulares
# modernos). Si necesitas compatibilidad con dispositivos viejos, añadir armeabi-v7a.
android.archs = arm64-v8a

# API target / min API.
#   - api 33 (Android 13): requerido por Play Store en 2024+
#   - minapi 24 (Android 7.0): cubre >97% de dispositivos en uso
android.api = 33
android.minapi = 24

# NDK / SDK — usar los que Buildozer descargue automáticamente.
# android.ndk = 25b
# android.sdk = 33

# Aceptar licencias del SDK automáticamente (necesario en CI sin interactividad).
android.accept_sdk_license = True

# (str) Presplash de la app (logo durante el arranque).
# presplash.filename = %(source.dir)s/assets/presplash.png

# (str) Icon de la app.
# icon.filename = %(source.dir)s/assets/icon.png

# (bool) Logs en logcat durante el primer arranque (útil para depurar el
# extract de assets en `/data/data/.../files/app/`).
android.logcat_filters = *:S python:D

# (str) Si quieres firmar para Play Store, configura keystore.
# android.release_artifact = aab
# android.keystore = path/to/keystore
# android.keyalias = arcaderacing

# Recipe customizada para ONNX Runtime (descomentar si falla la build estándar).
# p4a.local_recipes = ./p4a-recipes

# CRÍTICO: Buildozer clona python-for-android desde GitHub e IGNORA cualquier
# pip install de p4a. Por defecto clona `master`, donde el python3 recipe
# defaultea a Python 3.14 — y con esa versión el `pygame` upstream NO compila
# (src_c/_sdl2/sdl2.c:211 incluye `longintrepr.h`, removido en Python 3.12).
#
# Pinneamos al tag `2024.1.21` donde el python3 recipe construye Python 3.9/3.11
# y el `pygame` recipe compila sin problemas para ARM64.
p4a.branch = 2024.1.21


[buildozer]

# Nivel de log: 2 = info (recomendado para depurar la primera build)
log_level = 2

# Si Buildozer se queja por correr como root, esto lo permite (no recomendado
# en general; mantener en 0 a menos que sea estrictamente necesario).
warn_on_root = 1
