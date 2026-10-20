#!/usr/bin/env bash
#
# CryzonCloud Cpanel — node agent installer
# ------------------------------------------------------------
# Turns a host into a CryzonCloud "node" that the main panel
# can route container operations to. Installs LXD + the node
# agent (node.py) as a systemd service.
#
# Usage:
#   sudo ./setup_node.sh --key <API_KEY> [--port 7000]
#
set -euo pipefail

B="\033[1;36m"; G="\033[1;32m"; Y="\033[1;33m"; R="\033[1;31m"; N="\033[0m"
say()  { echo -e "${B}▸${N} $*"; }
ok()   { echo -e "${G}✔${N} $*"; }
warn() { echo -e "${Y}!${N} $*"; }
die()  { echo -e "${R}’${N} $*" >&2; exit 1; }

API_KEY=""
NODE_PORT="${CRYZON_NODE_PORT:-7000}"
NODE_USER="${CRYZON_USER:-cryzon}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --key)  API_KEY="$2"; shift 2 ;;
    --port) NODE_PORT="$2"; shift 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^#//'; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo
echo -e "${B}  CryzonCloud — node agent installer${N}"
echo    "  -----------------------------------"
echo    "  app dir : $APP_DIR"
echo    "  port    : $NODE_PORT"
echo

[[ $EUID -eq 0 ]] || die "Please run as root (sudo ./setup_node.sh --key <API_KEY>)"
[[ -n "$API_KEY" ]] || die "Missing --key <API_KEY> (generate one in the panel: Admin → Nodes)."

# ------------------------------------------------------------------ 1. base
say "Installing base packages…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip python3-dev build-essential snapd >/dev/null
ok "Base packages installed."

# ------------------------------------------------------------------ 2. LXD
if ! command -v lxc >/dev/null 2>&1; then
  say "Installing LXD via snap…"
  systemctl enable --now snapd.socket >/dev/null 2>&1 || true
  snap install lxd
fi
say "Initialising LXD…"
lxc storage list >/dev/null 2>&1 || lxd init --auto --storage-backend=dir || true
ok "LXD ready."

# ------------------------------------------------------------------ 3. user
if ! id "$NODE_USER" >/dev/null 2>&1; then
  say "Creating service user '$NODE_USER'…"
  useradd --system --create-home --shell /usr/sbin/nologin "$NODE_USER"
fi
usermod -aG lxd "$NODE_USER" || true
ok "Service user ready."

# ------------------------------------------------------------------ 4. venv
say "Installing node dependencies…"
python3 -m venv "$APP_DIR/venv-node"
"$APP_DIR/venv-node/bin/pip" install --upgrade pip -q
"$APP_DIR/venv-node/bin/pip" install -r "$APP_DIR/node_requirements.txt" -q
ok "Node dependencies installed."

chown -R "$NODE_USER:$NODE_USER" "$APP_DIR"

# ------------------------------------------------------------------ 5. systemd
say "Installing systemd service…"
cat >/etc/systemd/system/cryzoncloud-node.service <<EOF
[Unit]
Description=CryzonCloud Node Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$NODE_USER
Group=$NODE_USER
WorkingDirectory=$APP_DIR
Environment=CRYZON_NODE_PORT=$NODE_PORT
Environment=CRYZON_NODE_KEY=$API_KEY
ExecStart=$APP_DIR/venv-node/bin/gunicorn -w 2 --threads 4 -b 0.0.0.0:$NODE_PORT 'node:app'
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable cryzoncloud-node.service >/dev/null 2>&1 || true
systemctl restart cryzoncloud-node.service
ok "Node agent started."

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
ok "Node agent ready!"
echo    "  ────────────────────────────────"
echo    "  Register this node in the panel with:"
echo    "    Name    : <anything>"
echo    "    Address : http://${IP:-<node-ip>}:$NODE_PORT"
echo    "    API key : $API_KEY"
echo
