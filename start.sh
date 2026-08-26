#!/usr/bin/env bash
cd "$(dirname "$0")"
bash scripts/self_update.sh

# Restart, not just start - if an old instance is already listening on
# 8787, stop it first so an update actually takes effect instead of the
# new code sitting there unused behind the still-running old process.
if command -v lsof >/dev/null 2>&1; then
    EXISTING_PID=$(lsof -ti:8787 2>/dev/null)
    if [ -n "$EXISTING_PID" ]; then
        echo "start.sh: stopping existing app instance (PID $EXISTING_PID)..."
        kill "$EXISTING_PID"
        sleep 1
    fi
fi

exec env -u PYTHONPATH .venv/bin/python app.py
