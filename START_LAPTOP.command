#!/bin/bash
# Hardware-day start for the LAPTOP: backend + device gateway + CV pipeline in one go.
#   double-click in Finder, or:   bash START_LAPTOP.command
# Stops cleanly with Ctrl-C. Needs SETUP_MAC.command to have run once (creates .venv and .env).
#
# What it does:
#   1. prints the laptop's LAN IP (put it in the Pi's pi_agent.yaml laptop_url)
#   2. starts the FastAPI backend on :8000 (SQLite) in the background and waits for /health
#   3. starts the pipeline on the Pi stream: device gateway ws://0.0.0.0:8765, results saved to runs/,
#      predictions/events/regions persisted through the backend
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
[ -x .venv/bin/python ] || { echo "no .venv – run SETUP_MAC.command first"; exit 1; }
[ -f .env ] || { echo "no .env – run SETUP_MAC.command first"; exit 1; }
set -a; . ./.env; set +a

TIMEOUT="${CONVERGENT_FRAME_TIMEOUT:-900}"   # seconds to wait for the first/next Pi frame before the session ends
LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')
echo "================================================================"
echo " Laptop LAN IP: ${LAN_IP:-unknown}   ->  Pi pi_agent.yaml: laptop_url: ws://${LAN_IP:-LAPTOP_IP}:8765"
echo " Device token : CONVERGENT_DEVICE_TOKEN from .env (the Pi needs the same value)"
echo "================================================================"

mkdir -p logs
.venv/bin/python -m convergent.cli backend > logs/backend.out 2>&1 &
BACKEND_PID=$!
trap 'echo; echo "stopping backend ($BACKEND_PID)"; kill $BACKEND_PID 2>/dev/null; wait $BACKEND_PID 2>/dev/null' EXIT INT TERM
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${CONVERGENT_API_PORT:-8000}/health" >/dev/null 2>&1; then echo "backend up (http://127.0.0.1:${CONVERGENT_API_PORT:-8000}/docs)"; break; fi
  sleep 0.5
  [ "$i" = 60 ] && { echo "backend did not come up – see logs/backend.out"; exit 1; }
done

echo "pipeline: waiting for the Pi on ws://0.0.0.0:8765 (timeout ${TIMEOUT}s per frame; Ctrl-C to stop)"
.venv/bin/python -m convergent.cli network --host 0.0.0.0 --port 8765 --timeout "$TIMEOUT" --backend http --save-results "$@"
