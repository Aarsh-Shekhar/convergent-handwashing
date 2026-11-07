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

## Training the corrected temporal model

1. Get the Kaggle dataset (videos per step folder).
2. `python scripts/extract_landmark_sequences.py --root data/HandWashDataset --out data/landmark_sequences`
   (per-video `.npz` with PTS timestamps, S-Kia feature layout from the shared tracker, presence flags, subject id from the file name).
3. `python scripts/train_lstm.py --data data/landmark_sequences --out models/skia_temporal/v0.1.0 --window 16 --stride 4 --epochs 40`
4. Inspect `meta.json` (`split.test_groups` must not overlap `train_groups`; `metrics.test`).
5. `cp -r models/skia_temporal/v0.1.0 models/skia_temporal/current` (or set `skia.temporal_artifact_dir`).

Why the S-Kia CSVs cannot be used: `Prepare_data.ipynb` writes all videos of a class into one
folder with overlapping file names (`{count}.jpg`) and then lists them with string sorting
(`0, 1, 10, 100, …`), so the CSV rows are neither one recording nor in temporal order.
`generalize_recognition_timestep` in the upstream trainer reshapes those shuffled rows into
"sequences" – this is exactly the mistake the corrected pipeline avoids.

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
