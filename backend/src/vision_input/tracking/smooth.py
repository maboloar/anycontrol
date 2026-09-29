"""출력 안정화: One Euro 필터 (Casiez et al., CHI 2012).

입력 장치의 표준 필터. 속도에 따라 차단 주파수를 바꾼다.
- 느릴 때(거의 정지): 차단 주파수가 낮아 떨림을 강하게 누른다
- 빠를 때: 차단 주파수가 올라가 지연이 작다
속도 민감도(beta)는 '물체 크기/초' 단위라 물체 크기·해상도와 무관하게 같은 느낌이다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def _alpha(cutoff: float, dt: float) -> float:
    tau = 1.0 / (2 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class OneEuro:
    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.5, d_cutoff: float = 1.0) -> None:
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x: float | None = None
        self.dx = 0.0
        self.t: float | None = None

    def reset(self, x: float | None = None, t: float | None = None) -> None:
        self.x, self.dx, self.t = x, 0.0, t

    def __call__(self, x: float, t: float, speed_unit: float = 1.0) -> float:
        """speed_unit: 속도를 이 단위로 나눠 beta 에 곱한다 (예: 물체 크기 px → '물체 크기/초').

        값 자체를 단위로 나누면 안 된다: 화면 좌표(수백 px)를 크기로 나누면 크기 추정 잡음이
        좌표 전체에 곱해져 오히려 떨림이 커진다 (실측으로 확인한 버그).
        """
        if self.x is None or self.t is None:
            self.x, self.t = x, t
            return x
        dt = t - self.t
        if dt <= 0:
            return self.x
        dt = min(dt, 0.5)
        dx = (x - self.x) / dt
        a_d = _alpha(self.d_cutoff, dt)
        self.dx = a_d * dx + (1 - a_d) * self.dx
        cutoff = self.min_cutoff + self.beta * abs(self.dx) / max(speed_unit, 1e-9)
        a = _alpha(cutoff, dt)
        self.x = a * x + (1 - a) * self.x
        self.t = t
        return self.x


@dataclass
class SmoothConfig:
    min_cutoff: float = 1.2      # Hz. 정지 시 떨림 억제 정도 (낮을수록 강함)
    beta: float = 1.5            # 속도(물체 크기/초)에 따른 차단 주파수 증가 (클수록 빠른 움직임에 덜 늦음)
    d_cutoff: float = 1.0
    angle_min_cutoff: float = 1.0
    angle_beta: float = 0.02     # 도/초 단위


class PoseSmoother:
    """(cx, cy, log-scale, angle, aspect) 를 각각 One Euro 로. 위치는 물체 크기 단위."""

    def __init__(self, cfg: SmoothConfig | None = None) -> None:
        c = cfg or SmoothConfig()
        self.cfg = c
        self.fx = OneEuro(c.min_cutoff, c.beta, c.d_cutoff)
        self.fy = OneEuro(c.min_cutoff, c.beta, c.d_cutoff)
        self.fs = OneEuro(c.min_cutoff, c.beta, c.d_cutoff)
        self.fa = OneEuro(c.angle_min_cutoff, c.angle_beta, c.d_cutoff)
        self.fr = OneEuro(c.min_cutoff, c.beta, c.d_cutoff)

    def reset(self) -> None:
        for f in (self.fx, self.fy, self.fs, self.fa, self.fr):
            f.reset()

    def __call__(self, cx: float, cy: float, ls: float, angle: float, aspect: float, size: float,
                 t: float) -> tuple[float, float, float, float, float]:
        size = max(size, 1.0)
        return (self.fx(cx, t, size), self.fy(cy, t, size), self.fs(ls, t),
                self.fa(angle, t), math.exp(self.fr(math.log(max(aspect, 1e-3)), t)))
