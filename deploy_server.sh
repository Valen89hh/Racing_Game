#!/usr/bin/env bash
# =============================================================================
# deploy_server.sh — Deploy dedicated racing server via git sparse checkout
#
# Usage (from Git Bash on Windows):
#   bash deploy_server.sh --setup           # Initial droplet setup (once)
#   bash deploy_server.sh --install-service  # Install systemd service (once)
#   bash deploy_server.sh                    # Push + pull + restart (daily)
#
# Prerequisites:
#   - SSH key configured for the droplet
#   - Git remote 'origin' pointing to the GitHub repo
# =============================================================================

set -euo pipefail

# ─── Configuration ───────────────────────────────────────────────────────────
SERVER_IP="${RACING_SERVER_IP:-143.198.138.38}"
SERVER_USER="${RACING_SERVER_USER:-racing}"
SSH_KEY="${RACING_SSH_KEY:-}"  # e.g. ~/.ssh/id_rsa (empty = default key)
REMOTE_DIR="/home/${SERVER_USER}/racing_server"
REPO_URL="${RACING_REPO_URL:-$(git remote get-url origin 2>/dev/null || echo 'https://github.com/Valen89hh/Racing_Game.git')}"
TRACK_FILE="${RACING_TRACK_FILE:-leve_4.json}"
BOT_COUNT="${RACING_BOT_COUNT:-1}"
GAME_PORT="${RACING_GAME_PORT:-5555}"
BRANCH="${RACING_BRANCH:-main}"
# ─────────────────────────────────────────────────────────────────────────────

# SSH command builder
_ssh() {
    local ssh_opts=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)
    if [[ -n "$SSH_KEY" ]]; then
        ssh_opts+=(-i "$SSH_KEY")
    fi
    ssh "${ssh_opts[@]}" "${SERVER_USER}@${SERVER_IP}" "$@"
}

# Color helpers
_info()  { echo -e "\033[1;34m[INFO]\033[0m  $*"; }
_ok()    { echo -e "\033[1;32m[OK]\033[0m    $*"; }
_warn()  { echo -e "\033[1;33m[WARN]\033[0m  $*"; }
_error() { echo -e "\033[1;31m[ERROR]\033[0m $*"; }

# ─── Sparse checkout file list ───────────────────────────────────────────────
# These are the only paths materialized on the server (~28 Python files + data)
SPARSE_PATHS=(
    "main.py"
    "settings.py"
    "track_manager.py"
    "race_progress.py"
    "tile_track.py"
    "tile_defs.py"
    "tile_meta.py"
    "tile_collision.py"
    "server/"
    "networking/__init__.py"
    "networking/server.py"
    "networking/protocol.py"
    "networking/net_state.py"
    "entities/__init__.py"
    "entities/car.py"
    "entities/track.py"
    "entities/powerup.py"
    "systems/__init__.py"
    "systems/physics.py"
    "systems/collision.py"
    "systems/ai.py"
    "utils/__init__.py"
    "utils/base_path.py"
    "utils/helpers.py"
    "utils/timer.py"
    "utils/sprites.py"
    "tracks/"
    "assets/levels/tileset_meta.json"
)

# =============================================================================
# --setup: Initial droplet provisioning
# =============================================================================
do_setup() {
    _info "Setting up dedicated server on ${SERVER_USER}@${SERVER_IP}..."

    # 1. Install system dependencies
    _info "Installing system packages..."
    _ssh "sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-pip python3-venv git libsdl2-2.0-0 libsdl2-mixer-2.0-0 libsdl2-image-2.0-0 libsdl2-ttf-2.0-0"
    _ok "System packages installed"

    # 2. Clone repo with sparse checkout (partial clone to save bandwidth)
    _info "Cloning repo with sparse checkout..."
    local sparse_list=""
    for p in "${SPARSE_PATHS[@]}"; do
        sparse_list+="\"$p\" "
    done

    _ssh "bash -s" <<EOF
set -euo pipefail

if [ -d "${REMOTE_DIR}/.git" ]; then
    echo "Repository already exists at ${REMOTE_DIR}, updating sparse checkout..."
    cd "${REMOTE_DIR}"
    git sparse-checkout set --no-cone ${sparse_list}
    git pull origin ${BRANCH}
else
    git clone --no-checkout --filter=blob:none "${REPO_URL}" "${REMOTE_DIR}"
    cd "${REMOTE_DIR}"
    git sparse-checkout init
    git sparse-checkout set --no-cone ${sparse_list}
    git checkout ${BRANCH}
fi
EOF
    _ok "Repo cloned with sparse checkout"

    # 3. Create virtual environment and install deps
    _info "Setting up Python virtual environment..."
    _ssh "cd ${REMOTE_DIR} && python3 -m venv venv && ./venv/bin/pip install --upgrade pip -q && ./venv/bin/pip install -r server/requirements-server.txt -q"
    _ok "Virtual environment ready"

    # 4. Verify
    _info "Verifying setup..."
    local file_count
    file_count=$(_ssh "find ${REMOTE_DIR} -name '*.py' -not -path '*/venv/*' -not -path '*/__pycache__/*' | wc -l")
    _ok "Setup complete! ${file_count} Python files on server"

    # Check that game.py and editor.py are NOT present (sparse checkout working)
    if _ssh "test -f ${REMOTE_DIR}/game.py" 2>/dev/null; then
        _warn "game.py found on server — sparse checkout may not be filtering correctly"
    else
        _ok "Verified: game.py not present (sparse checkout working)"
    fi

    echo ""
    _info "Next steps:"
    echo "  1. bash deploy_server.sh --install-service"
    echo "  2. bash deploy_server.sh  (to deploy)"
}

