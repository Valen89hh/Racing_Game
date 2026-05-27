#!/usr/bin/env bash
# build_android.sh - Automatiza el build de la APK con Buildozer (en WSL2/Linux).
#
# Modos:
#   ./build_android.sh --setup        Instala dependencias del sistema + Buildozer.
#   ./build_android.sh                Build debug (default).
#   ./build_android.sh --release      Build release sin firmar (necesitas firmar después).
#   ./build_android.sh --clean        Borra el cache de Buildozer (.buildozer/, bin/).
#   ./build_android.sh --no-onnx      Quita onnxruntime del spec antes de buildear
#                                     (forza el backend numpy puro).
#   ./build_android.sh --install      Tras buildear, instala el APK vía adb.
#   ./build_android.sh --logs         Sigue logcat del dispositivo (filtrado a python).
#
# Uso típico la primera vez (en WSL2 Ubuntu):
#     ./build_android.sh --setup
#     ./build_android.sh                # primera build: 30-60 min
#     ./build_android.sh --install      # con el celular conectado en modo dev

set -euo pipefail

# ─── Colores ──────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
    GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RED=$'\033[0;31m'; CYAN=$'\033[0;36m'; RESET=$'\033[0m'
else
    GREEN=""; YELLOW=""; RED=""; CYAN=""; RESET=""
fi

log()   { printf '%s[*]%s %s\n' "$CYAN" "$RESET" "$*"; }
ok()    { printf '%s[OK]%s %s\n' "$GREEN" "$RESET" "$*"; }
warn()  { printf '%s[!]%s %s\n' "$YELLOW" "$RESET" "$*"; }
fatal() { printf '%s[X]%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

# ─── Parseo de argumentos (antes del check de OS para que --help funcione) ────
MODE="build"          # build | setup | clean
TARGET="debug"        # debug | release
NO_ONNX=0
DO_INSTALL=0
DO_LOGS=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --setup)    MODE="setup"; shift ;;
        --clean)    MODE="clean"; shift ;;
        --release)  TARGET="release"; shift ;;
        --no-onnx)  NO_ONNX=1; shift ;;
        --install)  DO_INSTALL=1; shift ;;
        --logs)     DO_LOGS=1; shift ;;
        -h|--help)
            sed -n '2,17p' "$0"; exit 0 ;;
        *) fatal "Argumento desconocido: $1 (usa --help)" ;;
    esac
done

# ─── Verificaciones de entorno ────────────────────────────────────────────────
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

[[ -f buildozer.spec ]] || fatal "No se encuentra buildozer.spec en $PROJECT_DIR"

if [[ "$(uname -s)" != "Linux" ]]; then
    fatal "Este script sólo corre en Linux (usa WSL2 en Windows)."
fi

# Buildozer no acepta correr como root salvo que se permita explícitamente.
if [[ $EUID -eq 0 ]]; then
    warn "Ejecutando como root — no recomendado. Continuando bajo tu riesgo."
fi

# ─── Modo: SETUP ──────────────────────────────────────────────────────────────
if [[ "$MODE" == "setup" ]]; then
    log "Instalando dependencias del sistema (necesita sudo)..."
    sudo apt update
    sudo apt install -y \
        python3-pip python3-venv python3-dev \
        git zip unzip \
        openjdk-17-jdk \
        autoconf libtool pkg-config \
        zlib1g-dev libncurses-dev libncursesw5-dev libtinfo6 \
        cmake libffi-dev libssl-dev \
        ccache

    log "Creando venv local en .venv-buildozer..."
    python3 -m venv .venv-buildozer
    # shellcheck disable=SC1091
    source .venv-buildozer/bin/activate

    log "Instalando Buildozer + Cython (versión compatible)..."
    pip install --upgrade pip wheel
    pip install "cython==0.29.36" buildozer

    ok "Setup completo."
    log "Próximos pasos:"
    echo "    source .venv-buildozer/bin/activate"
    echo "    ./build_android.sh                 # build debug"
    exit 0
fi

# ─── Modo: CLEAN ──────────────────────────────────────────────────────────────
if [[ "$MODE" == "clean" ]]; then
    log "Limpiando artefactos de Buildozer..."
    rm -rf .buildozer bin
    ok "Cache limpiado. La próxima build re-descargará NDK + dependencias."
    exit 0
fi

