"""Model artifact registry (``configs/models.yaml``): expected artifacts, provenance, trusted hashes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from convergent.common.config import resolve_path
from convergent.detection.base import sha256_of


@dataclass
class ArtifactSpec:
    model_key: str
    name: str
    path: str
    kind: str
    upstream: str = ""
    upstream_sha256: str | None = None
    trusted_sha256: list[str] = field(default_factory=list)
    preprocessing_version: str = ""
    label_map: str = ""
    notes: str = ""
    required: bool = False

    def discover(self) -> dict[str, Any]:
        p = resolve_path(self.path)
        exists = p.exists()
        digest = None
        if exists and p.is_file():
            digest = sha256_of(p)
        elif exists and p.is_dir():
            mp = p / "model.pt"
            digest = sha256_of(mp) if mp.exists() else None
        return {
            "model_key": self.model_key, "name": self.name, "path": str(p), "kind": self.kind, "exists": exists,
            "sha256": digest, "trusted": bool(digest and (digest in self.trusted_sha256 or digest == self.upstream_sha256)),
            "upstream": self.upstream, "preprocessing_version": self.preprocessing_version, "notes": self.notes,
        }


class ModelRegistry:
    def __init__(self, specs: list[ArtifactSpec]) -> None:
        self.specs = specs

    @classmethod
    def load(cls, path: str | Path = "configs/models.yaml") -> ModelRegistry:
        with open(resolve_path(path), encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        specs = []
        for key, entry in (data.get("artifacts") or {}).items():
            specs.append(ArtifactSpec(model_key=key, **entry))
        return cls(specs)

    def is_trusted(self, model_key: str, digest: str) -> bool:
        return any(s.model_key == model_key and (digest in s.trusted_sha256 or digest == s.upstream_sha256) for s in self.specs)

    def discover_all(self) -> list[dict[str, Any]]:
        return [s.discover() for s in self.specs]

    def for_key(self, key: str) -> ArtifactSpec | None:
        return next((s for s in self.specs if s.model_key == key), None)
