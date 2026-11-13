"""Window-level accuracy of a temporal_v2 artifact on own recorded rounds (diagnostic).

    python scripts/eval_own_rounds.py --model runs/v2/ft3_a --rounds down1,down2,down3
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from convergent.detection.lstm_model import TemporalArtifact
from convergent.detection.pair_training import (
    V2_CLASSES,
    _features,
    _symmetric_probs,
    build_window_index,
    load_raw_recordings,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", default="data/landmarks_v2/own")
    ap.add_argument("--rounds", required=True)
    a = ap.parse_args()
    art = TemporalArtifact.load(Path(a.model))
    recs = [r for r in load_raw_recordings(Path(a.data)) if r.group in a.rounds.split(",")]
    for rnd in a.rounds.split(","):
        rr = [r for r in recs if r.group == rnd]
        wi = build_window_index(rr, art.meta.window_frames, 3, art.meta.min_present_frames or 8, V2_CLASSES, hold_frames=art.meta.hold_frames or 0)
        sel = np.arange(len(wi))
        p = _symmetric_probs(art.model.eval(), _features(wi, sel, art.meta.window_frames), art.scaler, "cpu").argmax(1)
        rec = {c: round(float((p[wi.y == i] == i).mean()), 2) for i, c in enumerate(V2_CLASSES) if (wi.y == i).any()}
        print(f"{rnd}: acc {float((p == wi.y).mean()):.3f}  {rec}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