# ─── Activar venv si existe ───────────────────────────────────────────────────
if [[ -d .venv-buildozer ]]; then
    # shellcheck disable=SC1091
    source .venv-buildozer/bin/activate
    log "Usando venv local .venv-buildozer/ (python: $(which python3))"
fi

# ─── Verificar Buildozer ──────────────────────────────────────────────────────
if ! command -v buildozer &>/dev/null; then
    fatal "Buildozer no instalado. Ejecuta primero: ./build_android.sh --setup"
fi
log "Buildozer: $(buildozer --version 2>&1 | head -1)"

# ─── Verificar que los .onnx/.npz están presentes ─────────────────────────────
ONNX_COUNT=$(find models -name '*.onnx' 2>/dev/null | wc -l)
NPZ_COUNT=$(find models -name '*.npz' 2>/dev/null | wc -l)
log "Modelos para empacar: ${ONNX_COUNT} .onnx, ${NPZ_COUNT} .npz"
if [[ $ONNX_COUNT -eq 0 && $NPZ_COUNT -eq 0 ]]; then
    warn "No hay modelos exportados. Corre primero:"
    warn "    python tools/export_ppo_to_onnx.py"
    warn "Continuando sin modelos — los bots usarán AISystem (waypoints)."
fi

# ─── Modo: --no-onnx → backup del spec y patch temporal ───────────────────────
if [[ $NO_ONNX -eq 1 ]]; then
    log "Modo --no-onnx: quitando onnxruntime de requirements temporalmente."
    cp buildozer.spec buildozer.spec.bak
    sed -i 's/^requirements = \(.*\),onnxruntime/requirements = \1/' buildozer.spec
    sed -i 's/^requirements = \(.*\)onnxruntime,/requirements = \1/' buildozer.spec
    trap 'mv buildozer.spec.bak buildozer.spec 2>/dev/null || true' EXIT
fi

# ─── Build ────────────────────────────────────────────────────────────────────
log "Iniciando build: target=$TARGET"
log "La primera build descarga ~500MB (NDK) y tarda 30-60 min. Ten paciencia."

START_TIME=$(date +%s)
if buildozer android "$TARGET"; then
    ELAPSED=$(( $(date +%s) - START_TIME ))
    ok "Build completado en ${ELAPSED}s"
else
    EXIT_CODE=$?
    fatal "Build falló (exit $EXIT_CODE). Tips:
    - Si falla en compilar 'onnxruntime': ./build_android.sh --no-onnx
    - Para empezar de cero:                ./build_android.sh --clean
    - Logs completos en:                   .buildozer/android/platform/build-*/*.log
    - Mirar el último error:               buildozer android debug 2>&1 | tail -50"
fi

# ─── Localizar el APK generado ────────────────────────────────────────────────
APK_PATH=$(find bin -maxdepth 1 -name '*.apk' -newer buildozer.spec 2>/dev/null | head -1)
if [[ -z "$APK_PATH" ]]; then
    APK_PATH=$(find bin -maxdepth 1 -name '*.apk' 2>/dev/null | head -1)
fi

if [[ -n "$APK_PATH" ]]; then
    APK_SIZE=$(du -h "$APK_PATH" | cut -f1)
    ok "APK generado: $APK_PATH ($APK_SIZE)"
else
    warn "No se encontró el APK en bin/. Revisa los logs."
fi

# ─── Instalar APK ─────────────────────────────────────────────────────────────
if [[ $DO_INSTALL -eq 1 && -n "$APK_PATH" ]]; then
    if ! command -v adb &>/dev/null; then
        warn "adb no instalado. Instálalo con: sudo apt install android-tools-adb"
    elif ! adb devices | grep -qE '\sdevice$'; then
        warn "No hay dispositivos conectados. Conecta el celular en modo desarrollador."
    else
        log "Instalando APK en el dispositivo..."
        adb install -r "$APK_PATH"
        ok "APK instalado."
    fi
fi

# ─── Seguir logs ──────────────────────────────────────────────────────────────
if [[ $DO_LOGS -eq 1 ]]; then
    if ! command -v adb &>/dev/null; then
        warn "adb no instalado, no puedo mostrar logs."
    else
        log "Siguiendo logs del dispositivo (Ctrl+C para salir)..."
        adb logcat -s python:V SDL:V pygame:V
    fi
fi
