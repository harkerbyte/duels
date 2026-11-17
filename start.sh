#!/usr/bin/env bash
# Heaven Duels launcher: creates a virtualenv, installs deps, starts the server
# and opens your browser on the game.
#   ./start.sh            use shadeDB if .env has credentials, else local storage
#   ./start.sh --offline  force local storage (no network needed)
#   ./start.sh --lan      also let other devices on your network join
set -e
cd "$(dirname "$0")"

LAN=0
for arg in "$@"; do
  case "$arg" in
    --offline) export HD_MODE=offline ;;
    --lan) export HOST=0.0.0.0; LAN=1 ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

if [ ! -f .env ]; then
  cp sec/.env.example .env
  echo "No .env found, created one from sec/.env.example."
fi
PORT="${PORT:-$(grep -E '^PORT=' .env | cut -d= -f2)}"; PORT="${PORT:-5000}"; export PORT
URL="http://localhost:$PORT"

[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
pip install -q -r requirements.txt

open_browser() {
  sleep 1.5
  if command -v xdg-open >/dev/null; then xdg-open "$URL"
  elif command -v open >/dev/null; then open "$URL"
  elif command -v wslview >/dev/null; then wslview "$URL"
  elif command -v cmd.exe >/dev/null; then cmd.exe /c start "$URL"
  else echo "Open $URL in your browser."; fi
}
open_browser >/dev/null 2>&1 &

echo "Heaven Duels running at $URL (Ctrl+C to stop)"
if [ "$LAN" = 1 ]; then
  IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  [ -n "$IP" ] && echo "Friends on your network: http://$IP:$PORT"
fi
exec python app.py
