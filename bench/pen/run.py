"""펜 접촉·기록 벤치: 트래커 캐시를 PenTracker 에 재생하고 참조 라벨과 비교한다.

    PYTHONPATH=backend/src:third_party/EfficientTAM backend/.venv/bin/python bench/pen/run.py \
        bench/pen/configs/pen_test.json [--step 2] [--variant legacy floor ...] [--csv out.csv] [--overlay out.mp4]

variant 는 VARIANTS 의 이름 (PenConfig 덮어쓰기). 결과 JSON 은 bench/pen/results/ 에 저장한다.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import metrics  # noqa: E402
import track_cache  # noqa: E402

ROOT = HERE.parents[1]

# 기능별 스위치 (ablation). legacy = 기존 기본값 그대로.
_OFF = {"floor_shadow": False, "floor_memory": False, "floor_drift": "off", "floor_backfill": False}
VARIANTS: dict[str, dict] = {
    "legacy": {"contact_method": "legacy"},
    "legacy+shadow": {"contact_method": "legacy", "shadow_assist": True},
    "floor": {"contact_method": "floor", **_OFF},                                       # F + 상태기계
    "floor+memory": {"contact_method": "floor", **{**_OFF, "floor_memory": True}},
    "floor+memory+shadow": {"contact_method": "floor", **{**_OFF, "floor_memory": True, "floor_shadow": True}},
    "floor+memory+shadow+drift": {"contact_method": "floor", "floor_backfill": False, "floor_drift": "edge"},
    "floor+all": {"contact_method": "floor"},                                           # + 획 소급·끝 정리 (drift off)
    "floor+all+drift": {"contact_method": "floor", "floor_drift": "edge"},
    "floor+all+shadow_release": {"contact_method": "floor", "floor_shadow_release": True},
    "floor+all+noroll": {"contact_method": "floor", "floor_roll": False},              # 앞뒤 직선만 (평면 이전)
    "floor+all+touchroll": {"contact_method": "floor", "floor_depth_roll": False},     # 터치로 배운 롤만 (깊이 모델 끔)
    "floor+all+depth": {"contact_method": "floor", "floor_depth_roll": True, "_depth": True},  # 깊이 모델 롤 (제품 기본, 벤치는 동기 실행)
    "floor+all+precise": {"contact_method": "floor", "precise_width": True},
    "floor+all+horizon": {"contact_method": "floor", "floor_horizon": True},
}


def replay(cfg: dict, cache: dict, overrides: dict, n_frames: int, want_rows: bool = False,
           overlay: str | None = None) -> tuple[dict[int, bool], list[dict], float, list]:
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
    if use_depth:   # 벤치는 영상이 실시간보다 빠르므로 깊이 추론을 같은 스레드에서 끝내고 넘어간다
        from vision_input.depth_model import DepthService

        class _Sync(DepthService):
            def submit(self, bgr, job):  # type: ignore[no-untyped-def]
                if not self.available:
                    return False
                job(self.model.predict(bgr))
                return True
        pen.depth_service = _Sync()
    fps = cache["fps"]
    pred: dict[int, bool] = {}
    rows: list[dict] = []
    ms: list[float] = []
    writer = None
    strokes_px: list = []
    video = (ROOT / cfg["video"]).resolve()
    for i, img in track_cache.frames(video, int(cfg.get("width", 1280)), cache["step"], float(cfg.get("rotate", 0))):
        row = cache["rows"].get(i)
        if row is None:
            pred[i] = False
            continue
        out = track_cache.track_output(row)
        s = time.perf_counter()
        pen.update(img, out, i / fps)
        ms.append((time.perf_counter() - s) * 1000)
        st = pen.state()
        pred[i] = pen.pressed
        for ev in st["events"]:
            if ev["type"] == "up" and ev.get("stroke"):
                strokes_px.append(pen.last_stroke_span)
        if want_rows:
            dbg = st.get("floor") or {}
            rows.append({"frame": i, "contact": int(pred[i]), "tip_x": None if pen.tip is None else pen.tip[0],
                         "tip_y": None if pen.tip is None else pen.tip[1], "width": pen.width,
                         "height": st["height"], "uncertain": int(pen.uncertain), **{f"f_{k}": v for k, v in dbg.items()}})
        if overlay:
            vis = _draw(img, pen, out, st)
            if writer is None:
                writer = cv2.VideoWriter(overlay, cv2.VideoWriter_fourcc(*"mp4v"), fps / cache["step"],
                                         (vis.shape[1] // 2, vis.shape[0] // 2))
            writer.write(cv2.resize(vis, (vis.shape[1] // 2, vis.shape[0] // 2)))
    if writer:
        writer.release()
    if pen.cur and len(pen.cur_t) == len(pen.cur):
        strokes_px.append((pen.cur_t[0], pen.cur_t[-1]))
    return pred, rows, float(np.percentile(ms, 95)) if ms else 0.0, [s for s in strokes_px if s]


def _draw(img, pen, out, st):
    vis = img.copy()
    if out.mask is not None:
        cnt, _ = cv2.findContours(out.mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(vis, cnt, -1, (0, 255, 0), 1)
    f = st.get("floor") or {}
    if f.get("edge") is not None:
        a, b = f["edge"]
        cv2.line(vis, (0, int(b)), (vis.shape[1], int(a * vis.shape[1] + b)), (255, 0, 255), 1)
    on = pen.contact and not pen.uncertain
    if pen.tip is not None:
        t = tuple(int(v) for v in pen.tip)
        cv2.circle(vis, t, 9 if on else 6, (0, 0, 255) if on else (255, 200, 0), -1 if on else 2)
    cv2.rectangle(vis, (0, 0), (vis.shape[1], 44), (0, 0, 0), -1)
    txt = f"{'CONTACT' if on else 'air'}  h={f.get('h_s')}  base={f.get('base')}  sh={f.get('shadow')}  {f.get('reason', '')}"
    cv2.putText(vis, txt, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, .7, (255, 255, 255), 2)
    return vis


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--step", type=int, default=1)
    ap.add_argument("--variant", nargs="*", default=None)
    ap.add_argument("--set", nargs="*", default=[], help="추가 덮어쓰기 key=value (모든 variant 에 적용)")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--overlay", default=None)
    a = ap.parse_args()
    cfg = json.loads(Path(a.config).read_text())
    ref = json.loads((ROOT / cfg["labels"]).read_text())
    cache = track_cache.load(cfg, a.step)
    n = int(cv2.VideoCapture(str((ROOT / cfg["video"]).resolve())).get(cv2.CAP_PROP_FRAME_COUNT))
    extra = {}
    for kv in a.set:
        k, v = kv.split("=", 1)
        extra[k] = json.loads(v) if v[:1] in "-0123456789[{tfn" else v
    names = a.variant or list(VARIANTS)
    results = {}
    for name in names:
        ov = {**VARIANTS[name], **extra}
        pred, rows, p95, strokes = replay(cfg, cache, ov, n, want_rows=bool(a.csv),
                                          overlay=a.overlay if len(names) == 1 else None)
        flags = metrics.densify(pred, n)
        full, excl = metrics.score(flags, ref), metrics.score(flags, ref, skip_low_conf=True)
        # 기록: 실제로 저장된 획이 덮는 프레임 (소급·끝 정리 반영)
        fps = cache["fps"]
        sflags = [0] * n
        for t0, t1 in strokes:
            for i in range(int(round(t0 * fps)), min(n, int(round(t1 * fps)) + 1)):
                sflags[i] = 1
        sres = metrics.score(sflags, ref)
        print(metrics.format_result(name, full, excl, ref.get("fps", 60)))
        print(f"    strokes {len(strokes)}: acc {sres['acc']:.3f} prec {sres['prec']:.3f} rec {sres['rec']:.3f} "
              f"F1 {sres['f1']:.3f} spans {[ (round(a * fps), round(b * fps)) for a, b in strokes]}")
        print(f"    pen.update p95 {p95:.2f} ms")
        results[name] = {"overrides": ov, "full": full, "excl_low_conf": excl, "strokes": sres,
                         "update_ms_p95": p95}
        if a.csv and rows:
            with open(a.csv, "w", newline="") as fh:
                keys = sorted({k for r in rows for k in r}, key=lambda k: (k != "frame", k))
                w = csv.DictWriter(fh, fieldnames=keys)
                w.writeheader()
                w.writerows(rows)
    out = HERE / "results" / f"{Path(cfg['video']).stem}_s{a.step}.json"
    out.parent.mkdir(exist_ok=True)
    prev = json.loads(out.read_text()) if out.exists() else {}
    prev.update(results)
    out.write_text(json.dumps(prev, indent=1, default=lambda o: o if not isinstance(o, tuple) else list(o)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
