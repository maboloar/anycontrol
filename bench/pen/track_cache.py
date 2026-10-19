"""펜 영상 → 트래커 출력 캐시.

앱과 같은 경로(register_line → ViTracker(Tier 1 sim, 결정적))로 펜을 등록·추적하고, 프레임별 TrackOutput
(상태·포즈·보이는 마스크·정밀 마스크와 그 변환)을 저장한다. 접촉 판정 실험은 이 캐시를 재생하므로
마스크 모델을 다시 돌리지 않는다.

    PYTHONPATH=backend/src:third_party/EfficientTAM backend/.venv/bin/python bench/pen/track_cache.py \
        bench/pen/configs/pen_test.json
"""
from __future__ import annotations

import argparse
import os
import json
import pickle
import sys
import time
import zlib
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def pack(mask: np.ndarray | None):
    if mask is None:
        return None
    m = np.asarray(mask, bool)
    return (m.shape, zlib.compress(np.packbits(m).tobytes(), 3))


def unpack(p) -> np.ndarray | None:
    if p is None:
        return None
    shape, data = p
    n = int(np.prod(shape))
    return np.unpackbits(np.frombuffer(zlib.decompress(data), np.uint8))[:n].reshape(shape).astype(bool)


def roll_matrix(shape, deg: float) -> np.ndarray:
    h, w = shape[:2]
    return cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)


def frames(video: Path, width: int, step: int = 1, rotate: float = 0.0):
    """앱의 VideoFileSource 처럼 가로 width 로 줄인다. step>1 이면 프레임을 건너뛴다(30fps 모사).
    rotate != 0 이면 카메라가 그만큼 옆으로 기울어진 것처럼 영상을 회전한다 (롤 기울기 실험)."""
    cap = cv2.VideoCapture(str(video))
    i = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        if i % step == 0:
            if width and img.shape[1] > width:
                k = width / img.shape[1]
                img = cv2.resize(img, (width, round(img.shape[0] * k)), interpolation=cv2.INTER_AREA)
            if rotate:
                img = cv2.warpAffine(img, roll_matrix(img.shape, rotate), (img.shape[1], img.shape[0]),
                                     borderMode=cv2.BORDER_REPLICATE)
            yield i, img
        i += 1
    cap.release()


def cache_path(cfg: dict, step: int) -> Path:
    rot = cfg.get("rotate", 0)
    trk = tracker_name()
    return HERE / ".cache" / (f"{Path(cfg['video']).stem}_w{cfg.get('width', 1280)}_s{step}{f'_r{rot:g}' if rot else ''}"
                              f"{'' if trk == 'vi' else '_' + trk}.pkl")


def tracker_name() -> str:
    """PEN_TRACKER 환경변수로 평가 등록부의 트래커를 고른다 (기본 vi = 앱 기본 설정, Tier 1 sim)."""
    return os.environ.get("PEN_TRACKER", "vi")


def build(cfg: dict, step: int = 1) -> Path:
    from vision_input.tracking.api import InitPrompt
    from vision_input.tracking.register import register_line
    from vision_input.tracking.segment import default_segmenter
    from vision_input.tracking.vi_tracker import TrackerConfig, ViTracker

    video = (ROOT / cfg["video"]).resolve()
    width = int(cfg.get("width", 1280))
    fps = cv2.VideoCapture(str(video)).get(cv2.CAP_PROP_FPS) or 30.0
    reg_frame = int(cfg["register"]["frame"])
    tip, tail = tuple(cfg["register"]["tip"]), tuple(cfg["register"]["tail"])
    rot = float(cfg.get("rotate", 0))
    if rot:   # 등록 두 점도 같이 돌린다 (첫 프레임 크기 기준)
        h0 = next(frames(video, width, 1))[1]
        R = roll_matrix(h0.shape, rot)
        tip, tail = (tuple(R @ np.array([*pt, 1.0])) for pt in (tip, tail))
    if tracker_name() == "vi":
        tracker = ViTracker(TrackerConfig(tier1=cfg.get("tier1", "sim")))
    else:
        from vision_input.eval.trackers import make_tracker
        tracker = make_tracker(tracker_name())
    rows: dict[int, dict] = {}
    started = False
    t_start = time.perf_counter()
    for i, img in frames(video, width, step, rot):
        t = i / fps
        if i < reg_frame:
            continue
        if not started:
            reg = register_line(img, default_segmenter(), tip, tail)
            out = tracker.add(img, 1, InitPrompt(box=reg.measure.box, mask=reg.mask, kind="pen"))
            started = True
        else:
            out = (tracker.step(img, t) or {}).get(1)
        if out is None:
            continue
        ref = out.refined
        rows[i] = {"state": out.state.value, "box": out.box,
                   "pose": None if out.pose is None else (out.pose.cx, out.pose.cy, out.pose.scale,
                                                          out.pose.angle, out.pose.aspect),
                   "mask": pack(out.mask), "confidence": out.confidence,
                   "refined": None if ref is None else (pack(ref.mask), np.asarray(ref.M, float), float(ref.age))}
        if i % 60 == 0:
            print(f"  frame {i}  state={out.state.value}  {time.perf_counter() - t_start:.1f}s", flush=True)
    close = getattr(tracker, "close", None)
    if close:
        close()
    p = cache_path(cfg, step)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(pickle.dumps({"config": cfg, "fps": fps, "step": step, "rows": rows}))
    print(f"saved {p} ({len(rows)} frames, {p.stat().st_size / 1e6:.1f} MB)")
    return p


def load(cfg: dict, step: int = 1) -> dict:
    p = cache_path(cfg, step)
    if not p.exists():
        build(cfg, step)
    return pickle.loads(p.read_bytes())


def track_output(row: dict):
    """캐시 행 → TrackOutput (PenTracker.update 입력)."""
    from vision_input.tracking.api import Pose, RefinedMask, TrackOutput, TrackState

    ref = row["refined"]
    return TrackOutput(TrackState(row["state"]), row["box"], None if row["pose"] is None else Pose(*row["pose"]),
                       unpack(row["mask"]), row["confidence"], {},
                       None if ref is None else RefinedMask(unpack(ref[0]), ref[1], ref[2]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--step", type=int, default=1, help="프레임 간격 (2 = 60fps 영상을 30fps 로)")
    a = ap.parse_args()
    sys.exit(0 if build(json.loads(Path(a.config).read_text()), a.step) else 1)
