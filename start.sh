#!/usr/bin/env bash
# Heaven Duels launcher: sets up a virtualenv, installs deps, starts the server and
# opens your browser on the game.
#   ./start.sh              play on the shared demo database (creates .env for you)
#   ./start.sh --custom     use your OWN .env (your own shadeDB; this script never touches it)
#   ./start.sh --offline    local storage only, no network or database needed
#   ./start.sh --lan        also let other devices on your network join
#   ./start.sh --demo       replace .env with the demo one (your old one is kept as .env.bak)
#   ./start.sh --write-env  just write the demo .env and stop (handy for Docker)
set -e
cd "$(dirname "$0")"

# ---------------------------------------------------------------------------
# Shared demo database. The first run writes these into .env so the game works
# straight after cloning. They are public on purpose: anyone who has this file can
# use (and abuse) this database, so nothing private belongs in it. To use your own
# database run ./start.sh --custom with your own .env. To publish your own demo,
# replace the values below with a dedicated, disposable token.
# ---------------------------------------------------------------------------
DEMO_ENDPOINT="https://shadedb.duckdns.org/connect/sdb9e2ad3ca192f480186b8a156c9a06"
DEMO_DBID="sdb9e2ad3ca192f480186b8a156c9a06"
DEMO_CONNECTION_TOKEN="0de5a1a4332c8741dfbc0cb8eed1b0ea"
DEMO_CLUSTER_TOKEN="0aef6ebc3a2b500"
DEMO_PARTITION="duelers"
MARK="# created by start.sh: shared demo database"

write_demo_env() {
  cat > .env <<ENV
$MARK
# Safe to delete. To use your own database, put your details in .env (see .env.example)
# and run ./start.sh --custom
SHADEDB_ENDPOINT=$DEMO_ENDPOINT
SHADEDB_DBID=$DEMO_DBID
SHADEDB_CONNECTION_TOKEN=$DEMO_CONNECTION_TOKEN
SHADEDB_CLUSTER_TOKEN=$DEMO_CLUSTER_TOKEN
SHADEDB_PARTITION=$DEMO_PARTITION
PORT=5000
ENV
}
is_demo_env() { [ -f .env ] && grep -q "$MARK" .env; }

LAN=0; CUSTOM=0; DEMO=0; WRITE=0
for arg in "$@"; do
  case "$arg" in
    --custom) CUSTOM=1 ;;
    --demo) DEMO=1 ;;
    --write-env) WRITE=1 ;;
    --offline) export HD_MODE=offline ;;
    --lan) export HOST=0.0.0.0; LAN=1 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)"; exit 1 ;;
  esac
done
if [ "$CUSTOM" = 1 ] && { [ "$DEMO" = 1 ] || [ "$WRITE" = 1 ]; }; then
  echo "--custom uses your own .env, so it cannot be combined with --demo or --write-env."; exit 1
fi

# ---- which database? ----
if [ "$CUSTOM" = 1 ]; then
  if [ ! -f .env ]; then
    echo "--custom uses your own .env, and there isn't one here."
    echo "Copy .env.example to .env, fill in your shadeDB details, then run ./start.sh --custom again."
    exit 1
  fi
  if is_demo_env; then
    echo "The .env here is the demo one that start.sh wrote. Put your own shadeDB details in it"
    echo "(see .env.example), remove the first line, then run ./start.sh --custom again."
    exit 1
  fi
  DB="your own .env"
elif [ "${HD_MODE:-}" = offline ] && [ "$WRITE" = 0 ]; then
  DB="offline, local file"
else
  if [ -f .env ] && ! is_demo_env && [ "$DEMO" = 0 ]; then
    echo "Found a .env that is not the demo one, so I left it alone."
    echo "  ./start.sh --custom   use it (your own database)"
    echo "  ./start.sh --demo     replace it with the demo database (a backup is kept as .env.bak)"
    exit 1
  fi
  if [ ! -f .env ] || [ "$DEMO" = 1 ] || [ "$WRITE" = 1 ]; then
    if [ -f .env ] && ! is_demo_env; then cp .env .env.bak; echo "Your old .env is saved as .env.bak"; fi
    write_demo_env
    echo "Wrote .env for the shared demo database."
  fi
  DB="shared demo database (rooms and chat there are public; use --custom for your own)"
fi
if [ "$WRITE" = 1 ]; then exit 0; fi

PORT="${PORT:-$( (grep -E '^PORT=' .env 2>/dev/null || true) | head -1 | cut -d= -f2)}"; PORT="${PORT:-5000}"; export PORT
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

echo "Database: $DB"
echo "Heaven Duels running at $URL (Ctrl+C to stop)"
if [ "$LAN" = 1 ]; then
  IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  [ -n "$IP" ] && echo "Friends on your network: http://$IP:$PORT"
fi
exec python app.py
