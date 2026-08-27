#!/usr/bin/env bash
cd "$(dirname "$0")"

# Restart, not just start - if an old tunnel instance is already running,
# stop it first so this one actually takes over.
if command -v pgrep >/dev/null 2>&1; then
    EXISTING_PID=$(pgrep -f "cloudflared tunnel run torn-war-boss" 2>/dev/null)
    if [ -n "$EXISTING_PID" ]; then
        echo "start-tunnel.sh: stopping existing tunnel instance (PID $EXISTING_PID)..."
        kill $EXISTING_PID
        sleep 1
    fi
fi

exec cloudflared tunnel run torn-war-boss
