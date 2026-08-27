#!/usr/bin/env bash
# Installs the app, bot, and (if configured) Cloudflare Tunnel as systemd
# services, so they start on boot and restart automatically if they crash.
# Run this from the repo directory on the machine you actually want them
# running on (e.g. the Raspberry Pi), not from a dev machine - the paths and
# user baked into the generated units are wherever this script is run.
set -euo pipefail

if [ "$EUID" -eq 0 ]; then
    echo "Run this as your normal user, not root - it uses sudo itself where needed." >&2
    exit 1
fi

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CURRENT_USER="$(whoami)"

echo "Installing services for:"
echo "  user:        $CURRENT_USER"
echo "  install dir: $INSTALL_DIR"
echo

UNITS=(torn-war-app torn-war-bot)
if [ -f "$HOME/.cloudflared/config.yml" ]; then
    UNITS+=(torn-war-tunnel)
else
    echo "No ~/.cloudflared/config.yml found - skipping the tunnel service."
    echo "(Set up the named tunnel first - see README.md - then re-run this script.)"
    echo
fi

for name in "${UNITS[@]}"; do
    sed -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" -e "s|__USER__|$CURRENT_USER|g" \
        "$INSTALL_DIR/systemd/$name.service.template" \
        | sudo tee "/etc/systemd/system/$name.service" > /dev/null
    echo "Wrote /etc/systemd/system/$name.service"
done

sudo systemctl daemon-reload

for name in "${UNITS[@]}"; do
    sudo systemctl enable --now "$name.service"
done

echo
echo "Done. Check status with:"
for name in "${UNITS[@]}"; do
    echo "  systemctl status $name.service"
done
echo
echo "Logs: journalctl -u torn-war-app -u torn-war-bot -f"
