# Model integration: the three upstream projects

## Summary table

| | HandHygiene (A) | S-Kia (B) | dpt-xyz YOLO (C) |
|---|---|---|---|
| Reused algorithm | centroid-relative landmark features + sklearn classifier; `predict_proba` threshold 0.4 → "no step" | left+right raw landmark vector, 12 Kaggle labels, LSTM; legacy normalization from the whole dataset | YOLOv5s detection on frames, 7 classes `Step1..Step7`, step durations / missing steps |
| Native input | 126 = **right** (21×3 − centroid) ‖ **left** (21×3 − centroid), row-major x,y,z; missing hand = zeros | 126 = **left** (21×3 raw) ‖ **right** (21×3 raw); missing hand = zeros; `(x − mean)/(std + 1e-8)`; shape `(1, 1, 126)` | 640×640 letterboxed RGB float32 /255 |
| Native labels | `classes_ = 1..10` ↔ `1, 2.1, 2.2, 3, 4.1, 4.2, 5.1, 5.2, 6.1, 6.2` | `1, 2lt, 2rt, 3, 4lt, 4rt, 5lt, 5rt, 6lt, 6rt, 7lt, 7rt` | `Step1..Step7` (0..6) |
| Artifacts | RF/LR/SVM pickles (sklearn 1.0.2/1.2.1) – **present**; RF converted to `numpy-forest-v1` (validated exactly), LR loads directly; SVM has no `predict_proba` | `generalized_lstm_model.keras` + `X.pkl` – **present** (optional TF extra, loads with TF 2.18/Keras 3.15) | **none** – annotations only |
| Adapter | `detection/handhygiene_adapter.py` | `detection/skia_adapter.py` (`SkiaLegacyAdapter`, `SkiaTemporalAdapter`) | `detection/yolo_adapter.py` |
| Changes made | fixed order-based two-hand assignment (handedness-driven slots), replaced `verify_hand_rows` with explicit missing hands, exposed full distribution, decoupled from GUI, pinned modern deps | corrected temporal model (16-frame contiguous windows, presence flags, grouped split, train-only scaler, versioned artifact); legacy kept as a separate adapter | own preprocessing/decode/NMS, hash-allow-listed loading, training script with dataset yaml, availability reporting |
| Known limitations | trained on the author's own top-down videos with the assignment bug; accuracy on our camera unverified (0.30 frame accuracy on the sample video) | legacy model is a 1-timestep classifier with leaky normalization; temporal artifact needs real sequence data | validation frames from training videos; no weights; 1-epoch smoke checkpoint only |

## Handedness convention (Stage 3)

MediaPipe reports handedness assuming a mirrored/selfie image. The faucet camera looks down at
the hands from the far side of the basin, producing a **non-mirrored** image, so
`tracker.swap_handedness: true` turns MediaPipe's label into the anatomical side. Verify on
hardware: hold up the right hand only, run `convergent network --save-results`, and check
`hands.right` is populated in `runs/<session>/frames.jsonl`; if the left slot fills, set
`swap_handedness: false`. Both the raw label and the anatomical side are stored on every
`HandObservation`; the upstream adapters use the raw label (`feed_mode: raw_label`) so the
pretrained models see the same slot convention they were trained with (single-hand case) –
note the upstream two-hand case was order-based, i.e. effectively random.

## Resolving side semantics

`2.1/2.2` (HandHygiene) and `2lt/2rt` (S-Kia / Kaggle) are mapped to the right technique but
with `side: unresolved`. To resolve: watch examples (Kaggle `Step_2_Left` videos; HandHygiene
`Paso_2.MOV` is not public), decide which hand is being acted upon, then add e.g.

```yaml
side_resolution:
  "skia:2lt": left
  "skia:2rt": right
  "handhygiene:2.1": right
```

to `configs/labels.yaml`. Until then, fusion reports `side=unresolved`, the temporal validator
produces technique-level events with `side_resolved=false`, and region evidence for those events
is recorded as *unattributed* instead of being assigned to a hand (`regions.use_unresolved_side_evidence`).

## Training the corrected temporal model (done – this is how `models/skia_temporal/current` was made)

