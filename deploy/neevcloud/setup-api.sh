#!/usr/bin/env bash
# Bootstrap AegisAgent API on a fresh Ubuntu 24.04 NeevCloud CPU VM.
# Run as root from repo root: sudo bash deploy/neevcloud/setup-api.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/aegis-agent}"
APP_USER="${APP_USER:-aegis}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/neevcloud/setup-api.sh"
  exit 1
fi

echo "==> Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  python3 \
  python3-pip \
  python3-venv \
  python3-dev \
  build-essential \
  curl \
  git

echo "==> Creating user ${APP_USER}"
if ! id "$APP_USER" &>/dev/null; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

echo "==> Ensuring app directory ${APP_DIR}"
if [[ ! -d "$APP_DIR/.git" ]]; then
  if [[ "$REPO_ROOT" == "$APP_DIR" ]] || [[ -f "$REPO_ROOT/backend/main.py" ]]; then
    mkdir -p "$(dirname "$APP_DIR")"
    if [[ "$REPO_ROOT" != "$APP_DIR" ]]; then
      cp -a "$REPO_ROOT" "$APP_DIR"
    fi
  else
    echo "Clone the repo to ${APP_DIR} first, then re-run this script."
    exit 1
  fi
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "==> Creating Python virtualenv"
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip wheel
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> Chroma data directory"
mkdir -p "$APP_DIR/backend/rag/.chroma"
chown -R "$APP_USER:$APP_USER" "$APP_DIR/backend/rag"

echo "==> Production .env"
if [[ ! -f "$APP_DIR/.env" ]]; then
  cp "$APP_DIR/deploy/neevcloud/env.production.example" "$APP_DIR/.env"
  chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
  echo "Created ${APP_DIR}/.env — edit GOOGLE_API_KEY and CORS_ORIGINS before starting."
else
  echo "Keeping existing ${APP_DIR}/.env"
fi

echo "==> Installing systemd unit"
cp "$APP_DIR/deploy/neevcloud/aegis-api.service" /etc/systemd/system/aegis-api.service
systemctl daemon-reload

echo ""
echo "Setup complete."
echo ""
echo "Next steps:"
echo "  1. sudo nano ${APP_DIR}/.env"
echo "  2. sudo systemctl enable --now aegis-api"
echo "  3. curl -s http://127.0.0.1:8080/health"
echo "  4. Configure Cloudflare Tunnel — see deploy/neevcloud/README.md"
echo ""
