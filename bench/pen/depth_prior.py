"""실험: 깊이 모델이 알려 준 카메라 롤을 바닥 평면의 좌우 기울기 a 로 고정하면 접촉 판정이 좋아지나? (연구용, 제품 경로 아님)
    PYTHONPATH=backend/src:third_party/EfficientTAM backend/.venv/bin/python bench/pen/depth_prior.py \
        bench/pen/configs/pen_test_roll4.json [--step 2] [--at 300 400 500 600]
1) 영상을 PenTracker(floor) 에 재생하며 지정 프레임에서 깊이 평면의 롤을 잰다 (중앙값).
2) a_fixed = -W·tan(roll_depth) 로 두고 같은 영상을 다시 돌려 F1 을 비교한다.
   (d = k·w + a·x − c 에서 접촉 굵기 w 의 등고선 기울기 = tan(roll) 이므로 a = −W·tan(roll))
"""
from __future__ import annotations
import argparse
import json
import math
import sys
from pathlib import Path
import cv2
import numpy as np
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import metrics  # noqa: E402
import run as bench  # noqa: E402
import track_cache  # noqa: E402
ROOT = HERE.parents[1]
def measure_roll(cfg: dict, cache: dict, at: list[int]) -> list[float]:
    from vision_input import depth_model as dm
    from vision_input.pen import PenConfig, PenTracker
    reg = cfg["register"]
    tip0, tail0 = tuple(reg["tip"]), tuple(reg["tail"])
    rot = float(cfg.get("rotate", 0))
    video = (ROOT / cfg["video"]).resolve()
    if rot:
        first = next(track_cache.frames(video, int(cfg.get("width", 1280)), 1))[1]
        R = track_cache.roll_matrix(first.shape, rot)
        tip0, tail0 = (tuple(R @ np.array([*pt, 1.0])) for pt in (tip0, tail0))
    pen = PenTracker(tip0, tail0, PenConfig(contact_method="floor"))
    model, rolls = dm.DepthModel(), []
    for i, img in track_cache.frames(video, int(cfg.get("width", 1280)), cache["step"], rot):
        row = cache["rows"].get(i)
        if row is None:
            continue
        out = track_cache.track_output(row)
        pen.update(img, out, i / cache["fps"])
        if i in at:
            r = pen.depth_compare(img, out.mask, model)
            if r.get("ready"):
                rolls.append(r["roll_depth_deg"])
    return rolls
def main() -> int:
    from vision_input import depth_model as dm
    from vision_input import pen_floor
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--step", type=int, default=2)
    ap.add_argument("--at", type=int, nargs="*", default=[300, 400, 500, 600])
    a = ap.parse_args()
    if not dm.is_available():
        print("깊이 모델 가중치가 없습니다:", dm.cache_dir())
        return 1
    cfg = json.loads(Path(a.config).read_text())
    ref = json.loads((ROOT / cfg["labels"]).read_text())
    cache = track_cache.load(cfg, a.step)
    n = int(cv2.VideoCapture(str((ROOT / cfg["video"]).resolve())).get(cv2.CAP_PROP_FRAME_COUNT))
    rolls = measure_roll(cfg, cache, a.at)
    if not rolls:
        print("깊이 롤을 잴 수 없었습니다 (바닥 평면 학습 전)")
        return 1
    roll = float(np.median(rolls))
    width = int(cfg.get("width", 1280))
    a_px = -width * math.tan(math.radians(roll))
    print(f"depth roll median {roll:.2f} deg (n={len(rolls)}) -> a_fixed {a_px:.1f} px")
    orig = pen_floor.FloorModel.__init__
    def run(name: str, fixed: float | None) -> None:
        def patched(self, *args, **kw):
            orig(self, *args, **kw)
            self.a_fixed = fixed
        pen_floor.FloorModel.__init__ = patched
        try:
            pred, _, _, _ = bench.replay(cfg, cache, {"contact_method": "floor"}, n)
        finally:
            pen_floor.FloorModel.__init__ = orig
        flags = metrics.densify(pred, n)
        print(metrics.format_result(name, metrics.score(flags, ref), metrics.score(flags, ref, skip_low_conf=True), ref.get("fps", 60)))
    run("plane(touch roll)", None)
    run("plane(a from depth)", a_px)
    run("plane(a=0)", 0.0)
    return 0
if __name__ == "__main__":
    sys.exit(main())
