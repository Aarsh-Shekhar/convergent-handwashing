#!/bin/bash
# One-shot Raspberry Pi setup for the camera agent: Pi Zero 2 W (current plan) or Pi 3 A+ (run ON the Pi, from the repo root):
#
#   bash scripts/pi/install_pi.sh <LAPTOP_IP> <DEVICE_TOKEN>
#
# <LAPTOP_IP>    the laptop's LAN IP printed by START_LAPTOP.command
# <DEVICE_TOKEN> the CONVERGENT_DEVICE_TOKEN value from the laptop's .env
#
# Installs apt packages (picamera2 stack), creates .venv-pi, writes ~/pi_agent.yaml and
# /etc/convergent.env, enables the camera overlay and a systemd service that starts the agent at
# boot. Idempotent: safe to re-run. Log: setup_pi_log.txt in the repo root.
set -o pipefail
cd "$(dirname "$0")/../.." || exit 1
LAPTOP_IP="$1"; TOKEN="$2"
[ -n "$LAPTOP_IP" ] && [ -n "$TOKEN" ] || { echo "usage: bash scripts/pi/install_pi.sh <LAPTOP_IP> <DEVICE_TOKEN>"; exit 2; }
exec > >(tee "$PWD/setup_pi_log.txt") 2>&1
step() { printf '\n===== %s =====\n' "$1"; }
fail() { printf '\n!!! FAILED at: %s (see setup_pi_log.txt)\n' "$1"; exit 1; }

step "0. system"
uname -a; cat /proc/device-tree/model 2>/dev/null; echo; free -m | head -2
if grep -q "Zero 2" /proc/device-tree/model 2>/dev/null; then
  echo "Pi Zero 2 W detected: 512 MB RAM. Adding a 512 MB swap file so pip and the camera stack never OOM; agent defaults (640x480 @ 15 fps, JPEG q70) fit 2.4 GHz Wi-Fi."
  if [ ! -f /swapfile ]; then sudo fallocate -l 512M /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile && echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null; fi
fi

step "1. apt packages (camera stack comes from apt, NOT pip)"
sudo apt-get update && sudo apt-get install -y git python3-venv python3-pip python3-picamera2 python3-libcamera python3-numpy python3-pil python3-simplejpeg || fail "apt"

step "2. agent virtualenv (--system-site-packages so picamera2 is visible; no torch/tf/mediapipe/opencv on the Pi)"
[ -d .venv-pi ] || python3 -m venv --system-site-packages .venv-pi || fail "venv"
.venv-pi/bin/pip install -e ".[pi]" --no-deps && .venv-pi/bin/pip install "websockets>=13.1,<15" "pillow>=10.4,<12" "psutil>=6" "pyyaml>=6" || fail "pip"
.venv-pi/bin/python -c "import convergent.pi_agent, websockets, PIL, psutil, yaml; print('agent imports ok')" || fail "import check"

step "3. agent config + token"
sed -e "s#^laptop_url:.*#laptop_url: ws://${LAPTOP_IP}:8765#" configs/pi_agent.yaml > "$HOME/pi_agent.yaml"
printf 'CONVERGENT_DEVICE_TOKEN=%s\n' "$TOKEN" | sudo tee /etc/convergent.env >/dev/null && sudo chmod 600 /etc/convergent.env
echo "wrote $HOME/pi_agent.yaml (laptop_url: ws://${LAPTOP_IP}:8765) and /etc/convergent.env"

step "4. camera overlay (Arducam B0176 = OV5647; Zero 2 W needs the 22-pin mini-CSI ribbon) + console boot"
CFG=/boot/firmware/config.txt; [ -f "$CFG" ] || CFG=/boot/config.txt
if ! grep -q '^dtoverlay=ov5647' "$CFG"; then
  sudo sed -i 's/^camera_auto_detect=1/camera_auto_detect=0/' "$CFG"
  grep -q '^camera_auto_detect=0' "$CFG" || echo 'camera_auto_detect=0' | sudo tee -a "$CFG" >/dev/null
  echo 'dtoverlay=ov5647' | sudo tee -a "$CFG" >/dev/null
  echo "added dtoverlay=ov5647 to $CFG (reboot required). For motorized focus follow docs/PI_SETUP.md §4 (Arducam VCM overlay)."
else
  echo "ov5647 overlay already present"
fi
sudo raspi-config nonint do_boot_behaviour B1 2>/dev/null || true

step "5. systemd service (starts the agent at boot, restarts on failure)"
sudo tee /etc/systemd/system/convergent-agent.service >/dev/null <<EOF
[Unit]
Description=Convergent handwashing camera agent
After=network-online.target
Wants=network-online.target
[Service]
User=$(id -un)
WorkingDirectory=$PWD
EnvironmentFile=/etc/convergent.env
ExecStart=$PWD/.venv-pi/bin/python -m convergent.pi_agent --config $HOME/pi_agent.yaml
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload && sudo systemctl enable convergent-agent >/dev/null || fail "systemd"

step "DONE"
cat <<EOF
Pi setup finished.
  * If the overlay was just added: sudo reboot   (then: rpicam-hello --list-cameras  must show ov5647)
  * Start now:        sudo systemctl start convergent-agent     logs: journalctl -u convergent-agent -f
  * Run in foreground: set -a; . /etc/convergent.env; set +a; .venv-pi/bin/python -m convergent.pi_agent --config ~/pi_agent.yaml
  * Laptop must be running START_LAPTOP.command (gateway ws://${LAPTOP_IP}:8765).
EOF
