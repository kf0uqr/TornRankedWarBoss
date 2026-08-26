#!/usr/bin/env bash
cd "$(dirname "$0")"
exec env -u PYTHONPATH .venv/bin/python bot/discord_bot.py
