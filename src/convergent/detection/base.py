"""Common classifier interface, artifact discovery and safe artifact loading."""

from __future__ import annotations

import hashlib
import io
import pickle
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from convergent.common.logging import get_logger
from convergent.common.types import CanonicalLabel, ModelPrediction, PredictionStatus

log = get_logger(__name__)


class ArtifactError(RuntimeError):
    pass


@dataclass
class ArtifactStatus:
    model_id: str
    available: bool
    path: str | None = None
    version: str = ""
    sha256: str | None = None
    message: str = ""
    preprocessing_version: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id, "available": self.available, "path": self.path,
            "version": self.version, "sha256": self.sha256, "message": self.message,
            "preprocessing_version": self.preprocessing_version, "details": self.details,
        }


def sha256_of(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# --------------------------------------------------------------------------- safe pickle
_ALLOWED_PICKLE_PREFIXES = (
    "sklearn.", "numpy", "scipy.", "copyreg", "builtins", "_codecs", "collections", "joblib.numpy_pickle",
)
_FORBIDDEN_NAMES = {("builtins", "eval"), ("builtins", "exec"), ("builtins", "open"), ("builtins", "__import__"),
                    ("builtins", "compile"), ("builtins", "getattr")}


class RestrictedUnpickler(pickle.Unpickler):
    """Only resolves globals from scikit-learn / NumPy / SciPy.

    The upstream HandHygiene artifacts were statically inspected with ``pickletools`` before
    being allow-listed (see THIRD_PARTY.md). Anything else is refused.
    """

    def find_class(self, module: str, name: str) -> Any:  # noqa: D401
        if (module, name) in _FORBIDDEN_NAMES or not module.startswith(_ALLOWED_PICKLE_PREFIXES):
            raise pickle.UnpicklingError(f"refusing to unpickle global {module}.{name}")
        return super().find_class(module, name)


def inspect_pickle_globals(path: str | Path) -> set[str]:
    import pickletools

    data = Path(path).read_bytes()
    found: set[str] = set()
    pending: list[str] = []
    for op, arg, _pos in pickletools.genops(io.BytesIO(data)):
        if op.name in ("SHORT_BINUNICODE", "BINUNICODE", "UNICODE") and isinstance(arg, str):
            pending.append(arg)
            pending = pending[-2:]
        elif op.name == "STACK_GLOBAL" and len(pending) == 2:
            found.add(f"{pending[0]}.{pending[1]}")
        elif op.name == "GLOBAL" and isinstance(arg, str):
            found.add(arg.replace(" ", "."))
    return found


_DANGEROUS_PREFIXES = ("os", "posix", "nt.", "subprocess", "sys", "socket", "shutil", "importlib", "runpy", "code.",
                       "pty", "ctypes", "pickle", "builtins.eval", "builtins.exec", "builtins.open", "builtins.__import__")


def safe_load_pickle(path: str | Path) -> Any:
    """Static pre-scan (heuristic: string pairs preceding STACK_GLOBAL may be memo references,
    so it only rejects clearly dangerous module names) followed by the exact, enforced check in
    :class:`RestrictedUnpickler.find_class`."""
    globs = inspect_pickle_globals(path)
    bad = [g for g in globs if g.startswith(_DANGEROUS_PREFIXES)]
    if bad:
        raise ArtifactError(f"{path}: pickle references dangerous globals {bad}")
    with open(path, "rb") as f:
        return RestrictedUnpickler(f).load()


def safe_load_joblib_array(path: str | Path) -> Any:
    """Load a joblib-pickled NumPy array (e.g. S-Kia ``X.pkl``) with a restricted unpickler.

    joblib's format embeds raw array bytes, so ``pickletools`` cannot pre-scan it; instead the
    unpickler itself refuses any global outside numpy/joblib's array wrapper."""
    from joblib.numpy_pickle import NumpyUnpickler

    class _Restricted(NumpyUnpickler):  # type: ignore[misc]
        def find_class(self, module: str, name: str) -> Any:
            if (module, name) in _FORBIDDEN_NAMES or not module.startswith(("numpy", "joblib.numpy_pickle", "copyreg", "builtins")):
                raise pickle.UnpicklingError(f"refusing to unpickle global {module}.{name}")
            return super().find_class(module, name)

    import inspect

    kwargs = {"ensure_native_byte_order": True} if "ensure_native_byte_order" in inspect.signature(NumpyUnpickler.__init__).parameters else {}
    with open(path, "rb") as f:
        return _Restricted(str(path), f, **kwargs).load()


# --------------------------------------------------------------------------- interface
class Classifier(ABC):
    """A recognition branch. All branches emit :class:`ModelPrediction` and report
    their artifact status honestly; a branch whose artifact is missing never predicts."""

    model_id: str = "abstract"
    model_version: str = "0"
    preprocessing_version: str = "0"

    @abstractmethod
    def load(self) -> ArtifactStatus: ...

    @property
    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def status(self) -> ArtifactStatus: ...

    def unavailable_prediction(self, ts: float, message: str = "") -> ModelPrediction:
        return ModelPrediction(model_id=self.model_id, model_version=self.model_version, window_start_ts=ts,
                               window_end_ts=ts, status=PredictionStatus.MODEL_UNAVAILABLE,
                               message=message or self.status().message)

    def no_input_prediction(self, ts: float, message: str) -> ModelPrediction:
        return ModelPrediction(model_id=self.model_id, model_version=self.model_version, window_start_ts=ts,
                               window_end_ts=ts, status=PredictionStatus.NO_INPUT, message=message)

    def unknown_prediction(self, start: float, end: float, probs: dict[str, float] | None, frame_ids: list[int],
                           ms: float, message: str, canonical_probs: dict[str, float] | None = None) -> ModelPrediction:
        """The branch saw input but will not name a technique. Pass ``canonical_probs`` so that
        fusion still receives the branch's (uncertain) distribution instead of losing its vote."""
        conf = max(canonical_probs.values()) if canonical_probs else None
        return ModelPrediction(model_id=self.model_id, model_version=self.model_version, window_start_ts=start,
                               window_end_ts=end, frame_ids=frame_ids, probabilities=probs, canonical_probabilities=canonical_probs,
                               confidence=None if conf is None else float(min(max(conf, 0.0), 1.0)),
                               status=PredictionStatus.UNKNOWN, processing_time_ms=ms, message=message)

    def error_prediction(self, ts: float, message: str) -> ModelPrediction:
        return ModelPrediction(model_id=self.model_id, model_version=self.model_version, window_start_ts=ts,
                               window_end_ts=ts, status=PredictionStatus.ERROR, message=message)


class Stopwatch:
    def __enter__(self) -> Stopwatch:
        self._t0 = time.perf_counter()
        self.ms = 0.0
        return self

    def __exit__(self, *exc: Any) -> None:
        self.ms = (time.perf_counter() - self._t0) * 1000.0


def valid_prediction(model_id: str, version: str, start: float, end: float, frame_ids: list[int], native: str,
                     native_index: int | None, canonical: CanonicalLabel, probs: dict[str, float],
                     canonical_probs: dict[str, float], confidence: float, ms: float, calibrated: bool = False) -> ModelPrediction:
    return ModelPrediction(model_id=model_id, model_version=version, window_start_ts=start, window_end_ts=end,
                           frame_ids=frame_ids, native_label=native, native_index=native_index, canonical=canonical,
                           probabilities=probs, canonical_probabilities=canonical_probs,
                           confidence=float(min(max(confidence, 0.0), 1.0)), calibrated=calibrated,
                           processing_time_ms=ms, status=PredictionStatus.VALID)
