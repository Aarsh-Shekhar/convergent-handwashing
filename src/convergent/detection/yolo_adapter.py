"""YOLOv5 image branch adapter (dpt-xyz/hand-wash-compliance-yolo).

Audit result (see THIRD_PARTY.md / docs/MODEL_INTEGRATION.md): the upstream repository ships
707 annotated frames in YOLO format (567 train / 140 val, 7 classes ``Step1..Step7``) and a
Colab notebook that trains **YOLOv5s (v4.0 era, detection)** from ``yolov5s.pt`` for 100
epochs. It does **not** ship trained weights, ``custom.yaml`` or ``detect_custom.py``. The
reported 0.996 mAP is on validation frames cut from the *same videos* as training, so it
is not evidence of real-world performance.

This adapter therefore:

* discovers weights at ``YoloConfig.weights_path`` and refuses to load a checkpoint whose
  sha256 is not registered in ``configs/models.yaml`` (YOLOv5 ``.pt`` files are full pickled
  models and execute code on load),
* loads through the pinned ``third_party/yolov5`` checkout (``make yolov5``), the architecture
  the upstream notebook actually used – NOT the newer ``ultralytics`` package,
* implements letterbox preprocessing, decode, per-class NMS and box rescaling here (unit-tested),
* maps ``Step1..Step7`` to canonical labels via the registry,
* reports ``MODEL_UNAVAILABLE`` (never fake boxes) when weights are absent.

Training/evaluation: ``scripts/train_yolo.py`` writes the dataset yaml and invokes the pinned
``yolov5/train.py`` with the upstream hyper-parameters.
"""

from __future__ import annotations

import sys
from typing import Any

import cv2
import numpy as np

from convergent.common.config import YoloConfig, resolve_path
from convergent.common.logging import get_logger
from convergent.common.types import FramePacket, ModelPrediction
from convergent.detection.base import (
    ArtifactStatus,
    Classifier,
    Stopwatch,
    sha256_of,
    valid_prediction,
)
from convergent.detection.labels import LabelRegistry, ModelLabelMap, default_registry
from convergent.detection.registry import ModelRegistry

log = get_logger(__name__)

YOLO_PREPROCESSING_VERSION = "yolov5-letterbox-640-v1"
YOLO_NATIVE_NAMES = ["Step1", "Step2", "Step3", "Step4", "Step5", "Step6", "Step7"]


# --------------------------------------------------------------------------- preprocessing
def letterbox(img: np.ndarray, new_shape: int = 640, color: tuple[int, int, int] = (114, 114, 114), stride: int = 32) -> tuple[np.ndarray, float, tuple[float, float]]:
    """Resize keeping aspect ratio and pad to a multiple of ``stride`` (YOLOv5 convention).

    Returns (padded_image, ratio, (pad_w, pad_h)).
    """
    h, w = img.shape[:2]
    r = min(new_shape / h, new_shape / w)
    new_unpad = (int(round(w * r)), int(round(h * r)))
    dw, dh = new_shape - new_unpad[0], new_shape - new_unpad[1]
    dw, dh = dw % stride, dh % stride  # minimum rectangle padding
    dw /= 2
    dh /= 2
    if (w, h) != new_unpad:
        img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return img, r, (dw, dh)


def to_model_input(bgr: np.ndarray, img_size: int) -> tuple[np.ndarray, float, tuple[float, float]]:
    """BGR HxWx3 uint8 -> float32 (1,3,H',W') RGB in [0,1] with letterbox geometry."""
    lb, r, pad = letterbox(bgr, img_size)
    rgb = lb[:, :, ::-1].transpose(2, 0, 1)
    x = np.ascontiguousarray(rgb, dtype=np.float32) / 255.0
    return x[None], r, pad


def scale_boxes(boxes: np.ndarray, ratio: float, pad: tuple[float, float], orig_shape: tuple[int, int]) -> np.ndarray:
    """Letterbox xyxy -> original-image xyxy, clipped."""
    out = boxes.copy().astype(np.float64)
    out[:, [0, 2]] -= pad[0]
    out[:, [1, 3]] -= pad[1]
    out /= ratio
    h, w = orig_shape
    out[:, [0, 2]] = out[:, [0, 2]].clip(0, w)
    out[:, [1, 3]] = out[:, [1, 3]].clip(0, h)
    return out


