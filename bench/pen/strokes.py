"""획 모양 벤치: 펜을 PenTracker 에 재생해 만들어진 획(그리기 좌표)을 그림으로 저장하고 '삐침' 지표를 잰다.
    PYTHONPATH=backend/src:third_party/EfficientTAM backend/.venv/bin/python bench/pen/strokes.py \
        bench/pen/configs/pen_test.json [--step 2] [--set key=value ...] [--png out.png]
삐침(flick) = 획의 첫/끝 몇 점이 만드는, 획 본체 방향과 어긋나는 긴 한 걸음. 지표:
  flick_len  획 시작/끝 3걸음 중 가장 긴 걸음 / 획 본체 걸음 중앙값 (1 이면 평범한 걸음)
  flick_off  그 걸음이 획 본체 방향과 이루는 각 (도)
  flicks     (길이 비 > 3 이고 각이 > 45°) 인 시작/끝의 수
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


def collect(cfg: dict, cache: dict, overrides: dict) -> list[list[tuple[float, float]]]:
    from vision_input.pen import PenConfig, PenTracker
    reg = cfg["register"]
    tip0, tail0 = tuple(reg["tip"]), tuple(reg["tail"])
    if cfg.get("rotate"):
        first = next(track_cache.frames((ROOT / cfg["video"]).resolve(), int(cfg.get("width", 1280)), 1))[1]
        R = track_cache.roll_matrix(first.shape, float(cfg["rotate"]))
        tip0, tail0 = (tuple(R @ np.array([*pt, 1.0])) for pt in (tip0, tail0))
    overrides = dict(overrides)
    use_depth = overrides.pop("_depth", False)
    pen = PenTracker(tip0, tail0, PenConfig(**overrides))
    if use_depth:
        from vision_input.depth_model import DepthService

        class _Sync(DepthService):
            def submit(self, bgr, job):  # type: ignore[no-untyped-def]
                if not self.available:
                    return False
                job(self.model.predict(bgr))
                return True
        pen.depth_service = _Sync()
    strokes: list[list[tuple[float, float]]] = []
    for i, img in track_cache.frames((ROOT / cfg["video"]).resolve(), int(cfg.get("width", 1280)), cache["step"], float(cfg.get("rotate", 0))):
        row = cache["rows"].get(i)
        if row is None:
            continue
        pen.update(img, track_cache.track_output(row), i / cache["fps"])
        for ev in pen.state()["events"]:
            if ev["type"] == "up" and ev.get("stroke"):
                strokes.append([tuple(p) for p in ev["stroke"]])
    if pen.cur and len(pen.cur) >= pen.cfg.min_stroke_pts:
        strokes.append(list(pen.cur))
    return strokes


def flick_metrics(strokes: list[list[tuple[float, float]]], k: int = 3) -> dict:
    ends = []
    for s in strokes:
        P = np.array(s, float)
        if len(P) < 8:
            continue
        seg = np.diff(P, axis=0)
        ln = np.linalg.norm(seg, axis=1)
        body = seg[k:-k] if len(seg) > 2 * k + 2 else seg
        med = float(np.median(np.linalg.norm(body, axis=1))) or 1e-9
        main = body.sum(0)
        main = main / (np.linalg.norm(main) + 1e-12)
        for part in (range(0, k), range(len(seg) - k, len(seg))):
            j = max(part, key=lambda q: ln[q])
            cosang = abs(float(seg[j] @ main) / (ln[j] + 1e-12))
            ends.append((ln[j] / med, float(np.degrees(np.arccos(np.clip(cosang, 0, 1))))))
    if not ends:
        return {"ends": 0}
    r = np.array(ends)
    hooks = []
    for s in strokes:
        P = np.array(s, float)
        if len(P) < 14:
            continue
        for a, b in ((P[:4], P[4:13]), (P[-4:][::-1], P[-13:-4][::-1])):
            v1, v2 = a[-1] - a[0], b[-1] - b[0]
            n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
            if n1 > 1e-9 and n2 > 1e-9:
                hooks.append(float(np.degrees(np.arccos(np.clip(v1 @ v2 / (n1 * n2), -1, 1)))))
    hk = {"hook_deg_med": round(float(np.median(hooks)), 1), "hook_deg_max": round(float(np.max(hooks)), 1)} if hooks else {}
    return {**hk, "ends": len(r), "flick_len": round(float(np.median(r[:, 0])), 2), "flick_len_max": round(float(r[:, 0].max()), 2),
            "flick_off_med": round(float(np.median(r[:, 1])), 1), "flicks": int(((r[:, 0] > 3) & (r[:, 1] > 45)).sum())}


def plot(strokes, path: str) -> None:
    pts = np.array([p for s in strokes for p in s], float)
    if len(pts) == 0:
        return
    lo, hi = pts.min(0), pts.max(0)
    scale = 700 / max(float((hi - lo).max()), 1e-9)
    img = np.full((760, 760, 3), 255, np.uint8)
    cols = [(200, 60, 40), (40, 150, 60), (40, 80, 200), (150, 40, 150)]
    for n, s in enumerate(strokes):
        P = ((np.array(s) - lo) * scale + 30).astype(np.int32)
        cv2.polylines(img, [P.reshape(-1, 1, 2)], False, cols[n % 4], 1)
        cv2.circle(img, tuple(P[0]), 5, (0, 160, 0), -1)      # 시작
        cv2.circle(img, tuple(P[-1]), 5, (0, 0, 220), -1)     # 끝
    cv2.imwrite(path, img)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--step", type=int, default=2)
    ap.add_argument("--set", nargs="*", default=[])
    ap.add_argument("--png", default=None)
    a = ap.parse_args()
    cfg = json.loads(Path(a.config).read_text())
    cache = track_cache.load(cfg, a.step)
    extra = {}
    for kv in a.set:
        k, v = kv.split("=", 1)
        extra[k] = json.loads(v) if v[:1] in "-0123456789[{tfn" else v
    strokes = collect(cfg, cache, {"contact_method": "floor", **extra})
    print(len(strokes), "strokes, points", [len(s) for s in strokes], flick_metrics(strokes))
    if a.png:
        plot(strokes, a.png)
    return 0


if __name__ == "__main__":
    sys.exit(main())
