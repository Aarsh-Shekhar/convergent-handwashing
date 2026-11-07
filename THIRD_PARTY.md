# Third-party code, models, data and licenses

Audited 2026-11-07 from fresh clones (commit hashes below). Nothing from the three
handwashing repositories is vendored verbatim; the integration re-implements their
documented preprocessing and loads their *artifacts* through explicit adapters.

## Repository A – juannquinones/HandHygiene

| Item | Finding |
|---|---|
| Commit audited | `b1b2e846f51410cc0b50a88941638485507f1009` (2025-07-10) |
| License file | `LICENSE.md` – titled "MIT License" but with custom wording; **clause 2 explicitly permits commercial use**. |
| README | States the project is "licensed for free and **non-commercial** use" and that a proper license is pending. |
| **Discrepancy (recorded as required)** | README (non-commercial) contradicts LICENSE.md (commercial use permitted). Until the authors clarify, this project treats the artifacts as usable for the Convergent build-team prototype only and does not redistribute them commercially. Contact in README: juannquinonesr@gmail.com. |
| Paper | https://doi.org/10.1016/j.cegh.2025.101971 |
| What we use | Algorithm (centroid-relative 42×3 landmark features, right-then-left ordering, `predict_proba` + 0.4 threshold) **re-implemented** in `detection/handhygiene_adapter.py`; model artifacts loaded, not copied into git except the 219 KB validated conversion `models/handhygiene/rf_10102024.numpy-forest.npz` (derived from `Data/Models/rf_10102024.pkl`, sha256 `5526e8d0…`). |
| Artifacts available upstream | `Data/Models/{lr,rf,svm}_10102024.pkl` (sklearn 1.0.2), `app/Models/lr_10102024.pkl`, `app/Models/lr_260624.pkl` (sklearn 1.2.1), training CSVs `Points_06032024.csv`, `Points_10102024.csv` (18,262 rows, 126 features + class 1..10). Videos (`Data/Videos`) are git-ignored upstream and not available. |
| Security | Pickles were statically inspected with `pickletools` (only numpy/sklearn globals) and are loaded through `RestrictedUnpickler`. The SVM pickle lacks `predict_proba` (SVC without `probability=True`) and is rejected by the adapter. |
| Dependencies upstream | `requirementsHandHygiene.txt` pins mediapipe 0.9.0.1, PyQt5/6, Windows-only paths – not installed. |

## Repository B – S-Kia/Hand_washing_application

| Item | Finding |
|---|---|
| Commit audited | `c128f5b18b2149628756ad4b0dd8caa808c26ef9` (2025-04-29) |
| License file | **None.** No license means all rights reserved by default; we do not vendor any source. The feature layout (left 63 + right 63), the 12 labels and the normalization formula are re-implemented from the documented behaviour in `detection/skia_adapter.py`. |
| Artifacts | `generalized_lstm_model.keras` (Keras 3.9.1, input `(None, 1, 126)`, sha256 `3c4f344d…`), `X.pkl` (joblib NumPy array, full dataset used for normalization, sha256 `e485687e…`), `data/landmark/*.csv` (12 files, 7,418 rows). Downloaded by `make models` for local evaluation only (not redistributed). |
| Dataset | Kaggle `realtimear/hand-wash-dataset` (check its license on Kaggle before any redistribution). |
| Credit chain | README credits SunnySideUp11/Hand-Hygiene-ICU as inspiration. |

## Repository C – dpt-xyz/hand-wash-compliance-yolo

| Item | Finding |
|---|---|
| Commit audited | `45d54cc8c3e1afb01c49b6096fd1ce785af7c6b3` (2021-03-25) |
| License file | **None** (all rights reserved by default). Nothing vendored. The dataset YAML, training command and class list are reproduced in `scripts/train_yolo.py`; preprocessing/decoding is our own implementation. |
| Artifacts | 707 annotated JPEG frames (567 train / 140 val) in YOLO format, 7 classes `Step1..Step7`; `HandWashDataset_yoloFormat/TestingData/missingStep_test1.mp4` (used as our sample recording – copy with `make samples UPSTREAM=…`, git-ignored); `results.png`. **No trained weights, no `custom.yaml`, no `detect_custom.py`.** |
| Caveat | Validation frames come from the same videos as training frames; the reported mAP 0.996 is not a generalisation estimate. |

## Frameworks and libraries

| Component | License | Use |
|---|---|---|
| MediaPipe 0.10.21 (legacy `solutions.hands` graph + `tasks` Hand Landmarker) | Apache-2.0 | shared hand tracking; the `hand_landmarker.task` bundle is downloaded from Google storage by `make models` |
| ultralytics/yolov5 `v7.0` (`third_party/yolov5`, git-ignored, cloned by `scripts/fetch_yolov5.sh`) | GPL-3.0 (v7.0 tag; later versions are AGPL-3.0) | YOLO branch model definition / `DetectMultiBackend` / training script. Imported at runtime only when a trusted checkpoint exists. Note: importing yolov5 monkey-patches `cv2.imread`. |
| PyTorch, torchvision | BSD-3 | corrected temporal LSTM, YOLO |
| TensorFlow / Keras 3 (optional `skia-legacy` extra) | Apache-2.0 | S-Kia legacy checkpoint only |
| OpenCV (opencv-contrib-python) | Apache-2.0 | video decoding, calibration (findHomography/RANSAC, calibrateCamera, ArUco) |
| scikit-learn, SciPy, NumPy | BSD-3 | HandHygiene pipeline, Hungarian assignment, metrics |
| FastAPI, Starlette, Pydantic, pydantic-settings | MIT | backend / schemas |
| SQLAlchemy, Alembic | MIT | persistence / migrations |
| uvicorn, httpx, websockets | BSD-3 / BSD-3 / BSD-3 | serving, client, transport |
| psutil, PyYAML, Pillow, python-dotenv | BSD-3 / MIT / HPND / BSD-3 | resources, config, Pi rendering |
| One Euro filter (Casiez, Roussel, Vogel 2012) | algorithm, re-implemented | target smoothing |

## Provenance record for model artifacts

See `configs/models.yaml` (`upstream_sha256` / `trusted_sha256`). `python scripts/fetch_models.py`
verifies every downloaded file against those hashes; `convergent models` prints the result.
