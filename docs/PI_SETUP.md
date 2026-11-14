# Raspberry Pi 3 Model A+ setup (camera agent)

Status: **prepared, not executed on hardware** (the Pi, Arducam B0176 and RIF6 have not
arrived). Commands reference the official Raspberry Pi and Arducam documentation; verify each
step on the device and update this file.

Hardware (fixed): Pi Zero 2 W (or 3 A+) (512 MB, 1 USB, CSI, full-size HDMI, micro-USB power), Arducam B0176
(OV5647 5 MP, motorized focus, CSI ribbon), PNY 32 GB microSD, onn. 10,000 mAh power bank
(USB-A → micro-USB), full-size HDMI → mini-HDMI to the RIF6 Cube, Frost King foam tape mount.

## 1. OS image

1. Raspberry Pi Imager → **Raspberry Pi OS Lite (64-bit, Bookworm)** – Lite keeps memory free;
   64-bit matches current Picamera2/libcamera packages. (If the Arducam OV5647 VCM overlay turns
   out to need the 32-bit legacy stack, use Raspberry Pi OS Lite 32-bit; decide after step 5.)
2. In Imager "OS customisation": hostname `convergent-pi`, user `pi` (set a real password), Wi-Fi
   SSID/password + country, **enable SSH** (password or key), locale/timezone.
3. Flash the PNY 32 GB card (teammate's reader), boot, `ssh pi@convergent-pi.local`.

## 2. Base packages

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git python3-venv python3-pip python3-picamera2 python3-libcamera python3-numpy python3-pil python3-simplejpeg
sudo raspi-config nonint do_boot_behaviour B1   # console, no desktop (framebuffer rendering)
```

## 3. Project checkout and agent environment

```bash
git clone <this repo> ~/convergent-handwashing && cd ~/convergent-handwashing
make install-pi            # venv with --system-site-packages so picamera2 (apt) is visible; installs websockets/pillow/psutil/pyyaml only
cp configs/pi_agent.yaml ~/pi_agent.yaml && nano ~/pi_agent.yaml   # laptop_url: ws://<LAPTOP_IP>:8765, device_id
echo 'CONVERGENT_DEVICE_TOKEN=<same token as the laptop .env>' | sudo tee /etc/convergent.env
```

Nothing from PyTorch/TensorFlow/MediaPipe/OpenCV is installed on the Pi (spec §2).

## 4. Camera (Arducam B0176, OV5647 with motorized focus)

Follow Arducam's quick-start for the OV5647 motorized-focus camera on Bookworm
(https://docs.arducam.com/Raspberry-Pi-Camera/Motorized-Focus-Camera/Quick-Start-Guide/OV5647-Motorized-Focus-Camera/).
Expected steps (verify against the page for the OS release you flashed):

1. Connect the 15-pin ribbon (contacts facing the HDMI side on the Pi Zero 2 W (or 3 A+) CSI connector).
2. `/boot/firmware/config.txt`: `camera_auto_detect=0` and `dtoverlay=ov5647` (Arducam
   documents a VCM-enabled overlay/tuning file for focus control – install exactly what the
   page specifies for your OS version; keep a copy of the original tuning JSON).
3. Reboot, then verify:
   ```bash
   rpicam-hello --list-cameras          # must list ov5647
   rpicam-still -o /tmp/test.jpg --width 640 --height 480 -t 2000
   rpicam-hello -t 5000 --autofocus-mode continuous   # focus motor test (if the VCM driver is active)
   python3 -c "from picamera2 import Picamera2; c=Picamera2(); print(c.sensor_modes)"
   ```
4. Focus from the agent: `Picamera2Camera.set_focus(None)` (continuous AF) or
   `set_focus(<dioptres>)` (manual `LensPosition`). Unverified until hardware arrives.

## 5. HDMI / projector

* RIF6 Cube: mini-HDMI input, native 854×480. Connect before boot. Check the negotiated mode:
  `cat /sys/class/graphics/fb0/virtual_size` and `kmsprint` (or `tvservice -s` on legacy).
* If the projector shows nothing: in `config.txt` set `hdmi_force_hotplug=1`,
  `hdmi_group=2`/`hdmi_mode=87` with a custom `hdmi_cvt=854 480 60 6 0 0 0`, or let it
  negotiate 720p – the renderer letterboxes the 854×480 logical canvas into whatever `/dev/fb0`
  reports (`FramebufferRenderer`).
* Quick framebuffer test: `python3 -m convergent.pi_agent --renderer framebuffer --camera emulated --max-frames 1`
  then send a render command from the laptop (`convergent network` with a calibration profile).

## 6. Run the agent

```bash
source .venv-pi/bin/activate
set -a; source /etc/convergent.env; set +a
python -m convergent.pi_agent --config ~/pi_agent.yaml      # Ctrl-C = controlled shutdown (camera stop, framebuffer cleared)
```

### systemd service

```ini
# /etc/systemd/system/convergent-agent.service
[Unit]
Description=Convergent handwashing camera agent
After=network-online.target
Wants=network-online.target
[Service]
User=pi
WorkingDirectory=/home/pi/convergent-handwashing
EnvironmentFile=/etc/convergent.env
ExecStart=/home/pi/convergent-handwashing/.venv-pi/bin/python -m convergent.pi_agent --config /home/pi/pi_agent.yaml
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
```
`sudo systemctl enable --now convergent-agent` · logs: `journalctl -u convergent-agent -f`.

## 7. Bandwidth / latency trade-off (spec §7)

640×480 JPEG q=80 ≈ 35–60 KB/frame → 4–7 Mbit/s at 15 FPS. The Pi Zero 2 W (or 3 A+) 2.4/5 GHz radio
handles this with ~1–2 frames (70–130 ms) of encode+transport latency on a quiet 5 GHz network.
Bottlenecks are JPEG encoding on the CPU (~15–25 ms/frame at 640×480 with simplejpeg) and Wi-Fi
contention. H.264 (hardware encoder, ~0.5 Mbit/s) would be added as a new `encoding` value in
`communication/protocol.py`; only `pi_agent/camera.py` and `communication/websocket.py` change.
The send queue is 2 deep (latest wins): a congested link drops frames instead of adding latency;
drops are counted in the status message (`frames_dropped`).

## 8. Troubleshooting

| Symptom | Check |
|---|---|
| `under_voltage: true` / throttled flags `0x5000x` in status | the onn. power bank must deliver ≥ 2.5 A at 5 V; use a short, thick USB-A→micro-USB cable; `vcgencmd get_throttled` on the Pi (bit 0 now, bit 16 since boot). |
| `camera_ok: false` / `CameraUnavailable` | ribbon seating, `dtoverlay=ov5647`, `rpicam-hello --list-cameras`, `dmesg | grep -i ov5647`; make sure the venv uses `--system-site-packages`. |
| `display_ok: false` | `/dev/fb0` missing → HDMI not negotiated; connect the projector before boot, see §5. |
| agent keeps reconnecting | laptop gateway not running (`convergent network`), wrong `laptop_url`, token mismatch (`last_error: unauthorized` stops the agent), firewall on the laptop (allow TCP 8765). |
| frames arrive but pipeline says `tracking lost` | lighting/focus; run `convergent network --save-results` and inspect `runs/<session>/frames.jsonl`, or save JPEGs on the laptop for inspection. |
| high `frames_dropped` | Wi-Fi congestion → lower `fps`/`jpeg_quality` in `pi_agent.yaml`; move to 5 GHz. |
