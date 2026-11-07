"""Backend client used by the pipeline to persist real outputs (httpx, synchronous).

Also provides :class:`InProcessBackend` which drives the FastAPI app through its ASGI
interface without a network socket – used by integration tests and ``--backend inprocess``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from convergent.common.logging import get_logger
from convergent.common.types import (
    CalibrationProfile,
    GestureEvent,
    ModelPrediction,
    RegionEvidence,
)

log = get_logger(__name__)


class BackendError(RuntimeError):
    pass


@dataclass
class ClientStats:
    predictions_sent: int = 0
    events_sent: int = 0
    region_snapshots: int = 0
    failures: int = 0
    last_error: str = ""
    deferred: list[dict[str, Any]] = field(default_factory=list)


class BackendClient:
    def __init__(self, base_url: str, token: str, timeout_s: float = 5.0, transport: httpx.BaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout_s, transport=transport,
                                    headers={"Authorization": f"Bearer {token}"} if token else {})
        self.stats = ClientStats()

    def close(self) -> None:
        tc = getattr(self, "_tc", None)
        if tc is not None:
            tc.__exit__(None, None, None)
        else:
            self._client.close()

    # ---- helpers
    def _req(self, method: str, path: str, json_body: Any = None, retries: int = 2) -> Any:
        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                r = self._client.request(method, path, content=None if json_body is None else json.dumps(json_body, default=str),
                                         headers={"Content-Type": "application/json"} if json_body is not None else None)
                if r.status_code >= 500 and attempt < retries:
                    last = BackendError(f"{method} {path}: {r.status_code} {r.text[:200]}")
                    continue
                if r.status_code >= 400:
                    raise BackendError(f"{method} {path}: {r.status_code} {r.text[:300]}")
                return r.json() if r.content else None
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last = exc
                if attempt >= retries:
                    break
        self.stats.failures += 1
        self.stats.last_error = str(last)
        raise BackendError(str(last))

    # ---- API
    def health(self) -> dict[str, Any]:
        return self._req("GET", "/health")

    def create_session(self, session_id: str, source_id: str, width: int, height: int, target_fps: float, device_id: str | None,
                       processing_config: dict[str, Any], model_versions: dict[str, Any], capture_clock: str,
                       calibration_profile_id: str | None = None, recording_enabled: bool = False, recording_path: str | None = None) -> dict[str, Any]:
        return self._req("POST", "/api/v1/sessions", {
            "session_id": session_id, "source_id": source_id, "width": width, "height": height, "target_fps": target_fps,
            "device_id": device_id, "processing_config": processing_config, "model_versions": model_versions,
            "capture_clock": capture_clock, "calibration_profile_id": calibration_profile_id,
            "recording_enabled": recording_enabled, "recording_path": recording_path})

    def end_session(self, session_id: str, stats: dict[str, Any]) -> dict[str, Any]:
        return self._req("PATCH", f"/api/v1/sessions/{session_id}", {"ended": True, "stats": stats})

    def post_predictions(self, session_id: str, preds: list[ModelPrediction]) -> dict[str, Any]:
        if not preds:
            return {"accepted": 0, "duplicates": 0}
        res = self._req("POST", f"/api/v1/sessions/{session_id}/predictions", {"predictions": [p.model_dump(mode="json") for p in preds]})
        self.stats.predictions_sent += int(res.get("accepted", 0))
        return res

    def post_events(self, session_id: str, events: list[GestureEvent]) -> dict[str, Any]:
        if not events:
            return {"accepted": 0, "duplicates": 0}
        res = self._req("POST", f"/api/v1/sessions/{session_id}/events", {"events": [e.model_dump(mode="json") for e in events]})
        self.stats.events_sent += int(res.get("accepted", 0))
        return res

    def post_regions(self, session_id: str, snapshot_ts: float, evidence: list[RegionEvidence]) -> dict[str, Any]:
        res = self._req("POST", f"/api/v1/sessions/{session_id}/regions", {"snapshot_ts": snapshot_ts, "evidence": [e.model_dump(mode="json") for e in evidence]})
        self.stats.region_snapshots += 1
        return res

    def post_calibration(self, profile: CalibrationProfile, device_id: str | None = None, activate: bool = True) -> dict[str, Any]:
        return self._req("POST", "/api/v1/calibrations", {"profile": profile.model_dump(mode="json"), "device_id": device_id, "activate": activate})

    def get_active_calibration(self) -> CalibrationProfile | None:
        res = self._req("GET", "/api/v1/calibrations/active")
        return None if not res else CalibrationProfile.model_validate(res["profile"])

    def register_model(self, data: dict[str, Any]) -> dict[str, Any]:
        return self._req("POST", "/api/v1/models", data)

    def post_evaluation(self, data: dict[str, Any]) -> dict[str, Any]:
        return self._req("POST", "/api/v1/evaluations", data)

    def get_events(self, session_id: str) -> list[dict[str, Any]]:
        return self._req("GET", f"/api/v1/sessions/{session_id}/events")

    def get_regions(self, session_id: str) -> list[dict[str, Any]]:
        return self._req("GET", f"/api/v1/sessions/{session_id}/regions")


def inprocess_client(token: str, database_url: str) -> tuple[BackendClient, Any]:
    """Backend client bound to an in-process FastAPI app (no sockets). Returns (client, app).

    The Starlette ``TestClient`` is an ``httpx.Client`` subclass that drives the ASGI app
    synchronously, so it can serve as the transport for :class:`BackendClient` directly."""
    from starlette.testclient import TestClient

    from convergent.backend.app import create_app
    from convergent.common.config import Settings

    settings = Settings(api_token=token, database_url=database_url, log_dir="logs")
    app = create_app(settings, database_url)
    tc = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    tc.__enter__()  # runs the lifespan (migrations); closed by client.close()
    client = BackendClient("http://inprocess", token)
    client._client.close()
    client._client = tc  # type: ignore[assignment]
    client._tc = tc  # type: ignore[attr-defined]
    return client, app
