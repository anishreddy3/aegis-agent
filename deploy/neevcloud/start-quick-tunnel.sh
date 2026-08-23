#!/usr/bin/env bash
# Ephemeral Cloudflare Quick Tunnel — no custom domain required.
# Gives a public HTTPS URL like https://xxxx.trycloudflare.com → localhost:8080
#
# Usage (on NeevCloud VM, as root):
#   bash deploy/neevcloud/start-quick-tunnel.sh
#   bash deploy/neevcloud/start-quick-tunnel.sh --install-service
#
# URL is written to /var/log/aegis-tunnel.url (updates each restart).
set -euo pipefail

ORIGIN="${ORIGIN:-http://127.0.0.1:8080}"
URL_FILE="${URL_FILE:-/var/log/aegis-tunnel.url}"
LOG_FILE="${LOG_FILE:-/var/log/cloudflared-quick.log}"
INSTALL_SERVICE=false

for arg in "$@"; do
  case "$arg" in
    --install-service) INSTALL_SERVICE=true ;;
  esac
done

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "Installing cloudflared…"
  ARCH="$(uname -m)"
  case "$ARCH" in
    x86_64) DEB=cloudflared-linux-amd64.deb ;;
    aarch64|arm64) DEB=cloudflared-linux-arm64.deb ;;
    *) echo "Unsupported arch: $ARCH"; exit 1 ;;
  esac
  curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/${DEB}" -o "/tmp/${DEB}"
  dpkg -i "/tmp/${DEB}"
fi

if [[ "$INSTALL_SERVICE" == true ]]; then
  SCRIPT_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/start-quick-tunnel.sh"
  cat >/etc/systemd/system/cloudflared-quick.service <<EOF
[Unit]
Description=Cloudflare Quick Tunnel (AegisAgent API, no domain)
After=network-online.target aegis-api.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=${SCRIPT_PATH}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now cloudflared-quick
  echo "Service installed. Wait ~10s, then: cat ${URL_FILE}"
  exit 0
fi

: >"$LOG_FILE"
echo "Starting quick tunnel → ${ORIGIN}"
echo "Logging to ${LOG_FILE}"

# cloudflared prints the public URL to stderr
cloudflared tunnel --url "$ORIGIN" 2>&1 | tee -a "$LOG_FILE" | while IFS= read -r line; do
  echo "$line"
  if [[ "$line" =~ https://[a-z0-9-]+\.trycloudflare\.com ]]; then
    url="${BASH_REMATCH[0]}"
    echo "$url" >"$URL_FILE"
    echo ""
    echo "════════════════════════════════════════════════════════"
    echo " Public API URL (paste into Cloudflare Pages UI):"
    echo " ${url}"
    echo " Saved to: ${URL_FILE}"
    echo "════════════════════════════════════════════════════════"
    echo ""
  fi
done
