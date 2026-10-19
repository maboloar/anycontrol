"""설정 조합 탐색: 60fps·30fps 모두에서 F1(전체/저신뢰 제외)·허위 구간·단편화를 본다.

    PYTHONPATH=backend/src:third_party/EfficientTAM backend/.venv/bin/python bench/pen/sweep.py bench/pen/configs/pen_test.json

과적합 주의: 영상 1개다. 여기서 고른 값은 새 영상으로 재검증해야 한다.
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import cv2

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import metrics  # noqa: E402
import track_cache  # noqa: E402
from run import ROOT, replay  # noqa: E402

GRID = {
    "floor_shadow": [False, True],
    "floor_drift": ["off", "edge"],
    "floor_shadow_release": [True, False],
    "floor_min_samples": [40, 25],
    "floor_min_frames": [2, 1],
}


def main() -> int:
    cfg = json.loads(Path(sys.argv[1]).read_text())
    ref = json.loads((ROOT / cfg["labels"]).read_text())
    n = int(cv2.VideoCapture(str((ROOT / cfg["video"]).resolve())).get(cv2.CAP_PROP_FRAME_COUNT))
    caches = {s: track_cache.load(cfg, s) for s in (1, 2)}
    rows = []
    keys = list(GRID)
    for vals in itertools.product(*GRID.values()):
        ov = {"contact_method": "floor", **dict(zip(keys, vals, strict=True))}
        if not ov["floor_shadow"] and not ov["floor_shadow_release"]:
            continue  # 그림자를 끄면 release 스위치는 의미 없음
        res = {}
        for s, cache in caches.items():
            pred, _, _, strokes = replay(cfg, cache, ov, n)
            f = metrics.densify(pred, n)
            a, b = metrics.score(f, ref), metrics.score(f, ref, skip_low_conf=True)
            res[s] = (a["f1"], b["f1"], len(a["spurious"]), sum(a["frags"]), a["prec"])
        rows.append((min(res[1][0], res[2][0]), ov, res))
        print(f"{min(res[1][0], res[2][0]):.3f}  " + " ".join(f"{k.replace('floor_', '')}={v}" for k, v in ov.items()
                                                            if k != "contact_method")
              + "  | " + "  ".join(f"s{s}: F1 {r[0]:.3f} excl {r[1]:.3f} prec {r[4]:.3f} spur {r[2]} pieces {r[3]}"
                                   for s, r in res.items()), flush=True)
    rows.sort(key=lambda r: -r[0])
    print("\nbest (min F1 over 60/30fps):")
    for r in rows[:5]:
        print(f"  {r[0]:.3f} {r[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
