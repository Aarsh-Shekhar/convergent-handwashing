"""Recorder class list, METC label parsing and extractor job discovery (no camera, no MediaPipe)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from convergent.detection.pair_training import IGNORE_LABEL, V2_CLASSES
from convergent.vision.recorder import PROMPTS, RECORD_CLASSES

ROOT = Path(__file__).resolve().parents[2]


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_recorder_classes_are_the_model_classes():
    assert list(RECORD_CLASSES) == V2_CLASSES and set(PROMPTS) == set(V2_CLASSES)


def test_metc_labels_map_codes_and_mark_reaction_time(tmp_path):
    ex = _script("extract_landmarks_v2")
    codes = [1] * 40 + [3] * 40 + [0] * 20 + [7] * 10
    labels = [{"is_washing": 1, "code": c} for c in codes] + [{"is_washing": 0, "code": 2}] * 10
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"labels": labels}))
    out = ex.metc_frame_labels(p, src_fps=16.0)
    assert out[0] == "palm_to_palm" and out[60] == "interlaced_fingers" and out[95] == "none" and out[-1] == "none"
    assert out[33] == IGNORE_LABEL and out[46] == IGNORE_LABEL and out[31] == "palm_to_palm" and out[48] == "interlaced_fingers"
    assert out[105] == "none"  # code 0 -> 7 -> not-washing are all "none": no label change, nothing ignored
    assert set(ex.KAGGLE_FOLDERS.values()) | {"none"} == set(V2_CLASSES)


def test_extractor_finds_own_and_metc_clips(tmp_path):
    ex = _script("extract_landmarks_v2")
    own = tmp_path / "own" / "down1"
    own.mkdir(parents=True)
    (own / "round.json").write_text(json.dumps({"view": "down"}))
    for name in ("palm_to_palm", "none", "notaclass"):
        (own / f"{name}.mp4").write_bytes(b"")
    jobs = ex.jobs_own(tmp_path / "own")
    assert sorted(j["label"] for j in jobs) == ["none", "palm_to_palm"] and jobs[0]["group"] == "down1" and jobs[0]["view"] == "down"
    metc = tmp_path / "METC" / "Interface_number_1"
    (metc / "Videos").mkdir(parents=True)
    (metc / "Annotations" / "Annotator_1").mkdir(parents=True)
    for stem in ("2021-06-30_10-28-33-2-1+labots", "2021-06-30_10-40-00-2-2", "2021-06-30_11-00-00-3-1"):
        (metc / "Videos" / f"{stem}.mp4").write_bytes(b"")
        (metc / "Annotations" / "Annotator_1" / f"{stem}.json").write_text("{}")
    mj = ex.jobs_metc(tmp_path / "METC")
    assert len(mj) == 3 and {j["group"] for j in mj} == {"2021-06-30_2", "2021-06-30_3"}
