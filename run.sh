#!/usr/bin/env bash
# Linux/macOS: keep the bot running, restarting 10s after any exit.
set -u
cd "$(dirname "$0")"
[ -f .env ] || { echo "Copy .env.example to .env first"; exit 1; }
[ -x .venv/bin/python ] || { python3 -m venv .venv && .venv/bin/pip install -r requirements.txt; }
while true; do
  .venv/bin/python -m bot.main
  code=$?
  [ "$code" -eq 2 ] && { echo "Config problem, see data/bot.log"; exit 2; }
  echo "bot exited ($code), restarting in 10s"; sleep 10
done
