"""수평 RGB 카메라용 상대 이동: 좌우 위치 + 크기로 추정한 앞뒤 거리."""

from __future__ import annotations

import math
import numpy as np

from ..hands.detector import Hand
from ..tracking.smooth import OneEuro
from .touchpad import TouchSurface


def palm_scale(hand: Hand) -> float:
    # 손가락을 집거나 펴는 동작의 영향을 줄이기 위해 손바닥 뼈 길이만 쓴다.
    p = hand.points
    return max(float(np.median([np.linalg.norm(p[a] - p[b])
                               for a, b in [(0, 5), (0, 9), (0, 13), (5, 17)]])), 1e-4)


class DepthCursor:
    def __init__(self) -> None:
        self.fx, self.fy = OneEuro(1, 3), OneEuro(1, 3)
        self.last: np.ndarray | None = None
        self.plane: bool | None = None

    def reset(self) -> None:
        self.fx.reset()
        self.fy.reset()
        self.last = self.plane = None

    def update(self, point: np.ndarray | None, scale: float, t: float, surface: TouchSurface | None,
               *, smoothing: float, gain: float, freeze: bool = False, deadzone: float = .001,
               perspective: bool = False) -> tuple[float, float]:
        """perspective: 크기 기반 깊이일 때 원근 보정. 핀홀 카메라에서 x - 가운데 = f·X/Z 이고 크기 ∝ 1/Z 이므로
        d(x) = (물체 좌우 이동 성분) + (x - 가운데)·d(log 크기). 뒤 항(앞뒤로 움직여 생긴 사선 성분)을 뺀다.
        화면 가운데에서는 0 이라 예전과 같고, 초점거리(FOV)는 상쇄되어 필요 없다 (감도로만 남는다)."""
        if point is None or not np.isfinite(point).all() or not math.isfinite(scale) or scale <= 0 or freeze:
            self.reset()
            return 0., 0.
        plane = surface is not None and surface.mode in ("quad", "deskview")
        if plane and surface.mode == "quad":
            # 거의 수평인 얇은 사각형은 원근 역투영이 불안정하므로 크기 단서를 쓴다.
            q = surface.points
            plane = float(np.ptp(q[:, 1])) > .08 * max(float(np.ptp(q[:, 0])), 1e-4)
        if self.plane != plane:
            self.reset()
            self.plane = plane
        raw = surface.map(point) if plane else np.array([point[0], math.log(scale)])
        if not np.isfinite(raw).all():
            self.reset()
            return 0., 0.
        self.fx.min_cutoff = self.fy.min_cutoff = smoothing
        p = np.array([self.fx(float(raw[0]), t), self.fy(float(raw[1]), t)])
        if self.last is None:
            self.last = p
            return 0., 0.
        dx, dy = p - self.last
        if perspective and not plane:
            dx = float(dx) - (float(p[0]) - .5) * float(dy)  # dy = d(log 크기)
        dy = -float(dy) * (1 if plane else gain)  # 가까워짐(크기 증가) = 화면 위
        if math.hypot(dx, dy) < deadzone:
            return 0., 0.  # 작은 이동은 누적해 느린 움직임이 사라지지 않게 한다.
        self.last = p
        return float(np.clip(dx, -.12, .12)), float(np.clip(dy, -.12, .12))
