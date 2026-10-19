"""깊이 모델(Depth Anything V2 Small, Core ML) 평면 vs 펜 접촉으로 배운 바닥 평면 (개발자 실험).

    PYTHONPATH=backend/src:third_party/EfficientTAM backend/.venv/bin/python bench/pen/depth_compare.py \
        bench/pen/configs/pen_test.json [--step 2] [--at 300 400 500] [--save out.jpg]

가중치가 없으면 먼저 개발자 모드의 [깊이 모델 내려받기] 를 누르거나 depth_model.Downloader().start() 를 부른다.
영상을 PenTracker(floor) 에 재생해 바닥 평면이 학습되면, 지정한 프레임에서 두 평면의 기울기를 비교한다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import track_cache  # noqa: E402

ROOT = HERE.parents[1]


def decode(uri: str) -> np.ndarray:
    import base64
    return cv2.imdecode(np.frombuffer(base64.b64decode(uri.split(",", 1)[1]), np.uint8), cv2.IMREAD_UNCHANGED)


def main() -> int:
    from vision_input import depth_model as dm
    from vision_input.pen import PenConfig, PenTracker

    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--step", type=int, default=2)
    ap.add_argument("--at", type=int, nargs="*", default=[300, 400, 500])
    ap.add_argument("--save", default=None)
    a = ap.parse_args()
    if not dm.is_available():
        print("깊이 모델 가중치가 없습니다:", dm.cache_dir())
        return 1
    cfg = json.loads(Path(a.config).read_text())
    cache = track_cache.load(cfg, a.step)
    reg = cfg["register"]
    tip0, tail0 = tuple(reg["tip"]), tuple(reg["tail"])
    rot = float(cfg.get("rotate", 0))
    video = (ROOT / cfg["video"]).resolve()
    if rot:
        first = next(track_cache.frames(video, int(cfg.get("width", 1280)), 1))[1]
        R = track_cache.roll_matrix(first.shape, rot)
        tip0, tail0 = (tuple(R @ np.array([*pt, 1.0])) for pt in (tip0, tail0))
    pen = PenTracker(tip0, tail0, PenConfig(contact_method="floor"))
    model = dm.DepthModel()
    rows, tiles = [], []
    for i, img in track_cache.frames(video, int(cfg.get("width", 1280)), cache["step"], rot):
        row = cache["rows"].get(i)
        if row is None:
            continue
        out = track_cache.track_output(row)
        pen.update(img, out, i / cache["fps"])
        if i in a.at:
            r = pen.depth_compare(img, out.mask, model)
            if not r.get("ready"):
                print(i, "not ready:", r.get("reason"))
                continue
            keys = ("corr", "angle_deg", "roll_depth_deg", "roll_touch_deg", "plane_rms", "inlier_frac", "ms")
            rows.append({"frame": i, **{k: r[k] for k in keys}})
            print(i, {k: r[k] for k in keys})
            tiles.append(np.hstack([decode(r[k]) if decode(r[k]).ndim == 3 else cv2.cvtColor(decode(r[k]), cv2.COLOR_GRAY2BGR)
                                    for k in ("depth_image", "fit_image", "touch_image")]))
    if rows:
        print("median |roll_depth - roll_touch| = %.2f deg, median corr %.3f" % (
            float(np.median([abs(r["roll_depth_deg"] - r["roll_touch_deg"]) for r in rows])),
            float(np.median([r["corr"] for r in rows]))))
    if a.save and tiles:
        cv2.imwrite(a.save, np.vstack(tiles))
    return 0


if __name__ == "__main__":
    sys.exit(main())
