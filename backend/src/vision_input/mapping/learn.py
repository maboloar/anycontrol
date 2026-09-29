"""보여 주며 매핑하기: 사용자가 물체를 원하는 방식으로 움직여 보이면 어떤 축인지, 범위가 얼마인지 제안한다.

축마다 '보통 움직이는 폭'(TYPICAL) 으로 나눈 움직임 크기를 비교한다. 단위가 서로 다르므로(비율·log·도)
그대로 비교하면 각도가 늘 이긴다. 범위는 5~95 분위수 (가끔 튀는 값에 끌리지 않게).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# 손으로 편하게 움직이는 한 번의 폭. 화면 UI 막대 범위와 같은 값 (frontend ObjectPanel BAR_RANGE)
TYPICAL = {"x": 0.3, "y": 0.3, "depth": 0.8, "angle": 45.0, "stretch": 0.5, "contact": 0.2,
           "desk_x": 0.5, "desk_z": 0.5, "desk_yaw": 45.0}


@dataclass
class AxisSuggestion:
    axis: str
    score: float          # 움직임 크기 / 보통 폭
    range: list[float]    # 양방향 출력용 대칭 범위
    range_positive: list[float]  # 한방향 출력용 [중립 쪽, 움직인 쪽] (움직인 방향이 - 면 뒤집힘 필요)
    invert_for_positive: bool


@dataclass
class AxisLearner:
    object_id: int
    samples: dict[str, list[float]] = field(default_factory=dict)
    frames: int = 0

    def add(self, axes: dict[str, float | None]) -> None:
        self.frames += 1
        for k, v in axes.items():
            if v is not None and k in TYPICAL:
                self.samples.setdefault(k, []).append(float(v))

    def suggest(self, min_samples: int = 10) -> list[AxisSuggestion]:
        out = []
        for k, vs in self.samples.items():
            if len(vs) < min_samples:
                continue
            a = np.asarray(vs)
            p5, p95 = np.percentile(a, [5, 95])
            score = float((p95 - p5) / TYPICAL[k])
            r = max(abs(p5), abs(p95), 1e-6)
            # 한방향: 중립(0)에서 더 멀리 간 쪽이 '누른' 방향
            if abs(p95) >= abs(p5):
                pos, inv = [0.0, float(p95)], False
            else:
                pos, inv = [float(p5), 0.0], True
            if pos[1] <= pos[0]:
                pos = [pos[0], pos[0] + 1e-3]
            out.append(AxisSuggestion(k, round(score, 3), [round(-r, 5), round(r, 5)],
                                      [round(pos[0], 5), round(pos[1], 5)], inv))
        return sorted(out, key=lambda s: -s.score)
