"""Desk contact geometry and relative touchpad movement.

Coordinates are normalized camera coordinates. A single RGB view cannot prove
physical contact, so the surface constraint is combined with finger posture.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from ..hands.detector import Hand
from ..hands.gestures import GestureOutput
from ..tracking.desk import order_quad
from ..tracking.smooth import OneEuro


@dataclass
class TouchSurface:
    mode: str
    points: np.ndarray
    H: np.ndarray | None = None
    contact_bounds: np.ndarray | None = None  # 안내 보정에서 실제로 접촉하며 이동한 영상 범위

    @classmethod
    def overhead(cls) -> TouchSurface:
        return cls('deskview', np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32),
                   np.eye(3, dtype=np.float32))

    @classmethod
    def quad(cls, points: list[list[float]]) -> TouchSurface:
        if len(points) != 4:
            raise ValueError("책상 네 모서리가 필요합니다")
        q = order_quad(np.asarray(points, np.float32)).astype(np.float32)
        if not np.isfinite(q).all():
            raise ValueError("책상 좌표가 올바르지 않습니다")
        if cv2.contourArea(q) < 0.0005:
            raise ValueError("책상 네 점이 한 줄에 너무 가깝습니다. 수평 기준선 2점을 사용하세요")
        # order_quad: near-left, near-right, far-right, far-left
        dst = np.array([[0, 1], [1, 1], [1, 0], [0, 0]], np.float32)
        return cls("quad", q, cv2.getPerspectiveTransform(q, dst))

    @classmethod
    def line(cls, points: list[list[float]]) -> TouchSurface:
        if len(points) != 2:
            raise ValueError("책상 기준선 두 점이 필요합니다")
        p = np.asarray(points, np.float32)
        if not np.isfinite(p).all() or np.linalg.norm(p[1] - p[0]) < 0.05:
            raise ValueError("책상 기준선 두 점을 더 멀리 찍어 주세요")
        if p[0, 0] > p[1, 0]:
            p = p[::-1].copy()
        return cls("line", p)

    def map(self, point: np.ndarray) -> np.ndarray:
        p = np.asarray(point, np.float32)
        if self.H is not None:
            return cv2.perspectiveTransform(p.reshape(1, 1, 2), self.H).reshape(2)
        a, b = self.points
        d = b - a
        den = float(d @ d)
        u = float((p - a) @ d) / den
        v = .5 + float((p - a) @ np.array([-d[1], d[0]])) / math.sqrt(den) / .25
        return np.array([u, v], np.float32)

    def contains(self, point: np.ndarray, margin: float) -> bool:
        if self.contact_bounds is not None:
            p = np.asarray(point)
            return bool(np.isfinite(p).all() and np.all(p >= self.contact_bounds[0] - margin) and
                        np.all(p <= self.contact_bounds[1] + margin))
        u, v = self.map(point)
        if not np.isfinite([u, v]).all() or not -margin <= u <= 1 + margin:
            return False
        return (-margin <= v <= 1 + margin) if self.mode != "line" else (.4 - margin <= v <= 1.5 + margin)


class RelativeTouchpad:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.last: np.ndarray | None = None
        self.last_scale: float | None = None
        self.scroll_last: np.ndarray | None = None
        self.scroll_scale: float | None = None
        self.touch_frames = 0
        self.touching = False
        self.cursor_filters = [OneEuro(1, 3), OneEuro(1, 3), OneEuro(1, 3)]
        self.scroll_filters = [OneEuro(1, 3), OneEuro(1, 3), OneEuro(1, 3)]

    @staticmethod
    def _smooth(point: np.ndarray, scale: float, t: float, cutoff: float,
                filters: list[OneEuro]) -> tuple[np.ndarray, float]:
        for f in filters:
            f.min_cutoff = cutoff
        uv = np.array([filters[0](float(point[0]), t), filters[1](float(point[1]), t)])
        size = math.exp(filters[2](math.log(scale), t))
        return uv, size

    @staticmethod
    def _finger(surface: TouchSurface, p: np.ndarray, tip: int, pip: int,
                scale: float, height: float, margin: float, depth: np.ndarray | None = None) -> bool:
        if not surface.contains(p[tip], margin):
            return False
        if depth is not None:
            # 위에서 보는 영상에서는 화면 y 대신 손가락 끝의 상대 깊이/자세를 사용한다.
            raised = float(depth[pip] - depth[tip]) / scale
            return math.isfinite(raised) and raised <= height + .25
        return float(p[tip, 1] - p[pip, 1]) / scale >= height

    def update(self, hand: Hand | None, gesture: GestureOutput, surface: TouchSurface | None,
               *, t: float, smoothing: float, height: float, margin: float, depth_blend: float,
               deadzone: float, scroll_gain: float, overhead: bool = False, depth_gain: float = 1.4) -> tuple[float, float, float, bool]:
        """Return dx, dy, scroll, touching. Positive dy moves the cursor down."""
        if hand is None or surface is None:
            self.reset()
            return 0., 0., 0., False
        p = hand.points
        scale = max(float(np.linalg.norm(p[5] - p[17])), 1e-4)
        depth = hand.depth if overhead else None
        touch = self._finger(surface, p, 8, 6, scale, height, margin, depth)
        if touch:
            self.touch_frames += 1
            if self.touch_frames >= 2:
                self.touching = True
        else:
            self.reset()
            return 0., 0., 0., False
        if not self.touching:
            return 0., 0., 0., False

        blend = 0. if surface.mode in ("quad", "deskview") else float(np.clip(depth_blend, 0, 1))
        if gesture.gesture == "scroll" and self._finger(surface, p, 12, 10, scale, height, margin, depth):
            mid, scroll_size = self._smooth(surface.map((p[8] + p[12]) * .5), scale,
                                             t, smoothing, self.scroll_filters)
            scroll = 0.
            if self.scroll_last is not None:
                scroll_scale = 0. if self.scroll_scale is None else float(np.clip(math.log(scroll_size / self.scroll_scale), -.15, .15))
                scroll = float(((self.scroll_last[1] - mid[1]) * (1 - blend) -
                                scroll_scale * blend * depth_gain) * scroll_gain)
            self.scroll_last, self.scroll_scale = mid, scroll_size
            self.last, self.last_scale = None, None
            for f in self.cursor_filters:
                f.reset()
            return 0., 0., float(np.clip(scroll, -4, 4)), True

        self.scroll_last, self.scroll_scale = None, None
        for f in self.scroll_filters:
            f.reset()
        if gesture.freeze:
            self.last, self.last_scale = None, None
            for f in self.cursor_filters:
                f.reset()
            return 0., 0., 0., True
        tip_uv, cursor_scale = self._smooth(surface.map(p[8]), scale, t, smoothing, self.cursor_filters)
        scale_motion = 0. if self.last_scale is None else float(np.clip(math.log(cursor_scale / self.last_scale), -.15, .15))
        if self.last is None:
            self.last, self.last_scale = tip_uv, cursor_scale
            return 0., 0., 0., True
        dx = 0. if self.last is None else float(tip_uv[0] - self.last[0])
        dy = 0. if self.last is None else float(-((tip_uv[1] - self.last[1]) * (1 - blend) +
                                                   scale_motion * blend * depth_gain))
        if math.hypot(dx, dy) < deadzone:
            return 0., 0., 0., True
        self.last, self.last_scale = tip_uv, cursor_scale
        return float(np.clip(dx, -.12, .12)), float(np.clip(dy, -.12, .12)), 0., True
