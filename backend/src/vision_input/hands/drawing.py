"""엄지·검지를 맞대는 동안 검지 끝의 궤적을 그린다. 마우스 출력과 독립적이다."""

from __future__ import annotations

from typing import Any

import numpy as np

from .detector import INDEX_TIP, Hand, HandFrame
from .gestures import GestureConfig, GestureRecognizer, features
from ..tracking.smooth import OneEuro

HAND_STALE_S = 0.3


class HandDrawing:
    def __init__(self) -> None:
        self.enabled = False
        self.mirror = False
        self.gestures = GestureRecognizer(GestureConfig(release_frames=1))
        self.fx, self.fy = OneEuro(2, 3), OneEuro(2, 3)
        self.current: list[list[float]] | None = None
        self.events: list[dict[str, Any]] = []
        self.stroke_count = 0
        self.point: list[float] | None = None
        self.pinch_index: float | None = None
        self._palm: np.ndarray | None = None
        self._handedness: str | None = None
        self._last_t: float | None = None

    def _lift(self) -> None:
        if self.current is not None:
            self.events.append({"type": "up", "stroke": self.current})
            self.stroke_count += 1
            self.current = None

    def _lose_hand(self) -> None:
        self._lift()
        self.gestures.reset()
        self.fx.reset()
        self.fy.reset()
        self.point = self.pinch_index = None
        self._palm = self._handedness = None

    def set_enabled(self, enabled: bool) -> None:
        if enabled != self.enabled:
            self._lose_hand()
        self.enabled = enabled

    def clear(self) -> None:
        self.current = None
        self.stroke_count = 0
        self.events = [{"type": "clear"}]
        self.gestures.reset()

    def reset(self) -> None:
        self._lose_hand()
        self._last_t = None
        self.clear()

    def suspend(self) -> None:
        self._lose_hand()

    def _pick(self, hands: list[Hand]) -> Hand | None:
        candidates = [h for h in hands if self._handedness is None or h.handedness == self._handedness]
        if not candidates:
            return None
        if self._palm is None:
            return max(candidates, key=lambda h: h.score)
        hand = min(candidates, key=lambda h: np.linalg.norm(features(h, self.gestures.cfg).palm - self._palm))
        f = features(hand, self.gestures.cfg)
        # 다른 손이나 갑작스러운 재검출을 한 획으로 연결하지 않는다.
        return hand if np.linalg.norm(f.palm - self._palm) <= max(.12, f.size * 1.5) else None

    def update(self, hf: HandFrame | None, t: float, pinch_on: float = .30) -> None:
        if not self.enabled or hf is None or not 0 <= t - hf.t < HAND_STALE_S:
            self._lose_hand()
            return
        # 손 인식은 카메라보다 느리다. 같은 관측으로 누름 프레임을 중복 세지 않는다.
        if self._last_t is not None and hf.t <= self._last_t:
            return
        self._last_t = hf.t
        if pinch_on != self.gestures.cfg.pinch_on:
            self._lose_hand()
            self.gestures.cfg.pinch_on = pinch_on
            self.gestures.cfg.pinch_off = pinch_on * 1.5
        hand = self._pick(hf.hands)
        if hand is None or not np.isfinite(hand.points).all():
            self._lose_hand()
            return
        g = self.gestures.update(hand, hf.t)
        f = g.features
        assert f is not None
        self._palm, self._handedness = f.palm, hand.handedness
        self.pinch_index = round(f.pinch_index, 3)
        x, y = np.clip(hand.points[INDEX_TIP], 0, 1)
        self.point = [round(self.fx(float(x), hf.t, f.size), 5),
                      round(self.fy(float(y), hf.t, f.size), 5)]
        if self.mirror:
            self.point[0] = 1.0 - self.point[0]
        # 마우스용 커서 고정을 적용하지 않고 검지 끝을 계속 따라간다.
        if g.left:
            if self.current is None:
                self.current = []
                self.events.append({"type": "down"})
            self.current.append(self.point.copy())
        else:
            self._lift()

    def state(self) -> dict[str, Any]:
        events, self.events = self.events, []
        return {"enabled": self.enabled, "hand_visible": self.point is not None,
                "contact": self.current is not None, "point": self.point,
                "pinch_index": self.pinch_index, "current": self.current,
                "stroke_count": self.stroke_count, "events": events}
