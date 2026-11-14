# Model card – Convergent handwashing recognition stack v1.0 (frozen 2026-11-14)

One page for demo day, the pitch and anyone evaluating the model. Numbers are copied from
`docs/TEST_RESULTS.md`; nothing here is rounded up.

## What it is

Three small models behind one shared hand tracker, running on a laptop at ~25 frames/s:

| Component | Does | Size | Input | Output |
|---|---|---|---|---|
| MediaPipe Hands (Google) | finds up to 2 hands, 21 landmarks each | – | camera frame | landmarks |
| `temporal_v2` (ours) | names the WHO technique being performed | 2.2 MB TCN | last 48 frames (3.2 s) of hand-relative geometry | 7 techniques + "not washing", calibrated probability |
| `side_resolver` (ours) | which hand is receiving a one-sided technique | 108 KB MLP | current frame's hand geometry + technique | P(right hand receives) |

Downstream (not learned): fusion → temporal validator (≥ 0.5 s support, hysteresis 0.6/0.4) →
`GestureEvent`s → per-region evidence → wash score (per-step timers, 0–100 points, 0–5 stars).

## The 7 techniques

palm to palm · palm over back of hand (L/R) · fingers interlaced · backs of fingers (L/R) ·
thumb rubbing (L/R) · fingertips in palm (L/R) · wrist (L/R; WHO's optional step 7). Plus `none`.

## Training data

| Set | Washes | Frames | Camera | People |
|---|---|---|---|---|
| METC (Zenodo 5808789) | 212 | 208 k | overhead sink, hospital | 72 |
| Kaggle hand-wash dataset | 300 clips (25 sessions) | 58 k | overhead sink, 5 locations | ≤ 25 |
| Our webcam rounds | 3 | ~6 k | laptop webcam, front view | 1 |

All adults. No children. No footage from the faucet-mounted camera yet (hardware not arrived).
Side resolver: the 250 sided Kaggle clips only.

## Measured accuracy

| What | Held out | Result |
|---|---|---|
| Technique, window level | METC people never seen | 79 % accuracy, 0.80 macro-F1 |
| Technique, window level | Kaggle washes never seen | 99 % |
| Full pipeline, credited seconds / performed seconds | METC people | **70 %** mean over steps (palm 80 %, back of hand 84 %, thumb 53 %) |
| Label flicker | METC people | 24 changes/min (truth 7.8; previous models 248) |
| Full pipeline on **our** webcam, different round held out | Andrew | 48 % credited (24 % before own data) |
| Side resolver | Kaggle sessions never seen | 96.5 % per frame, 96–100 % per clip |
| Sample "missing thumb" clip | – | 6 events in WHO order, thumb absent, sides correct, 3★/80 |

Published landmark-based results on METC are ~0.70 macro-F1; ours is 0.80 on a comparable split.

## Known limits (say these out loud)

1. **Measures motion, not cleanliness.** Credited seconds per technique and region evidence are
   proxies; nothing detects soap, water or microbes.
2. **Our camera is unmeasured.** Every number above is from overhead sink footage of adults. Two
   rounds of one teammate's webcam moved accuracy from 24 % to 59 %; more people and the real
   mount are the next lever (`docs/RECORDING_GUIDE.md`).
3. **Children's hands: zero data.** Smaller, faster, more occluded. Needs consented recordings.
4. **Thumb rubbing is the weakest step** (53 % credited): the tracker loses both hands.
5. **"Other movement" earns ~1.3 s of step credit per 10 s** on METC; idle hands at our sink untested.
6. **Side resolver trained on one camera family**; `mirrored` flag covers a user-facing camera,
   accuracy on it is not yet measured.
7. Confidence values are calibrated on METC/Kaggle only (temperature 1.05, ECE 0.031).

## Reproduce

```bash
make accept                                                     # 1 min: known answer on the sample clip
.venv/bin/python scripts/benchmark_recognition.py --metc data/METC   # held-out METC people through the pipeline
.venv/bin/python scripts/train_side_resolver.py                      # 40 s, prints grouped cross-validation
```

Artifacts: `models/temporal_v2/current` (sha256 f33fdd0d…), `models/side_resolver/current`
(sha256 939ac261…), both committed; `configs/models.yaml` lists the hashes.
