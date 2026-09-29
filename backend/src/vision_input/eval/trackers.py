"""하네스용 트래커 등록부.

기준선
- static: 등록 박스를 그대로 유지 (지표가 제대로 동작하는지 보는 하한선)
- csrt:   OpenCV CSRT 박스 트래커 (고전 기준선)
이후 task 에서 본 트래커("vi")를 여기에 등록한다.
"""

from __future__ import annotations

from collections.abc import Callable

import cv2
import numpy as np

from ..tracking.api import Box, InitPrompt, Pose, Tracker, TrackOutput, TrackState, mask_to_box

_REGISTRY: dict[str, Callable[[], Tracker]] = {}


def register(name: str) -> Callable[[Callable[[], Tracker]], Callable[[], Tracker]]:
    def deco(fn: Callable[[], Tracker]) -> Callable[[], Tracker]:
        _REGISTRY[name] = fn
        return fn

    return deco


def make_tracker(name: str) -> Tracker:
    if name not in _REGISTRY:
        _load_optional()
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise SystemExit(f"unknown tracker {name!r}; available: {sorted(_REGISTRY)}") from None


def available() -> list[str]:
    _load_optional()
    return sorted(_REGISTRY)


def _load_optional() -> None:
    # 본 트래커는 무거운 의존성이 있어 필요할 때만 불러온다
    try:
        from ..tracking import vi_tracker  # noqa: F401
    except ImportError:
        pass


def _prompt_box(prompt: InitPrompt) -> Box:
    if prompt.mask is not None:
        b = mask_to_box(prompt.mask)
        if b is not None:
            return b
    if prompt.box is None:
        raise ValueError("box or mask required")
    return prompt.box


def _pose_from_box(b: Box, b0: Box) -> Pose:
    s0 = np.sqrt((b0[2] - b0[0]) * (b0[3] - b0[1]))
    s = np.sqrt(max(1.0, (b[2] - b[0]) * (b[3] - b[1])))
    return Pose((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, float(s / s0))


class StaticTracker:
    name = "static"

    def __init__(self) -> None:
        self.boxes: dict[int, Box] = {}

    def add(self, frame: np.ndarray, obj_id: int, prompt: InitPrompt) -> TrackOutput:
        b = _prompt_box(prompt)
        self.boxes[obj_id] = b
        return TrackOutput(TrackState.TRACKING, b, _pose_from_box(b, b), confidence=1.0)

    def step(self, frame: np.ndarray, t: float) -> dict[int, TrackOutput]:
        return {k: TrackOutput(TrackState.TRACKING, b, _pose_from_box(b, b), confidence=1.0)
                for k, b in self.boxes.items()}

    def remove(self, obj_id: int) -> None:
        self.boxes.pop(obj_id, None)


class CSRTTracker:
    name = "csrt"

    def __init__(self) -> None:
        self.trk: dict[int, tuple[cv2.Tracker, Box]] = {}

    def add(self, frame: np.ndarray, obj_id: int, prompt: InitPrompt) -> TrackOutput:
        b = _prompt_box(prompt)
        t = cv2.TrackerCSRT_create()
        t.init(frame, (int(b[0]), int(b[1]), int(b[2] - b[0]), int(b[3] - b[1])))
        self.trk[obj_id] = (t, b)
        return TrackOutput(TrackState.TRACKING, b, _pose_from_box(b, b), confidence=1.0)

    def step(self, frame: np.ndarray, t: float) -> dict[int, TrackOutput]:
        out = {}
        for k, (trk, b0) in self.trk.items():
            ok, (x, y, w, h) = trk.update(frame)
            if ok and w > 0 and h > 0:
                b = (float(x), float(y), float(x + w), float(y + h))
                out[k] = TrackOutput(TrackState.TRACKING, b, _pose_from_box(b, b0), confidence=1.0)
            else:
                out[k] = TrackOutput(TrackState.LOST)
        return out

    def remove(self, obj_id: int) -> None:
        self.trk.pop(obj_id, None)


register("static")(StaticTracker)
register("csrt")(CSRTTracker)


def _vi() -> Tracker:
    """본 트래커. 평가에서는 Tier 1 을 sim 모드로 (실측 지연만큼 늦게 반영, 결정적)."""
    from ..tracking.vi_tracker import TrackerConfig, ViTracker

    return ViTracker(TrackerConfig(tier1="sim"))


def _vi0() -> Tracker:
    """Tier 0 만 (비교용)."""
    from ..tracking.vi_tracker import TrackerConfig, ViTracker

    return ViTracker(TrackerConfig(tier1="off"))


def _vi_async() -> Tracker:
    """실시간과 같은 비동기 Tier 1 (--pace realtime 과 함께)."""
    from ..tracking.vi_tracker import TrackerConfig, ViTracker

    return ViTracker(TrackerConfig(tier1="async"))


register("vi")(_vi)
register("vi0")(_vi0)
register("vi_async")(_vi_async)


def _vi_cfg(**kw):  # type: ignore[no-untyped-def]
    def f():  # type: ignore[no-untyped-def]
        from ..tracking.vi_tracker import TrackerConfig, ViTracker

        return ViTracker(TrackerConfig(tier1="sim", **kw))
    return f


def _reacq(**kw):  # type: ignore[no-untyped-def]
    from ..tracking.reacquire import ReacquireConfig
    return ReacquireConfig(**kw)


# 모양 기억 재획득 비교용 (vi 는 기본 설정 그대로)
register("vi_noreacq")(lambda: _vi_cfg(reacq=_reacq(enabled=False))())
register("vi_reacq")(lambda: _vi_cfg(reacq=_reacq(enabled=True))())