def xywh2xyxy(x: np.ndarray) -> np.ndarray:
    y = np.empty_like(x)
    y[:, 0] = x[:, 0] - x[:, 2] / 2
    y[:, 1] = x[:, 1] - x[:, 3] / 2
    y[:, 2] = x[:, 0] + x[:, 2] / 2
    y[:, 3] = x[:, 1] + x[:, 3] / 2
    return y


def nms(boxes: np.ndarray, scores: np.ndarray, iou_thres: float) -> list[int]:
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1).clip(0) * (y2 - y1).clip(0)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = (xx2 - xx1).clip(0) * (yy2 - yy1).clip(0)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-12)
        order = order[1:][iou <= iou_thres]
    return keep


def decode_predictions(raw: np.ndarray, conf_thres: float, iou_thres: float, max_det: int = 50) -> np.ndarray:
    """YOLOv5 raw output (N, 5+nc) [cx,cy,w,h,obj,cls...] -> (M, 6) [x1,y1,x2,y2,conf,cls]."""
    raw = np.asarray(raw, dtype=np.float64)
    if raw.ndim != 2 or raw.shape[1] < 6:
        raise ValueError(f"unexpected raw output shape {raw.shape}")
    obj = raw[:, 4]
    cand = raw[obj > conf_thres]
    if cand.size == 0:
        return np.zeros((0, 6))
    cls_scores = cand[:, 5:] * cand[:, 4:5]
    cls = cls_scores.argmax(axis=1)
    conf = cls_scores[np.arange(len(cand)), cls]
    keep_mask = conf > conf_thres
    cand, cls, conf = cand[keep_mask], cls[keep_mask], conf[keep_mask]
    if cand.size == 0:
        return np.zeros((0, 6))
    boxes = xywh2xyxy(cand[:, :4])
    # class-offset trick for per-class NMS
    offset = cls[:, None] * 4096.0
    keep = nms(boxes + offset, conf, iou_thres)[:max_det]
    return np.concatenate([boxes[keep], conf[keep, None], cls[keep, None].astype(np.float64)], axis=1)


def detections_to_distribution(dets: np.ndarray, names: list[str]) -> dict[str, float]:
    """Per-class maximum detection confidence. NOT a calibrated posterior: values need not sum to 1."""
    dist = {n: 0.0 for n in names}
    for d in dets:
        c = int(d[5])
        if 0 <= c < len(names):
            dist[names[c]] = max(dist[names[c]], float(d[4]))
    return dist


