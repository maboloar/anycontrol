"""물체를 쥔 손의 검지 탭. 영상상 거리이므로 실제 접촉 센서와 같지는 않다."""

from __future__ import annotations

import numpy as np

from .detector import Hand, INDEX_TIP


class ObjectTapDetector:
    def __init__(self) -> None:
        self.last_click = -float("inf")
        self.reset()

    def reset(self) -> None:
        self.armed = False
        self.lift_frames = self.touch_frames = 0
        self.pulse_until = -float("inf")
        self.observation: float | None = None
        self.wrist: np.ndarray | None = None

    def update(self, hands: list[Hand], box: tuple[float, float, float, float] | None,
               t: float, observation: float | None, threshold: float = .10) -> bool:
        if box is None or not hands:
            self.reset()
            return False
        bounds = np.asarray(box, float).reshape(2, 2)
        center = bounds.mean(0)

        def distance(p: np.ndarray) -> float:
            return float(np.linalg.norm(p - np.clip(p, bounds[0], bounds[1])))

        candidates = []
        for hand in hands:
            size = float(np.linalg.norm(hand.points[5] - hand.points[17]))
            palm = hand.points[[0, 5, 9, 13, 17]].mean(0)
            if size > .015 and hand.score >= .5 and distance(palm) <= 1.5 * size:
                candidates.append((float(np.linalg.norm(palm - center)) / size, hand, size))
        if not candidates:
            self.reset()
            return False
        _, hand, size = min(candidates, key=lambda item: item[0])
        if self.wrist is not None and np.linalg.norm(hand.points[0] - self.wrist) > size * 1.5:
            self.reset()  # 손이 바뀌면 이전 손의 탭 준비 상태를 넘기지 않는다
        self.wrist = hand.points[0].copy()
        if observation == self.observation:
            return t < self.pulse_until  # 워커 결과 재사용을 새 관측으로 세지 않는다
        self.observation = observation
        gap = distance(hand.points[INDEX_TIP]) / size
        if gap >= max(.35, threshold * 2.5):
            self.lift_frames += 1
            self.touch_frames = 0
            if self.lift_frames >= 2:
                self.armed = True
        elif gap <= threshold:
            self.touch_frames += 1
            self.lift_frames = 0
            if self.armed and self.touch_frames >= 2 and t - self.last_click >= .45:
                self.pulse_until = t + .08
                self.last_click = t
                self.armed = False
        else:
            self.lift_frames = self.touch_frames = 0
        return t < self.pulse_until
