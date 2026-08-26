#!/usr/bin/env bash
cd "$(dirname "$0")"
bash scripts/self_update.sh

# Restart, not just start - if an old bot instance is already running,
# stop it first so an update actually takes effect.
if command -v pgrep >/dev/null 2>&1; then
    EXISTING_PID=$(pgrep -f "bot/discord_bot.py" 2>/dev/null)
    if [ -n "$EXISTING_PID" ]; then
        echo "start-bot.sh: stopping existing bot instance (PID $EXISTING_PID)..."
        kill $EXISTING_PID
        sleep 1
    fi
fi

exec env -u PYTHONPATH .venv/bin/python bot/discord_bot.py