# --------------------------------------------------------------------------- adapter
class YoloAdapter(Classifier):
    model_id = "yolo"
    preprocessing_version = YOLO_PREPROCESSING_VERSION

    def __init__(self, cfg: YoloConfig | None = None, registry: LabelRegistry | None = None,
                 model_registry: ModelRegistry | None = None) -> None:
        self.cfg = cfg or YoloConfig()
        self.registry = registry or default_registry()
        self.label_map: ModelLabelMap = self.registry.model_map("yolo")
        self.model_registry = model_registry
        self._model: Any = None
        self._names: list[str] = []
        self._status = ArtifactStatus(self.model_id, False, message="not loaded")
        self.model_version = "unloaded"
        self._stride = 32
        self._frame_counter = 0
        self._torch: Any = None

    # ---- loading
    def load(self) -> ArtifactStatus:
        weights = resolve_path(self.cfg.weights_path)
        repo = resolve_path(self.cfg.yolov5_repo_dir)
        if not self.cfg.enabled:
            self._status = ArtifactStatus(self.model_id, False, str(weights), message="disabled by config")
            return self._status
        if not weights.exists():
            self._status = ArtifactStatus(self.model_id, False, str(weights),
                                          message=f"MODEL_UNAVAILABLE: no handwashing YOLOv5 weights at {weights}. "
                                                  "Upstream ships no checkpoint; train with scripts/train_yolo.py.")
            return self._status
        digest = sha256_of(weights)
        trusted = self.cfg.sha256 == digest or (self.model_registry is not None and self.model_registry.is_trusted("yolo", digest))
        if not trusted:
            self._status = ArtifactStatus(self.model_id, False, str(weights), sha256=digest,
                                          message=f"MODEL_UNAVAILABLE: checkpoint sha256 {digest[:12]}… is not registered as trusted in configs/models.yaml "
                                                  "(YOLOv5 .pt files are pickled models; register provenance first)")
            return self._status
        if not (repo / "models" / "common.py").exists():
            self._status = ArtifactStatus(self.model_id, False, str(weights), sha256=digest,
                                          message=f"MODEL_UNAVAILABLE: pinned yolov5 checkout missing at {repo} (run `make yolov5`)")
            return self._status
        try:
            import os

            import torch

            # YOLOv5 checkpoints are full pickled models (hence the hash allow-list above); torch>=2.6
            # refuses them under its weights_only default, so opt out explicitly for this trusted file.
            os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")
            if str(repo) not in sys.path:
                sys.path.insert(0, str(repo))
            from models.common import DetectMultiBackend  # type: ignore[import-not-found]

            model = DetectMultiBackend(str(weights), device=torch.device(self.cfg.device), fp16=False)
            names = model.names
            names_list = [names[i] for i in range(len(names))] if isinstance(names, dict) else list(names)
            unknown = [n for n in names_list if n not in self.label_map.mappings]
            if unknown:
                raise ValueError(f"checkpoint classes {unknown} have no canonical mapping – not a handwashing detector?")
            model.eval()
            stride = int(getattr(model, "stride", 32))
        except Exception as exc:  # noqa: BLE001
            log.error("yolo artifact unusable: %s", exc)
            self._status = ArtifactStatus(self.model_id, False, str(weights), sha256=digest, message=f"MODEL_UNAVAILABLE: {exc}")
            self._model = None
            return self._status
        self._torch = torch
        self._model, self._names, self._stride = model, names_list, stride
        self.model_version = f"{weights.stem}-{digest[:8]}"
        self._status = ArtifactStatus(self.model_id, True, str(weights), self.model_version, digest, "loaded",
                                      YOLO_PREPROCESSING_VERSION, {"classes": names_list, "stride": stride})
        return self._status

    @property
    def available(self) -> bool:
        return self._model is not None

    def status(self) -> ArtifactStatus:
        return self._status

    def should_run(self, frame_id: int) -> bool:
        return self.cfg.every_n_frames <= 1 or frame_id % self.cfg.every_n_frames == 0

    # ---- inference
    def predict(self, frame: FramePacket) -> ModelPrediction:
        ts = frame.capture_ts
        if not self.available:
            return self.unavailable_prediction(ts)
        if frame.image is None:
            return self.no_input_prediction(ts, "frame without image")
        try:
            with Stopwatch() as sw:
                x, ratio, pad = to_model_input(frame.image, self.cfg.img_size)
                tensor = self._torch.from_numpy(x).to(self.cfg.device)
                with self._torch.no_grad():
                    raw = self._model(tensor)
                raw = raw[0] if isinstance(raw, list | tuple) else raw
                raw_np = raw[0].detach().cpu().numpy()
                dets = decode_predictions(raw_np, self.cfg.conf_threshold, self.cfg.iou_threshold)
                dets[:, :4] = scale_boxes(dets[:, :4], ratio, pad, frame.image.shape[:2]) if len(dets) else dets[:, :4]
        except Exception as exc:  # noqa: BLE001
            log.exception("yolo inference failed")
            return self.error_prediction(ts, f"inference error: {exc}")
        return self.prediction_from_detections(dets, ts, frame.frame_id, sw.ms)

    def prediction_from_detections(self, dets: np.ndarray, ts: float, frame_id: int, ms: float) -> ModelPrediction:
        names = self._names or YOLO_NATIVE_NAMES
        dist = detections_to_distribution(dets, names)
        boxes = [{"xyxy": [float(v) for v in d[:4]], "conf": float(d[4]), "class": names[int(d[5])]} for d in dets]
        if len(dets) == 0:
            return self.unknown_prediction(ts, ts, dist, [frame_id], ms, "no detection above confidence threshold")
        best = int(np.argmax(dets[:, 4]))
        native = names[int(dets[best, 5])]
        conf = float(dets[best, 4])
        canonical = self.label_map.canonical_for(native)
        canon: dict[str, float] = {}
        for n, p in dist.items():
            k = self.label_map.canonical_for(n).key
            canon[k] = max(canon.get(k, 0.0), p)
        pred = valid_prediction(self.model_id, self.model_version, ts, ts, [frame_id], native, names.index(native),
                                canonical, dist, canon, conf, ms, calibrated=False)
        pred.extras = {"boxes": boxes, "note": "class values are max detection confidences, not posteriors"}
        return pred
