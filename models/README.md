# models/

Two artifacts are committed because the system needs them and they are small:

| Path | What | Size |
|---|---|---|
| `handhygiene/rf_10102024.numpy-forest.npz` | validated dependency-free conversion of the upstream HandHygiene RandomForest (18,262/18,262 rows identical to sklearn 1.0.2) | 219 KB |
| `skia_temporal/current/` | corrected temporal LSTM v0.1.0 trained on the Kaggle hand-wash dataset (`meta.json` = classes, window, split, metrics, provenance; `model.pt` = state_dict, loaded with `weights_only=True`; `scaler.npz`) | 2.2 MB |

Everything else is fetched or trained locally and git-ignored:

    make models                                  # upstream HandHygiene pickles, S-Kia Keras checkpoint + scaler stats, MediaPipe task bundle (hash-checked)
    make yolov5                                  # pinned YOLOv5 code (third_party/)
    python scripts/extract_landmark_sequences.py --root data/HandWashDataset --out data/landmark_sequences
    python scripts/sweep_lstm.py --data data/landmark_sequences      # retrain the temporal model; installs the winner to skia_temporal/current
    python scripts/train_yolo.py ...             # YOLOv5 handwashing weights -> yolo/handwash_yolov5.pt (register sha256 in configs/models.yaml)

`.venv/bin/python -m convergent.cli models` prints what was found and whether each artifact is trusted.
How the temporal model was trained and how well it does: `docs/MODEL_INTEGRATION.md`, `docs/TEST_RESULTS.md` §3.
