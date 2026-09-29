"""Desk View의 외형 기반 접촉 보정. 닿음/떼기 예시가 구분될 때만 입력한다."""
from __future__ import annotations

from collections import deque
import numpy as np


class OverheadContact:
    def __init__(self) -> None:
        self.recent = deque(maxlen=9)
        self.touch = deque(maxlen=180)
        self.lift = deque(maxlen=180)
        self.score: float | None = None

    @staticmethod
    def feature(width: float, length: float, sharpness: float) -> np.ndarray:
        return np.array([np.log(max(width, 1)), .25 * np.log(max(length, 1)),
                         .08 * np.log1p(max(sharpness, 0))])

    def observe(self, point: np.ndarray, width: float, length: float, sharpness: float) -> None:
        feat = self.feature(width, length, sharpness)
        if np.isfinite(feat).all() and np.isfinite(point).all():
            self.recent.append((point.copy(), feat))

    @property
    def ready(self) -> bool:
        if not self.touch or not self.lift:
            return False
        a = np.median([s[1] for s in self.touch], axis=0)
        b = np.median([s[1] for s in self.lift], axis=0)
        return bool(np.linalg.norm(a - b) > .025)

    def mark(self, touching: bool) -> bool:
        if len(self.recent) < 3:
            return False
        target = self.touch if touching else self.lift
        target.extend((p.copy(), f.copy()) for p, f in self.recent)
        return True

    def classify(self) -> float | None:
        if not self.ready or not self.recent:
            self.score = None
            return None
        p, f = self.recent[-1]
        def distance(samples):
            ds = sorted(float(np.linalg.norm(f - sf) + .05 * np.linalg.norm(p - sp)) for sp, sf in samples)
            return float(np.mean(ds[:min(3, len(ds))]))
        a, b = distance(self.touch), distance(self.lift)
        # 배우지 않은 큰 기울기 변화는 접촉으로 결정하지 않는다.
        if min(a, b) > .3:
            self.score = None
        else:
            self.score = float((b - a) / max(a + b, .01))
        return self.score
