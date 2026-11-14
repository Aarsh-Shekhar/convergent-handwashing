# Projected game graphics (germ-dinos) and the laptop preview

Built 2026-11-14. The first piece of the game layer that is actually in the repo: germ
dinosaurs on the hands that wash away as region evidence grows, a soft glow under the active
hand, and a basin-anchored strip with the current prompt, seven step bars, stars and the soap
tick. It is rendered through the same `RenderCommand` protocol the Pi draws, so **what the
laptop preview shows is exactly what the projector will show** once the hardware is here.

## Try it now (laptop webcam, no projector)

```bash
cd ~/Downloads/convergent-handwashing
.venv/bin/python -m convergent.cli camera --device 1 --show --projection --save-results --backend inprocess
# or on the sample clip:
.venv/bin/python -m convergent.cli replay --video data/samples/handwashing_missing_step.mp4 --show --projection
```

In the window: the green **PROJECTION: ON (P)** button (click it, or press `P`) toggles the
graphics. The germs are composited onto the camera image where the projector would put them
(additive, like light on skin) and the bottom-right inset shows the raw projector canvas, i.e.
what the Pi receives. `Esc` stops.

Without a calibration profile the camera view is stretched over the whole 854×480 canvas
(`projector.graphics.preview_without_calibration`). With a valid profile the real homography is
used both ways (canvas → camera for the preview, camera → canvas for the Pi).

## What the pieces are

| Piece | File | Notes |
|---|---|---|
| Sprites (`dino`, `blob` glow, `pop` burst) | `projection/sprites.py` | drawn from polygons with PIL, no bitmaps, no licensed characters; identical on Pi and laptop |
| Scene | `projection/scene.py` `GermScene` | 3 germs per (hand, region) cell at fixed offsets in the hand's own frame (wrist → middle MCP axis), so they ride with the hand; a cell's germs die as `observed_duration_s / min_sufficient_duration_s` grows; each death plays a 0.5 s pop |
| Protocol | `communication/protocol.py` | new shapes `sprite`, `filled_polygon`, `bar`; new `RenderItem` fields `sprite, angle, alpha, progress, size` (old messages still parse) |
| Pi renderer | `pi_agent/renderer.py` | draws the new shapes; TrueType font when available |
| Pipeline | `pipeline.py` `_render_graphics` | builds a `RenderCommand` per frame (`FrameResult.render`), sends it to the Pi gateway instead of the diagnostic crosshairs when graphics are on |
| Preview | `vision/overlays.py` `ProjectionPreview` | composite + button + inset |
| Config | `configs/development.yaml: projector.graphics` | `enabled`, `germs_per_region`, `germ_size_px`, `lead_ms`, `show_ui`, `preview_without_calibration` |

The scene reads `ProgressState`, `WashScore` and the soap state. It never writes to them.

## Rules taken from Casper DPM (SIGGRAPH Asia 2024) and why

Casper projects 3D content onto moving hands with a 1000 fps projector, a 525 fps infrared
camera and an RTX GPU. We have a 60 Hz projector and a Wi-Fi camera, so we keep the ideas,
not the hardware:

1. **Predict ahead.** Hand-attached graphics are extrapolated along the hand's velocity by
   `lead_ms`. Set it to the measured capture → photon latency on hardware day (the Pi acks every
   render command; the summary reports the round trip). Default 0 until measured.
2. **No crisp edges on the skin.** Everything attached to the hand is small (sprites) or soft
   (blurred glow). A misalignment of a few centimetres then reads as "the germ wiggled", not as
   "the projection is broken".
3. **Detail goes where nothing moves.** Prompt, step bars, stars and the soap tick live in a
   fixed strip at the bottom of the canvas, meant for the basin or wall next to the hands.
4. **Warp to landmarks, not to a fixed sprite.** Germ positions come from the region polygons of
   the current frame, so they follow finger spread and rotation.

## Frame rate matters more than anything here (2026-11-14 finding)

The first live runs on a MacBook M3 processed only 7–9 frames/s (summary.json: `frames /
duration_s`), with the MediaPipe `tasks` backend at 35–50 ms/frame and `cap.read()` blocking in
series with the model. The technique model was trained on 15 FPS windows, so at 8 FPS it saw
every motion twice as fast and phases came out short or wrong. Three fixes:

1. `temporal_v2` now resamples its window onto the 15 FPS grid (linear interpolation of
   landmarks between frames); on the sample clip decimated to 8 and 6 FPS the credited seconds
   are now within a few seconds of the 15 FPS answer, with the thumb still correctly missing.
   At 15 FPS the window is bit-identical (regression fingerprint and acceptance unchanged).
2. The webcam is read in a background thread, so the pipeline always takes the newest frame
   instead of waiting ~33 ms for the next one.
3. `tracker.backend` defaults to `solutions` (about 2× faster than `tasks` on macOS).

The live window prints `pipeline N fps` and warns below 12. If it is still low: close other
apps, lower `source.width/height` to 640×480, or turn the projection preview off (P) while
testing recognition; the Pi path never pays the preview cost.

**Why it looked worse than on Andrew's laptop:** the installed model was fine-tuned on
Andrew's own webcam rounds (weight 12). On his hands and camera it is close to 100 %; on anyone
else it is the held-out case (48–59 % credited). Recording your own rounds and fine-tuning is
the fix (`docs/RECORDING_GUIDE.md`, `scripts/train_temporal_v2.py --init-from ... --own-weight 12`).

## Known limits

* The dinos sit on MediaPipe's hand outline; when the tracker loses a hand the germs vanish
  with it and come back when it is found again (no persistence across dropouts yet).
* Which germs die depends on region evidence, i.e. on the side resolver and the sided
  techniques; a hand MediaPipe labels wrongly gets the other hand's evidence.
* ~50 ms per frame for the preview composite on a laptop (PIL blur + resize); the Pi only
  draws the canvas (no composite).
* Preview without calibration assumes the projector covers the camera view exactly, which is
  false on real hardware: calibrate before judging alignment.
