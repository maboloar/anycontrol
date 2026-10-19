"""정지 떨림 벤치.

    PYTHONPATH=backend/src:third_party/EfficientTAM backend/.venv/bin/python bench/still/run.py \
        [--scene synthetic-still synthetic-move real-still] [--variant baseline still_lock ...] [--csv out.csv]

variant 는 VARIANTS 에 정의한 TrackerConfig 덮어쓰기. 결과: 표 + bench/still/results/<variant>.json
Tier 1 은 sim 모드(실측 지연만큼 늦게 반영, 결정적)로 돌려 앱의 비동기 경로와 같은 효과를 낸다.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import metrics  # noqa: E402
import scenarios  # noqa: E402

# 단계별 기능 스위치 (ablation). 새 기능은 여기에 이름을 더한다.
from vision_input.tracking.still import StillConfig  # noqa: E402

VARIANTS: dict[str, dict] = {
    "baseline": {"still": StillConfig(enabled=False)},      # 정지 잠금 이전과 같은 동작
    "still_lock": {},                                       # 현재 기본값 (정지 잠금 켬)
    "no_refresh": {"_refresh": False},               # 원인 분리용
    "tier0_only": {"tier1": "off"},                  # Tier 1·재분할 없이 (점 추적 + 색 영역만)
}
DOWN = 320


def make_tracker(overrides: dict):
    from vision_input.tracking.vi_tracker import TrackerConfig, ViTracker

    overrides = dict(overrides)
    refresh = overrides.pop("_refresh", True)       # 2초마다 하는 재분할 보정 (bench 전용 스위치)
    tr = ViTracker(dataclasses.replace(TrackerConfig(tier1="sim"), **overrides))
    tr.refresh_enabled = bool(refresh) and tr.refresh_enabled
    return tr


def run_scene(scene: scenarios.Scene, overrides: dict, dump: list | None = None) -> tuple[list[dict], dict]:
    from vision_input.tracking.api import InitPrompt
    from vision_input.tracking.desk import mask_foot

    from vision_input.io.mouse import MouseController, MouseSettings
    from vision_input.io.sink import VirtualSink

    sink = VirtualSink()
    mouse = MouseController(sink)
    mouse.configure(MouseSettings(mode="object", object_id=1, hand_clicks=False, object_tap=False))
    H, W = scene.frames[0].shape[:2]
    tr = make_tracker(overrides)
    series: list[dict] = []
    prev: np.ndarray | None = None
    ms: list[float] = []
    size = 1.0
    k = scenarios.WIDTH / DOWN
    for i, img in enumerate(scene.frames):
        t = i / scene.fps
        s = time.perf_counter()
        if i == 0:
            out = tr.add(img, 1, InitPrompt(box=scene.box))
            size = tr.tracks[1].size0 / tr.tracks[1].k
        else:
            out = tr.step(img, t)[1]
        ms.append((time.perf_counter() - s) * 1000 - (0.0))
        row: dict = {"t": t, "visible": out.state.visible, "cx": None, "cy": None, "ls": None, "th": None,
                     "rx": None, "ry": None, "mcx": None, "mcy": None, "iou": None, "area": None,
                     "fx": None, "fy": None, "curx": None, "cury": None, "state": out.state.value}
        if out.pose is not None:
            row.update(cx=out.pose.cx, cy=out.pose.cy, ls=float(np.log(out.pose.scale)), th=out.pose.angle,
                       rx=out.debug.get("raw_cx"), ry=out.debug.get("raw_cy"))
        if out.state.visible and out.mask is not None:
            m = cv2.resize(out.mask.astype(np.uint8), (DOWN, round(out.mask.shape[0] / k)), interpolation=cv2.INTER_NEAREST) > 0
            if m.any():
                ys, xs = np.nonzero(m)
                row.update(mcx=float(xs.mean() * k), mcy=float(ys.mean() * k), area=float(m.mean()))
                f = mask_foot(m)
                if f is not None:
                    row.update(fx=f[0] * k, fy=f[1] * k)
                if prev is not None and prev.shape == m.shape:
                    row["iou"] = float((m & prev).sum() / max((m | prev).sum(), 1))
                prev = m
        mouse.update(t, None, (out.pose.cx / W, out.pose.cy / H) if out.pose is not None else None, out.state.visible,
                     False, None, obj_scale=float(out.pose.scale) if out.pose is not None else 1.0)
        row.update(curx=sink.x, cury=sink.y)
        series.append(row)
    close = getattr(tr, "close", None)
    if close:
        close()
    if dump is not None:
        dump.extend({"scene": scene.name, **r} for r in series)
    if scene.onset is not None:
        res = metrics.still_summary(series[:scene.onset], size, scene.warmup)
        res.update(metrics.response_delay(series, scene.onset, scene.shift, scene.moved))
    else:
        res = metrics.still_summary(series, size, scene.warmup, scene.truth)
    res["ms_p50"] = round(float(np.percentile(ms[1:], 50)), 2)
    res["ms_p95"] = round(float(np.percentile(ms[1:], 95)), 2)
    res["object_px"] = round(size, 1)
    return series, res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", nargs="*", default=scenarios.SCENES)
    ap.add_argument("--variant", nargs="*", default=["baseline"])
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--csv", default=None, help="프레임별 시계열 저장 (variant 하나일 때)")
    ap.add_argument("--cfg", default=None, help='임시 덮어쓰기 JSON, 예: \'{"still_px": 0.5}\'')
    a = ap.parse_args()
    extra = json.loads(a.cfg) if a.cfg else {}
    allres: dict[str, dict] = {}
    dump: list = []
    for vname in a.variant:
        ov = {**VARIANTS[vname], **extra}
        for sname in a.scene:
            scene = scenarios.build(sname, a.seconds)
            _, res = run_scene(scene, ov, dump if a.csv else None)
            allres.setdefault(vname, {})[sname] = res
        out = HERE / "results" / f"{vname}.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps({"overrides": ov, "scenes": allres[vname]}, indent=1, default=lambda o: dataclasses.asdict(o)))
    for sname in a.scene:
        print(f"== {sname}")
        print(metrics.format_table({v: allres[v][sname] for v in a.variant}))
    if a.csv and dump:
        with open(a.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(dump[0].keys()))
            w.writeheader()
            w.writerows(dump)
    return 0


if __name__ == "__main__":
    sys.exit(main())
