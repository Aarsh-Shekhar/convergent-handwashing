"""Canonical label registry.

The canonical label space is defined in ``configs/labels.yaml`` so that adding a technique or
re-mapping a model class never requires a code change or retraining of other components.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from convergent.common.config import PipelineConfig, resolve_path
from convergent.common.types import CanonicalLabel, HandSide

# Stable constants for the six core techniques (used in code paths such as region mapping).
PALM_TO_PALM = "palm_to_palm"
BACK_OF_HAND = "back_of_hand"
INTERLACED_FINGERS = "interlaced_fingers"
BACKS_OF_FINGERS = "backs_of_fingers"
THUMB_RUBBING = "thumb_rubbing"
FINGERTIP_RUBBING = "fingertip_rubbing"
WRIST_RUBBING = "wrist_rubbing"  # extension (WHO step 7): scored, but no region evidence
NONE = "none"
UNKNOWN = "unknown"
TRANSITION = "transition"
CORE_TECHNIQUES: tuple[str, ...] = (
    PALM_TO_PALM, BACK_OF_HAND, INTERLACED_FINGERS, BACKS_OF_FINGERS, THUMB_RUBBING, FINGERTIP_RUBBING,
)
# The seven techniques the wash score times, in suggested (WHO) order.
SCORED_TECHNIQUES: tuple[str, ...] = CORE_TECHNIQUES + (WRIST_RUBBING,)

_SIDE = {"left": HandSide.LEFT, "right": HandSide.RIGHT, "both": HandSide.BOTH,
         "unresolved": HandSide.UNRESOLVED, "unknown": HandSide.UNKNOWN}


class LabelMappingError(ValueError):
    pass


@dataclass(frozen=True)
class NativeMapping:
    native: str
    canonical: CanonicalLabel
    note: str = ""


@dataclass
class ModelLabelMap:
    model_key: str
    native_order: list[str]
    mappings: dict[str, NativeMapping]

    def canonical_for(self, native: str) -> CanonicalLabel:
        m = self.mappings.get(str(native))
        if m is None:
            raise LabelMappingError(f"{self.model_key}: native label {native!r} has no canonical mapping")
        return m.canonical

    def canonical_for_index(self, idx: int) -> CanonicalLabel:
        if idx < 0 or idx >= len(self.native_order):
            raise LabelMappingError(f"{self.model_key}: native index {idx} out of range")
        return self.canonical_for(self.native_order[idx])

    def native_for_index(self, idx: int) -> str:
        if idx < 0 or idx >= len(self.native_order):
            raise LabelMappingError(f"{self.model_key}: native index {idx} out of range")
        return self.native_order[idx]


@dataclass
class LabelRegistry:
    core: list[str]
    special: list[str]
    extensions: list[str]
    sided: set[str]
    symmetric: set[str]
    models: dict[str, ModelLabelMap]
    version: int = 1
    side_resolution: dict[str, HandSide] = field(default_factory=dict)

    # ---- construction
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LabelRegistry:
        tech = data.get("techniques", {})
        core = list(tech.get("core", []))
        special = list(tech.get("special", []))
        ext = list(tech.get("extensions", []))
        all_known = set(core) | set(special) | set(ext)
        if len(all_known) != len(core) + len(special) + len(ext):
            raise LabelMappingError("duplicate technique names in labels config")
        side_res = {k: _SIDE[v] for k, v in (data.get("side_resolution") or {}).items()}
        for k, v in side_res.items():
            if v not in (HandSide.LEFT, HandSide.RIGHT):
                raise LabelMappingError(f"side_resolution[{k}] must be left or right")
        models: dict[str, ModelLabelMap] = {}
        for key, spec in (data.get("models") or {}).items():
            order = [str(x) for x in spec.get("native_order", [])]
            maps: dict[str, NativeMapping] = {}
            for native, entry in (spec.get("map") or {}).items():
                native = str(native)
                technique = entry["technique"]
                if technique not in all_known:
                    raise LabelMappingError(f"{key}:{native} maps to unknown technique {technique!r}")
                side = _SIDE[str(entry.get("side", "unknown"))]
                resolved = side != HandSide.UNRESOLVED
                override = side_res.get(f"{key}:{native}")
                if override is not None:
                    side, resolved = override, True
                maps[native] = NativeMapping(native, CanonicalLabel(technique=technique, side=side, resolved=resolved), str(entry.get("note", "")))
            missing = [n for n in order if n not in maps]
            if missing:
                raise LabelMappingError(f"{key}: native labels without mapping: {missing}")
            models[key] = ModelLabelMap(key, order, maps)
        return cls(core=core, special=special, extensions=ext, sided=set(data.get("sided_techniques", [])),
                   symmetric=set(data.get("symmetric_techniques", [])), models=models,
                   version=int(data.get("version", 1)), side_resolution=side_res)

    @classmethod
    def load(cls, path: str | Path | None = None) -> LabelRegistry:
        p = resolve_path(path or PipelineConfig().labels_path)
        with open(p, encoding="utf-8") as f:
            return cls.from_dict(yaml.safe_load(f))

    # ---- queries
    @property
    def techniques(self) -> list[str]:
        return self.core + self.extensions

    def is_core(self, technique: str) -> bool:
        return technique in self.core

    def is_known(self, technique: str) -> bool:
        return technique in self.core or technique in self.special or technique in self.extensions

    def is_sided(self, technique: str) -> bool:
        return technique in self.sided

    def model_map(self, model_key: str) -> ModelLabelMap:
        try:
            return self.models[model_key]
        except KeyError as exc:
            raise LabelMappingError(f"no label map for model {model_key!r}") from exc

    def canonical_keys(self) -> list[str]:
        """All canonical keys that can appear in a fused distribution.

        Sided techniques appear as ``left_<t>``/``right_<t>`` plus the side-less ``<t>`` (used
        when the side is unknown/unresolved); symmetric ones as ``<t>``; plus ``none``."""
        keys: list[str] = []
        for t in self.techniques:
            keys.append(t)
            if t in self.sided:
                keys.extend([f"left_{t}", f"right_{t}"])
        keys.append(NONE)
        return keys

    @staticmethod
    def key_for(label: CanonicalLabel) -> str:
        return label.key

    @staticmethod
    def technique_of_key(key: str) -> str:
        for prefix in ("left_", "right_"):
            if key.startswith(prefix):
                return key[len(prefix):]
        return key

    @staticmethod
    def side_of_key(key: str) -> HandSide:
        if key.startswith("left_"):
            return HandSide.LEFT
        if key.startswith("right_"):
            return HandSide.RIGHT
        return HandSide.UNKNOWN


_DEFAULT: LabelRegistry | None = None


def default_registry() -> LabelRegistry:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = LabelRegistry.load()
    return _DEFAULT