Dataset: Kaggle `realtimear/hand-wash-dataset` – 300 MP4s, 12 folders `Step_1 … Step_7_Right`,
25 recording sessions (`HandWash_001 … 025`) in 5 sink/location groups (`G_01 … G_05`, see the
dataset's `HandwashList.txt`); 720×480 or 1920×1080 at 30 FPS; adults, overhead sink camera.
Put it at `data/HandWashDataset/` (not committed – 1.3 GB).

```bash
# 1. landmarks: one .npz per video from the SHARED tracker (15 FPS decimation on PTS, raw_label feed, presence flags; ~25 min on 2 CPU cores)
.venv/bin/python scripts/extract_landmark_sequences.py --root data/HandWashDataset --out data/landmark_sequences
# 2. small sweep on a FIXED session-grouped split, winner chosen on validation macro-F1, installed to models/skia_temporal/current
.venv/bin/python scripts/sweep_lstm.py --data data/landmark_sequences --out runs/lstm_sweep --epochs 80
# 3. stricter estimate: leave-one-sink-group-out cross-validation with the winning hyper-parameters
.venv/bin/python scripts/crossval_lstm.py --data data/landmark_sequences --window <W> --stride <S> --hidden <H> --epochs 80
# (single run, no sweep:)  .venv/bin/python scripts/train_lstm.py --data data/landmark_sequences --out models/skia_temporal/v0.2.0
```

What the trainer guarantees: windows come from contiguous, timestamp-ordered frames of one
recording and never contain a frame with no hands (the inference buffer resets there, so train and
inference see the same thing); the split is grouped (session id, or `--group-regex` for the sink
group); the scaler is fitted on training windows only, with a std floor so near-constant features
(MediaPipe wrist z) cannot amplify noise; class-balanced cross-entropy with label smoothing,
AdamW, LR plateau schedule, early stopping on validation loss; and `meta.json` records classes,
window geometry, dataset fingerprint, split groups, hyper-parameters and the metrics.

Training-time augmentation (`AugmentConfig`, inference preprocessing unchanged): one random
translation and isotropic scale per window (both hands), x/y jitter, and optional horizontal
mirroring that swaps the left/right blocks, the presence flags and the label side (`2lt` ↔ `2rt`).
The sweep compares mirror on/off; see `docs/TEST_RESULTS.md` §3 for the numbers.

Facts to keep in mind when reading the metrics:

* In the Kaggle videos the two hands overlap so much that MediaPipe finds **one** hand in ~97 % of
  frames (raw MediaPipe, not our tracker – verified). The model therefore mostly learns from one
  hand's 21 landmarks over time plus *which* hand is visible. Our faucet camera will see the hands
  differently; record our own clips before trusting any number (`docs/HARDWARE_DAY_RUNBOOK.md` §4).
* "Session" is the only identity the file names carry. Sessions in the same sink group may well
  be the same person, which is why the sink-group cross-validation is reported as well.
* Side semantics (`2lt` vs `2rt`) remain `unresolved` in `configs/labels.yaml` until someone looks
  at the videos and writes down what "Left" means; the model predicts the native label either way.

Why the S-Kia CSVs cannot be used: `Prepare_data.ipynb` writes all videos of a class into one
folder with overlapping file names (`{count}.jpg`) and then lists them with string sorting
(`0, 1, 10, 100, …`), so the CSV rows are neither one recording nor in temporal order.
`generalize_recognition_timestep` in the upstream trainer reshapes those shuffled rows into
"sequences" – this is exactly the mistake the corrected pipeline avoids.

## The hand-relative temporal model (`temporal_v2`) – what the pipeline should use

Why it exists (measured on webcam runs, 2026-11-10): the v1 LSTM above reads raw image
coordinates in MediaPipe's left/right slots. On Kaggle footage the tracker sees one hand in
~97 % of frames, so the model learned "which single hand is visible"; on a live camera with two
tracked hands it called palm-to-palm "interlaced" (0–3 % palm recall with two hands), and the
fused label flipped ~200 times a minute. `temporal_v2` replaces the representation, the
slotting, the class list and the windowing:

| | v1 `skia_temporal` | v2 `temporal_v2` |
|---|---|---|
| Features | raw x, y, z in the image | per hand: 21 landmarks in the hand's own frame (wrist origin, in-plane rotation removed, divided by hand size), wrist velocity / turn rate / size change; the other hand's key points seen from this hand; palm distance; presence (183 values, `detection/pair_features.py`) |
| Invariant to | ±8 % shift, ±12 % scale (augmentation only) | translation, scale, in-plane rotation **by construction**; camera tilt, speed, hand size, a hidden hand by augmentation |
| Hand slots | MediaPipe handedness label; a hand without a resolved side is dropped | position continuity (`HandSlotter`), unassigned hands included; trained with random slot swaps and evaluated on both orders |
| Classes | 12 (Kaggle left/right variants) | the 7 techniques + `none` (not washing). No left/right: the coverage layer will get the side from geometry |
| Window | 24 frames *with a hand*; any 0.25 s dropout resets it (1.6 s warm-up) | the last N frames on the frame clock; empty frames stay in, short history is left-padded; answers after 8 frames with a hand and keeps its history through dropouts |
| Model | 2-layer LSTM | temporal convolution network (residual dilated blocks) – `lstm_model._build_tcn`; GRU also available |
| Output | raw softmax | temperature-calibrated on validation subjects (`calibrator.json`), then smoothed (`temporal_v2.smooth_s`) |
| Tracker for the training data | legacy `solutions` graph | the same backend and settings as the live pipeline (`configs/development.yaml: tracker`) |

Data it can train on (all extracted with `scripts/extract_landmarks_v2.py` into `data/landmarks_v2/`, git-ignored):

* **METC** (Zenodo 10.5281/zenodo.5808789, CC BY 4.0, 2.1 GB, no login): 212 washes by medical
  students, a label on every frame (WHO steps 1–6, 0 = other). Top-down sink camera. Frames
  within ±0.5 s of a label change are marked `ignore` (the labels were made live). No wrist step.
* **Kaggle** `realtimear/hand-wash-dataset` (CC BY-SA 4.0, needs a Kaggle login): ~290 clips from
  25 washes, one label per clip. The only public source of wrist rubbing. Left/right folders are merged.
* **Own clips** from `convergent record` (`docs/RECORDING_GUIDE.md`): one clip per class per round,
  recorded on the camera we actually use. Weighted ×4 in training; whole rounds are held out for testing.

```bash
# 1. landmarks (re-run any time; existing files are skipped)
.venv/bin/python scripts/extract_landmarks_v2.py --metc data/METC --kaggle data/HandWashDataset --own data/own
# 2. train (Apple GPU), hold out own rounds for the honest test, install for the live pipeline
.venv/bin/python scripts/train_temporal_v2.py --out runs/v2/<name> --device mps --test-own-rounds down2,front2 --install
# 3. measure through the REAL pipeline (tracker + fusion + validator), before/after
.venv/bin/python scripts/benchmark_recognition.py --metc data/METC --rounds down2,front2 --out runs/benchmark.json
```

Splits are by person / wash / recording round (`pair_training.partition_groups`, stable per
dataset), so the benchmark's held-out METC subjects are exactly the ones training never saw.
Results: `docs/TEST_RESULTS.md` §7.

## Training / registering YOLO

```bash
bash scripts/fetch_yolov5.sh
python scripts/train_yolo.py --dataset <HandWashDataset_yoloFormat> --epochs 100 --out runs/yolo_handwash   # CPU: hours; GPU recommended
cp runs/yolo_handwash/exp/weights/best.pt models/yolo/handwash_yolov5.pt
sha256sum models/yolo/handwash_yolov5.pt   # add to configs/models.yaml -> artifacts.yolo.trusted_sha256
```
Checkpoints are full pickles, so the adapter refuses any hash that is not registered. For real
validation you need recordings that are not in the training frames (the upstream val split is
from the same videos).

## Calibration of branch confidences and fusion weights

1. Run the pipeline on held-out annotated recordings with `--save-results`.
2. Fit `Calibrator.fit_temperature(probs, labels)` per branch on those predictions; save with `Calibrator.save` and load them into `FusionEngine(calibrators=...)`.
3. Derive `fusion.weights` from per-branch held-out macro-F1 (or fit `MetaClassifierFusion` on out-of-sample predictions).
4. `scripts/evaluate_models.py --ablation` shows whether the fused result beats the best single branch; do not assume it does.

## Foam / soap

`regions/foam.py` is an explicitly experimental, unvalidated proxy (bright, low-saturation pixel
fraction inside the palm polygon). It is never used by the core detector. Training a real foam
classifier requires a labeled dataset (`train_foam_classifier` refuses to run without one).
