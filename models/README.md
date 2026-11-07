# models/

Model artifacts live here and are **not** committed (except the small, validated
`handhygiene/rf_10102024.numpy-forest.npz` conversion). Populate with:

    make models            # upstream HandHygiene pickles, S-Kia Keras checkpoint + scaler stats, MediaPipe task bundle
    make yolov5            # pinned YOLOv5 code (third_party/)
    python scripts/train_lstm.py ...   # corrected temporal model -> skia_temporal/<version>  (copy to skia_temporal/current)
    python scripts/train_yolo.py ...   # YOLOv5 handwashing weights -> yolo/handwash_yolov5.pt (register sha256 in configs/models.yaml)

`convergent models` prints what was found and whether each artifact is trusted.
