#!/usr/bin/env bash
#
# CryzonCloud Cpanel — control-panel installer
# ------------------------------------------------------------
# Installs the panel on a fresh Debian/Ubuntu host together with
# LXD (snap) so containers can be provisioned with dedicated
# RAM, disk (ROM) and CPU cores.
#
# Usage:
#   sudo ./setup.sh            # full install (LXD + panel + systemd)
#   sudo ./setup.sh --demo     # panel only, demo mode (no LXD)
#   sudo ./setup.sh --no-systemd
#
set -euo pipefail

# ------------------------------------------------------------------ colors
B="\033[1;36m"; G="\033[1;32m"; Y="\033[1;33m"; R="\033[1;31m"; N="\033[0m"
say()  { echo -e "${B}▸${N} $*"; }
ok()   { echo -e "${G}✔${N} $*"; }
warn() { echo -e "${Y}!${N} $*"; }
die()  { echo -e "${R}’${N} $*" >&2; exit 1; }

DEMO=0
SYSTEMD=1
for arg in "$@"; do
  case "$arg" in
    --demo)       DEMO=1 ;;
    --no-systemd) SYSTEMD=0 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^#//'; exit 0 ;;
    *) die "Unknown option: $arg" ;;
  esac
done

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PANEL_USER="${CRYZON_USER:-cryzon}"
PANEL_PORT="${CRYZON_PORT:-8080}"

echo
echo -e "${B}  CryzonCloud Cpanel — installer${N}"
echo    "  --------------------------------"
echo    "  app dir : $APP_DIR"
echo    "  port    : $PANEL_PORT"
echo    "  mode    : $([ $DEMO -eq 1 ] && echo 'demo (no LXD)' || echo 'live (LXD)')"
echo

[[ $EUID -eq 0 ]] || die "Please run as root (sudo ./setup.sh)"

# ------------------------------------------------------------------ 1. base packages
say "Installing base packages…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  python3 python3-venv python3-pip python3-dev \
  build-essential git curl ca-certificates \
  sqlite3 tzdata >/dev/null
ok "Base packages installed."

# ------------------------------------------------------------------ 2. LXD
if [[ $DEMO -eq 0 ]]; then
  if ! command -v lxc >/dev/null 2>&1; then
    say "Installing LXD via snap…"
    if ! command -v snap >/dev/null 2>&1; then
      apt-get install -y -qq snapd >/dev/null
      systemctl enable --now snapd.socket >/dev/null 2>&1 || true
    fi
    snap install lxd
  else
    ok "LXD already present."
  fi

  say "Initialising LXD (if needed)…"
  if ! lxc storage list >/dev/null 2>&1; then
    lxd init --auto --storage-backend=dir || true
  fi
  # allow the panel user to talk to LXD
  if id "$PANEL_USER" >/dev/null 2>&1; then
    usermod -aG lxd "$PANEL_USER" || true
  fi
  ok "LXD ready."
else
  warn "Demo mode — skipping LXD installation."
fi

# ------------------------------------------------------------------ 3. service user
if ! id "$PANEL_USER" >/dev/null 2>&1; then
  say "Creating service user '$PANEL_USER'…"
  useradd --system --create-home --shell /usr/sbin/nologin "$PANEL_USER"
fi
ok "Service user ready."

# ------------------------------------------------------------------ 4. python venv
say "Creating virtualenv + installing requirements…"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip -q
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q
ok "Python dependencies installed."

# ------------------------------------------------------------------ 5. dirs + perms
say "Preparing data directory…"
mkdir -p "$APP_DIR/data"
chown -R "$PANEL_USER:$PANEL_USER" "$APP_DIR"
chmod +x "$APP_DIR/app.py" "$APP_DIR/node.py" 2>/dev/null || true
ok "Permissions set."

# ------------------------------------------------------------------ 6. systemd unit
if [[ $SYSTEMD -eq 1 ]]; then
  say "Installing systemd service…"
  cat >/etc/systemd/system/cryzoncloud.service <<EOF
[Unit]
Description=CryzonCloud Cpanel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$PANEL_USER
Group=$PANEL_USER
WorkingDirectory=$APP_DIR
Environment=CRYZON_HOST=0.0.0.0
Environment=CRYZON_PORT=$PANEL_PORT
Environment=CRYZON_DEMO=$DEMO
ExecStart=$APP_DIR/venv/bin/gunicorn -w 4 --threads 8 -b 0.0.0.0:$PANEL_PORT 'app:app'
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable cryzoncloud.service >/dev/null 2>&1 || true
  systemctl restart cryzoncloud.service
  ok "Service 'cryzoncloud' started."
fi

# ------------------------------------------------------------------ done
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
ok "Installation complete!"
echo    "  ────────────────────────────────"
echo    "  Panel URL : http://${IP:-<server-ip>}:$PANEL_PORT"
echo    "  Login     : admin / admin123"
echo    "  Mode      : $([ $DEMO -eq 1 ] && echo 'DEMO' || echo 'LIVE (LXD)')"
[[ $SYSTEMD -eq 1 ]] && echo "  Service   : systemctl status cryzoncloud"
echo
warn "Change the default admin password after first login!"
echo
