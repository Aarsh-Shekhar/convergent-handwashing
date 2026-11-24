#!/bin/bash
# Scrubble demo: double-click (Mac) or run `bash START_SCRUBBLE_DEMO.command`.
# Builds the app, starts a DEMO backend with a made-up family (Sam, Mia, Leo) and opens it in the browser.
# It uses its own database file (scrubble_demo.db) and never touches real wash data. Ctrl+C stops it.
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"   # Finder starts scripts with a short PATH
PORT="${SCRUBBLE_PORT:-8010}"
URL="http://127.0.0.1:$PORT"

command -v npm >/dev/null || { echo "Node.js is missing. Install it from https://nodejs.org (LTS), then run this again."; exit 1; }
if [ ! -x .venv/bin/python ]; then
  command -v uv >/dev/null || { echo "The Python environment is missing. Run SETUP_MAC.command (or 'make install') first."; exit 1; }
  echo "Creating the Python environment (first run only, a few minutes)..."
  uv sync --extra backend --extra dev
fi

echo "Building the app..."
# install again when the package list changed (for example after a git pull)
(cd web && { [ -d node_modules ] && [ ! package-lock.json -nt node_modules/.package-lock.json ] || npm ci --silent; } && npm run build --silent)

# a token just for this demo run (the seed script and the backend must share it)
export CONVERGENT_API_TOKEN="${CONVERGENT_API_TOKEN:-demo-$(.venv/bin/python -c 'import secrets;print(secrets.token_urlsafe(24))')}"
export CONVERGENT_DEMO_MODE=true CONVERGENT_DATABASE_URL="sqlite:///./scrubble_demo.db" CONVERGENT_API_PORT="$PORT"

.venv/bin/python -m convergent.cli backend --port "$PORT" &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT
for _ in $(seq 1 80); do curl -sf "$URL/health" >/dev/null 2>&1 && break; sleep 0.25; done
curl -sf "$URL/health" >/dev/null || { echo "The backend did not start. Is port $PORT in use? Try: SCRUBBLE_PORT=8011 bash START_SCRUBBLE_DEMO.command"; exit 1; }

.venv/bin/python scripts/seed_demo_family.py --url "$URL" --reset

cat <<MSG

  Scrubble demo is running.

  Grown-up view (numbers):     $URL/
  Kid view (game):             $URL/kid
  How sync works, live:        $URL/station
  First-run tour:              $URL/onboarding
  Switch Kid / Grown-up and Phone / Desktop with the two switches in the app's side bar.

  Developer side:
    API docs you can click:    $URL/docs
    What the app reads:        $URL/api/v1/app/home
    Send a simulated wash (new Terminal tab, watch the open app update on its own):
      CONVERGENT_API_TOKEN=$CONVERGENT_API_TOKEN .venv/bin/python scripts/send_test_wash.py --url $URL --miss thumbs
    Look at the database:      sqlite3 scrubble_demo.db "select wash_id, source, points, reward_points from washes order by ended_utc desc limit 5"
    Run the tests:             .venv/bin/python -m pytest -q tests/integration/test_family_app.py tests/integration/test_wash_outbox.py
                               (cd web && npm run test:e2e)

  Everything here is made-up demo data. Press Ctrl+C to stop.
MSG
command -v open >/dev/null && open "$URL/" || true
wait $SERVER
