"""평가 하네스.

두 가지 재생 방식
- offline: 모든 프레임을 순서대로 넣는다 (알고리즘 자체의 정확도)
- realtime: 프레임을 fps 에 맞춰 흘리고, 트래커가 바쁘면 그 사이 프레임은 건너뛴다.
  건너뛴 프레임은 직전 출력으로 채점한다 (앱 화면과 같은 조건). 지연이 정확도를 깎는 효과까지 측정.

사용
    python -m vision_input.eval run --tracker csrt --split tune
    python -m vision_input.eval run --tracker csrt --video input.mov --gt annotations.json
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ..tracking.api import InitPrompt, Tracker, TrackOutput, TrackState
from .metrics import SequenceScore, aggregate
from .synth import SynthSequence, SynthSpec, build_suite

TrackerFactory = Callable[[], Tracker]


# ------------------------------------------------------------------ 실제 영상 + 정답 파일
@dataclass
class VideoGT:
    """정답 파일 형식 (JSON)
    {"video": "input.mov", "size": [W, H], "fps": 60, "init": {"frame": 0, "box": [x1,y1,x2,y2]},
     "frames": {"<idx>": {"box": [..] | null, "visible_frac": 0..1, "hand_frac": 0..1,
                          "scale": 1.0, "cx": .., "cy": ..}}}
    frames 에 없는 프레임은 채점하지 않는다 (키프레임만 채점).
    """

    path: Path
    data: dict

    @classmethod
    def load(cls, path: str | Path) -> VideoGT:
        p = Path(path)
        return cls(p, json.loads(p.read_text()))


class VideoSequence:
    def __init__(self, video: str | Path, gt: VideoGT, size: tuple[int, int] | None = (640, 360),
                 max_frames: int | None = None) -> None:
        self.video, self.gt = Path(video), gt
        self.name = f"video/{self.video.stem}"
        cap = cv2.VideoCapture(str(self.video))
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        self.frames = min(n, max_frames) if max_frames else n
        gw, gh = gt.data["size"]
        self.size = size or (gw, gh)
        self.k = self.size[0] / gw
        b = gt.data["init"]["box"]
        self.init_box = tuple(v * self.k for v in b)
        self.init_frame = int(gt.data["init"].get("frame", 0))

    def __len__(self) -> int:
        return self.frames

    def __iter__(self):
        cap = cv2.VideoCapture(str(self.video))
        for i in range(self.frames):
            ok, img = cap.read()
            if not ok:
                break
            if img.shape[1] != self.size[0]:
                img = cv2.resize(img, self.size, interpolation=cv2.INTER_AREA)
            g = self.gt.data["frames"].get(str(i))
            yield img, None if g is None else self._target(g)
        cap.release()

    def _target(self, g: dict) -> dict:
        k = self.k
        box = None if g.get("box") is None else tuple(v * k for v in g["box"])
        amodal = None if g.get("amodal_box") is None else tuple(v * k for v in g["amodal_box"])
        cx = g.get("cx", None)
        cy = g.get("cy", None)
        ref = amodal or box
        if cx is None and ref is not None:
            cx, cy = (ref[0] + ref[2]) / 2 / k, (ref[1] + ref[3]) / 2 / k
        vf = float(g.get("visible_frac", 1.0 if box else 0.0))
        return {
            "target": {"cx": (cx or 0) * k, "cy": (cy or 0) * k, "scale": g.get("scale"), "angle": None,
                       "visible_box": box, "amodal_box": amodal or box, "visible_frac": vf,
                       "in_view": box is not None},
            "distractors": [{"box": tuple(v * k for v in d)} for d in g.get("distractors", [])],
            "hand_frac": float(g.get("hand_frac", 0.0)),
        }


# ------------------------------------------------------------------ 실행
def _init_scale(box) -> float:
    return float(np.sqrt(max(1.0, (box[2] - box[0]) * (box[3] - box[1]))))


def run_synth(factory: TrackerFactory, spec: SynthSpec, pace: str = "offline", hands: bool = False) -> dict:
    """hands=True: 정답 손 마스크를 트래커에 준다 (set_occluders). 손 검출이 완벽할 때의 상한을 본다."""
    seq = SynthSequence(spec)
    frames = ((img, {"target": g.target, "distractors": g.distractors, "hand_frac": g.hand_frac,
                     "hand_mask": g.hand_mask if hands else None})
              for img, g in seq)
    return _run(factory, seq.name, frames, seq.init_box, 0, seq.fps, pace)


def run_video(factory: TrackerFactory, seq: VideoSequence, pace: str = "offline") -> dict:
    return _run(factory, seq.name, iter(seq), seq.init_box, seq.init_frame, seq.fps, pace)


def _run(factory: TrackerFactory, name: str, frames: Iterable, init_box, init_frame: int, fps: float,
         pace: str) -> dict:
    tracker = factory()
    score = SequenceScore(name)
    scale0 = _init_scale(init_box)
    period = 1.0 / fps
    last: dict[int, TrackOutput] = {}
    busy_until = -1.0  # realtime: 가상 시계에서 트래커가 바쁜 시각
    started = False
    for i, (img, gt) in enumerate(frames):
        t = i * period
        ms = 0.0
        if i < init_frame:
            continue
        if not started:
            s = time.perf_counter()
            out = tracker.add(img, 1, InitPrompt(box=tuple(init_box)))
            ms = (time.perf_counter() - s) * 1000
            last = {1: out}
            started = True
            busy_until = t + ms / 1000
        elif pace == "offline" or t >= busy_until:
            occ = gt.get("hand_mask") if gt is not None else None
            if occ is not None and hasattr(tracker, "set_occluders"):
                tracker.set_occluders(occ if occ.any() else None)
            off0 = getattr(tracker, "offloaded_ms", 0.0)
            s = time.perf_counter()
            last = tracker.step(img, t) or last
            # 비동기로 돌 작업(sim 모드 Tier 1)은 hot loop 시간에서 뺀다
            ms = (time.perf_counter() - s) * 1000 - (getattr(tracker, "offloaded_ms", 0.0) - off0)
            busy_until = t + ms / 1000
        if gt is not None and i > init_frame:
            score.add(gt["target"], gt["distractors"], gt["hand_frac"], last.get(1), ms, scale0)
    close = getattr(tracker, "close", None)
    if close:
        close()
    return score.summary()


def run_suite(factory_name: str, specs: list[SynthSpec], pace: str = "offline", workers: int = 4,
              hands: bool = False) -> list[dict]:
    """synthetic 세트를 병렬 실행. 트래커는 이름으로 넘긴다 (프로세스 간 전달)."""
    if pace == "realtime":
        workers = 1  # 병렬로 돌리면 시간 측정이 왜곡된다
    if workers <= 1:
        return [_run_named(factory_name, s, pace, hands) for s in specs]
    n = len(specs)
    with ProcessPoolExecutor(workers) as ex:
        return list(ex.map(_run_named, [factory_name] * n, specs, [pace] * n, [hands] * n))


def _run_named(factory_name: str, spec: SynthSpec, pace: str, hands: bool = False) -> dict:
    from .trackers import make_tracker

    return run_synth(lambda: make_tracker(factory_name), spec, pace, hands)


def report(results: list[dict]) -> str:
    cols = ["success", "robust", "fp_rate", "hijacks", "recovery_frames", "center_err", "scale_err",
            "wobble", "occl_jump", "ms_p95"]
    lines = [f"{'sequence':34s} " + " ".join(f"{c[:9]:>9s}" for c in cols)]
    for r in results:
        lines.append(f"{r['name'][:34]:34s} " + " ".join(_fmt(r.get(c)) for c in cols))
    agg = aggregate(results)
    lines.append("-" * len(lines[0]))
    lines.append(f"{'MEAN':34s} " + " ".join(_fmt(agg.get(c)) for c in cols))
    return "\n".join(lines)


def _fmt(v) -> str:
    if v is None:
        return f"{'-':>9s}"
    if isinstance(v, float) and not v.is_integer():
        return f"{v:9.3f}"
    return f"{int(v):9d}"


__all__ = ["run_suite", "run_synth", "run_video", "VideoGT", "VideoSequence", "report", "build_suite",
           "TrackState"]
