#!/bin/bash
# One-shot setup for the Convergent handwashing project on macOS.
# Run with:   bash ~/Downloads/convergent-handwashing/SETUP_MAC.command
# Everything is logged to setup_log.txt next to this file.

cd "$(dirname "$0")" || exit 1
LOG="$PWD/setup_log.txt"
exec > >(tee "$LOG") 2>&1
set -o pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

step() { printf '\n\n===== %s =====\n' "$1"; }
fail() { printf '\n!!! FAILED at: %s (see %s)\n' "$1" "$LOG"; exit 1; }

step "0. environment"
sw_vers; uname -m; echo "folder: $PWD"

step "1. uv"
if ! command -v uv >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    brew install uv || curl -LsSf https://astral.sh/uv/install.sh | sh || fail "installing uv"
  else
    curl -LsSf https://astral.sh/uv/install.sh | sh || fail "installing uv"
  fi
fi
export PATH="$HOME/.local/bin:$PATH"
uv --version || fail "uv not on PATH"

step "2. python environment (uv sync from uv.lock; downloads Python 3.11 + ~2 GB of packages the first time)"
uv sync --extra backend --extra yolo --extra dev || fail "uv sync"
uv pip install --python .venv/bin/python --reinstall --no-deps "opencv-contrib-python==4.11.0.86" || fail "opencv reinstall"
.venv/bin/python -c "import cv2, mediapipe, torch, fastapi, sqlalchemy; print('cv2', cv2.__version__, 'mediapipe', mediapipe.__version__, 'torch', torch.__version__)" || fail "import check"

step "3. .env with random tokens"
if [ ! -f .env ]; then
  T1=$(.venv/bin/python -c "import secrets;print(secrets.token_urlsafe(32))")
  T2=$(.venv/bin/python -c "import secrets;print(secrets.token_urlsafe(32))")
  sed -e "s#^CONVERGENT_API_TOKEN=.*#CONVERGENT_API_TOKEN=$T1#" -e "s#^CONVERGENT_DEVICE_TOKEN=.*#CONVERGENT_DEVICE_TOKEN=$T2#" .env.example > .env
  echo ".env written"
else
  echo ".env already exists, left untouched"
fi

step "4. model artifacts (MediaPipe bundle download; the rest is already here)"
.venv/bin/python scripts/fetch_models.py --from-local /nonexistent || echo "(some downloads failed - the tracker falls back to the bundled MediaPipe graph; not fatal)"

step "5. tests"
.venv/bin/python -m pytest -q --timeout 300 || fail "tests"

step "6. replay the sample video through the whole pipeline"
.venv/bin/python -m convergent.cli replay --video data/samples/handwashing_missing_step.mp4 --save-results --backend inprocess || fail "replay"

step "DONE"
echo "Setup finished successfully. Log: $LOG"
