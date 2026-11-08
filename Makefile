# Convergent handwashing system – developer commands (laptop). Every target is a real command.
UV ?= uv
PY := .venv/bin/python

.PHONY: help install install-legacy install-pi models yolov5 samples backend replay camera network pi-emulator calibrate evaluate train-lstm start test test-fast lint status db-up

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

install: ## create .venv from uv.lock (laptop: inference + backend + yolo + dev)
	$(UV) sync --extra backend --extra yolo --extra dev
	$(UV) pip install --python $(PY) --reinstall --no-deps "opencv-contrib-python==4.11.0.86"   # repairs cv2 if a headless wheel was ever installed
	@test -f .env || cp .env.example .env
	@echo "edit .env: set CONVERGENT_API_TOKEN and CONVERGENT_DEVICE_TOKEN"

install-legacy: ## add the optional TensorFlow extra for the S-Kia legacy checkpoint
	$(UV) sync --extra backend --extra yolo --extra dev --extra skia-legacy

install-pi: ## on the Raspberry Pi: minimal agent dependencies (see docs/PI_SETUP.md)
	python3 -m venv --system-site-packages .venv-pi && .venv-pi/bin/pip install -e ".[pi]" --no-deps && .venv-pi/bin/pip install "websockets>=13.1,<15" "pillow>=10.4,<12" "psutil>=6" "pyyaml>=6"

models: ## fetch/derive upstream model artifacts into models/ (hash-checked)
	$(PY) scripts/fetch_models.py $(if $(UPSTREAM),--from-local $(UPSTREAM),)

yolov5: ## clone the pinned YOLOv5 checkout into third_party/
	bash scripts/fetch_yolov5.sh

samples: ## copy the sample handwashing video from a local clone of the YOLO repo (UPSTREAM=dir)
	mkdir -p data/samples && cp $(UPSTREAM)/hand-wash-compliance-yolo/HandWashDataset_yoloFormat/TestingData/missingStep_test1.mp4 data/samples/handwashing_missing_step.mp4

backend: ## start the FastAPI backend (applies migrations)
	$(PY) -m convergent.cli backend

db-up: ## start PostgreSQL via docker compose
	docker compose up -d db

replay: ## run the pipeline on the sample video and save results (VIDEO=path BACKEND=none|inprocess|http)
	$(PY) -m convergent.cli replay --video $(or $(VIDEO),data/samples/handwashing_missing_step.mp4) --save-results --backend $(or $(BACKEND),none)

camera: ## run the pipeline on the local webcam with the diagnostic overlay
	$(PY) -m convergent.cli camera --show

network: ## run the pipeline on the Pi stream (device gateway on :8765)
	$(PY) -m convergent.cli network --save-results

pi-emulator: ## run a simulated Pi agent against the local gateway
	$(PY) -m convergent.cli pi-emulator --max-frames 150

calibrate: ## synthetic projector calibration self-test
	$(PY) -m convergent.cli calibrate synthetic

evaluate: ## evaluate on the sample recording with branch ablations
	$(PY) scripts/evaluate_models.py --video data/samples/handwashing_missing_step.mp4 --reference data/fixtures/handwashing_missing_step.reference.json --ablation --out runs/evaluation.json

train-lstm: ## extract landmarks from DATA (Step_* folders) and run the temporal-model sweep (installs the winner)
	$(PY) scripts/extract_landmark_sequences.py --root $(or $(DATA),data/HandWashDataset) --out data/landmark_sequences
	$(PY) scripts/sweep_lstm.py --data data/landmark_sequences --out runs/lstm_sweep --epochs 80

start: ## hardware day: backend + device gateway + pipeline (same as START_LAPTOP.command)
	bash START_LAPTOP.command

test: ## run the whole test-suite
	$(PY) -m pytest -q

test-fast: ## unit tests only (no MediaPipe model runs)
	$(PY) -m pytest -q tests/unit -m "not mediapipe"

lint: ## ruff
	$(PY) -m ruff check src tests scripts

status: ## artifact discovery + adapter availability
	$(PY) -m convergent.cli models