# =============================================================================
# --install-service: Install systemd unit
# =============================================================================
do_install_service() {
    _info "Installing systemd service on ${SERVER_USER}@${SERVER_IP}..."

    local service_content="[Unit]
Description=Racing Dedicated Server
After=network.target

[Service]
Type=simple
User=${SERVER_USER}
WorkingDirectory=${REMOTE_DIR}
Environment=SDL_VIDEODRIVER=dummy
Environment=PYTHONUNBUFFERED=1
ExecStart=${REMOTE_DIR}/venv/bin/python main.py --dedicated-server --track ${TRACK_FILE} --bots ${BOT_COUNT} --port ${GAME_PORT} --multi-room
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=racing-server

[Install]
WantedBy=multi-user.target"

    _ssh "sudo bash -s" <<EOF
echo '${service_content}' > /etc/systemd/system/racing-server.service
systemctl daemon-reload
systemctl enable racing-server
systemctl start racing-server
EOF

    _ok "Service installed and started"
    _info "Check status: ssh ${SERVER_USER}@${SERVER_IP} 'systemctl status racing-server'"
    _info "View logs:    ssh ${SERVER_USER}@${SERVER_IP} 'journalctl -u racing-server -f'"
}

# =============================================================================
# Default: Deploy (push + pull + restart)
# =============================================================================
do_deploy() {
    _info "Deploying to ${SERVER_USER}@${SERVER_IP}..."

    # 1. Push local changes
    _info "Pushing to origin/${BRANCH}..."
    git push origin "${BRANCH}"
    _ok "Pushed"

    # 2. Pull on server
    _info "Pulling on server..."
    _ssh "cd ${REMOTE_DIR} && git pull origin ${BRANCH}"
    _ok "Pulled"

    # 3. Restart service
    _info "Restarting service..."
    _ssh "sudo systemctl restart racing-server"
    _ok "Service restarted"

    # 4. Quick health check (wait 2s, then check if running)
    sleep 2
    local status
    status=$(_ssh "systemctl is-active racing-server" 2>/dev/null || true)
    if [[ "$status" == "active" ]]; then
        _ok "Deploy complete! Server is running"
    else
        _error "Service is not active (status: ${status})"
        _info "Check logs: ssh ${SERVER_USER}@${SERVER_IP} 'journalctl -u racing-server -n 20'"
        exit 1
    fi
}

# =============================================================================
# Argument parsing
# =============================================================================

# Validate configuration
if [[ "$SERVER_IP" == "YOUR_DROPLET_IP" ]]; then
    _error "Server IP not configured!"
    echo ""
    echo "Set the IP via environment variable or edit this script:"
    echo "  export RACING_SERVER_IP=your.server.ip"
    echo ""
    echo "All configurable variables:"
    echo "  RACING_SERVER_IP     — Droplet IP address"
    echo "  RACING_SERVER_USER   — SSH user (default: racing)"
    echo "  RACING_SSH_KEY       — Path to SSH key (default: system default)"
    echo "  RACING_REPO_URL      — Git repo URL (default: from 'origin' remote)"
    echo "  RACING_TRACK_FILE    — Track JSON path (default: tracks/leve_4.json)"
    echo "  RACING_BOT_COUNT     — Number of bots (default: 1)"
    echo "  RACING_GAME_PORT     — UDP port (default: 5555)"
    echo "  RACING_BRANCH        — Git branch (default: main)"
    exit 1
fi

case "${1:-}" in
    --setup)
        do_setup
        ;;
    --install-service)
        do_install_service
        ;;
    --help|-h)
        echo "Usage: bash deploy_server.sh [OPTION]"
        echo ""
        echo "Options:"
        echo "  --setup             Initial droplet setup (clone repo, install deps)"
        echo "  --install-service   Install and start systemd service"
        echo "  (no option)         Deploy: push + pull + restart"
        echo "  --help              Show this help"
        echo ""
        echo "Configure via environment variables (see --help output above)"
        ;;
    "")
        do_deploy
        ;;
    *)
        _error "Unknown option: $1"
        echo "Use --help for usage"
        exit 1
        ;;
esac
