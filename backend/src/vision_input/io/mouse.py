"""마우스 컨트롤러: 맨손 마우스 / 물체 마우스.

- off:    아무것도 하지 않는다. 손 추적도 꺼진다.
- hand:   손바닥 좌우·접근/후퇴 = 상대 커서 이동, 손 제스처 = 클릭·오른쪽 클릭·스크롤
- object: 물체 좌우·접근/후퇴 = 상대 커서 이동, 손 제스처 = 클릭·스크롤

기본은 수평 카메라용 크기 기반 깊이이며 책상 평면 보정이 있으면 우선 사용한다.
화면 XY 절대 위치와 접촉 중 이동하는 터치패드는 별도 모드로 제공한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field, field_validator

from ..hands.detector import Hand, HandFrame
from ..hands.gestures import GestureConfig, GestureRecognizer
from ..hands.object_tap import ObjectTapDetector
from ..tracking.smooth import OneEuro
from .sink import OutputSink
from .touchpad import RelativeTouchpad, TouchSurface
from .depth import DepthCursor, palm_scale

Mode = Literal["off", "hand", "object"]
HAND_STALE_S = 0.3


def axis_adjust(p: np.ndarray, sens_x: float = 1.0, sens_y: float = 1.0,
                invert_x: bool = False, invert_y: bool = False) -> np.ndarray:
    """커서 정규화 좌표(0..1)에 축별 감도(가운데 기준 배율)와 반전을 적용한다. 결과는 항상 [0, 1]."""
    x = float(np.clip(0.5 + (float(p[0]) - 0.5) * sens_x, 0.0, 1.0))
    y = float(np.clip(0.5 + (float(p[1]) - 0.5) * sens_y, 0.0, 1.0))
    if invert_x:
        x = 1.0 - x
    if invert_y:
        y = 1.0 - y
    return np.array([x, y])


class MouseSettings(BaseModel):
    mode: Mode = "off"
    object_id: int | None = None
    mirror: bool = False
    hand_region: list[float] = Field(default_factory=lambda: [0.2, 0.15, 0.8, 0.75], min_length=4, max_length=4)
    object_region: list[float] = Field(default_factory=lambda: [0.1, 0.1, 0.9, 0.9], min_length=4, max_length=4)
    hand_clicks: bool = True           # 물체 모드에서 손 제스처로 클릭
    object_tap: bool = True
    object_tap_distance: float = Field(.10, ge=.03, le=.25)
    smoothing: float = Field(1.0, ge=0.1, le=10.0)   # One Euro min_cutoff (Hz). 낮을수록 부드럽고 느림
    pinch_on: float = Field(0.30, ge=0.1, le=0.8)
    hand_control: Literal["depth", "touchpad", "air"] = "depth"
    coordinate_mode: Literal["depth", "image"] = "depth"
    depth_sensitivity: float = Field(1.5, ge=.2, le=6)
    depth_gain: float = Field(1.4, ge=.2, le=5)
    depth_deadzone: float = Field(.001, ge=0, le=.04)
    touch_sensitivity: float = Field(1.5, ge=0.2, le=6.0)
    touch_height: float = Field(-0.2, ge=-1.0, le=1.0)
    touch_margin: float = Field(0.025, ge=0, le=0.15)
    touch_depth_blend: float = Field(1., ge=0, le=1)
    touch_depth_gain: float = Field(1.4, ge=.2, le=5)
    touch_deadzone: float = Field(0.004, ge=0, le=0.04)
    scroll_gain: float = Field(20.0, ge=1, le=100)
    invert_y: bool = False
    # 축별 감도(배율). 상대 이동(깊이·터치패드·펜)은 이동량에, 절대 위치(화면 XY)는 가운데 기준으로 곱한다.
    # 좌우 반전은 mirror(자동 보정도 이것을 정한다), 상하 반전은 invert_y.
    sens_x: float = Field(1.0, ge=0.2, le=5.0)
    sens_y: float = Field(1.0, ge=0.2, le=5.0)
    # 크기 기반 깊이의 원근 보정: 화면 가장자리에서 카메라 쪽으로 곧게 움직여도 영상에서는 가운데에서 멀어지는
    # 사선으로 보인다 (x - 가운데 ∝ 크기). 크기 변화만큼 생긴 좌우 이동을 빼서 앞뒤 이동이 커서 위아래로만 가게 한다.
    depth_perspective: bool = True
    # 종이(책상 4점) 보정이 있으면 깊이 커서를 책상 면 좌표로 계산한다 (가장자리 사다리꼴을 편다). 끄면 크기 기반.
    desk_correct: bool = True
    invert_scroll: bool = False
    pen_relative: bool = True
    pen_sensitivity: float = Field(1.5, ge=0.2, le=6.0)
    pen_depth_blend: float = Field(1., ge=0, le=1)
    pen_depth_gain: float = Field(1.4, ge=.2, le=5)
    pen_deadzone: float = Field(.001, ge=0, le=.04)

    @field_validator("hand_region", "object_region")
    @classmethod
    def _region(cls, v: list[float]) -> list[float]:
        x0, y0, x1, y1 = v
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1) or x1 - x0 < 0.1 or y1 - y0 < 0.1:
            raise ValueError("region must be [x0,y0,x1,y1] within 0..1 and at least 0.1 wide")
        return v

    @property
    def needs_hands(self) -> bool:
        return self.mode == "hand" or (self.mode == "object" and self.hand_clicks)


@dataclass
class _Cursor:
    """One Euro + 고정(freeze) 오프셋. 고정이 풀릴 때 커서가 튀지 않도록 오프셋을 서서히 0 으로."""

    fx: OneEuro
    fy: OneEuro
    offset: np.ndarray
    out: np.ndarray | None = None
    decay_s: float = 0.35

    def update(self, raw: np.ndarray, t: float, freeze: bool, dt: float) -> np.ndarray:
        s = np.array([self.fx(float(raw[0]), t, 1.0), self.fy(float(raw[1]), t, 1.0)])
        if self.out is None:
            self.out = s.copy()
        if freeze:
            self.offset = self.out - s     # 화면 위치를 그대로 둔다
        else:
            self.offset *= math.exp(-dt / self.decay_s)
            self.out = s + self.offset
        return self.out


class MouseController:
    def __init__(self, sink: OutputSink) -> None:
        self.sink = sink
        self.settings = MouseSettings()
        self.input_mirror = False
        self.gestures = GestureRecognizer()
        self.object_tap = ObjectTapDetector()
        self._new_cursor()
        self.t_prev: float | None = None
        self.hand_idx: int | None = None
        self.last_palm: np.ndarray | None = None
        self.status: dict[str, Any] = {}
        self.touch_surface: TouchSurface | None = None
        self.touchpad = RelativeTouchpad()
        self.pen_last: tuple[np.ndarray, float] | None = None
        self.desk_view = False

    def _new_cursor(self) -> None:
        mc = self.settings.smoothing
        self.cursor = _Cursor(OneEuro(mc, 3.0, 1.0), OneEuro(mc, 3.0, 1.0), np.zeros(2))
        self.depth_cursor = DepthCursor()

    def configure(self, s: MouseSettings) -> None:
        old = self.settings
        switch = (old.mode, old.object_id, old.hand_control, old.mirror, old.invert_y,
                  old.pen_relative, old.coordinate_mode) != (s.mode, s.object_id, s.hand_control, s.mirror,
                                       s.invert_y, s.pen_relative, s.coordinate_mode)
        if switch:
            self.sink.release_all()
        self.settings = s
        if switch or old.object_tap != s.object_tap or old.hand_clicks != s.hand_clicks:
            self.object_tap.reset()
        if switch or old.pinch_on != s.pinch_on:
            self.gestures = GestureRecognizer(GestureConfig(pinch_on=s.pinch_on, pinch_off=s.pinch_on * 1.5))
            if not switch:
                self.sink.button("left", False)
                self.sink.button("right", False)
        self.gestures.cfg.scroll_gain = s.scroll_gain
        if not switch and old.desk_correct != s.desk_correct:
            self.depth_cursor.reset()  # 기준 좌표계가 바뀌므로 상대 이동을 새로 시작 (커서 점프 방지)
        if switch or old.smoothing != s.smoothing:
            self._new_cursor()
        if switch:
            self.last_palm = None
            self.touchpad.reset()
            self.pen_last = None

    def set_surface(self, surface: TouchSurface | None) -> None:
        self.touch_surface = surface
        self.touchpad.reset()
        self.pen_last = None
        self.depth_cursor.reset()

    def emergency_stop(self) -> None:
        self.sink.release_all()
        self.configure(self.settings.model_copy(update={"mode": "off"}))

    # ---------------------------------------------------------------- 매 프레임
    def update(self, t: float, hands: HandFrame | None, obj_center: tuple[float, float] | None,
               obj_visible: bool, obj_pressed: bool = False,
               ext_buttons: dict[str, bool] | None = None,
               obj_is_pen: bool = False, obj_scale: float = 1.0,
               obj_box: tuple[float, float, float, float] | None = None,
               obj_foot: tuple[float, float] | None = None) -> dict[str, Any]:
        """obj_pressed: 물체 자체의 누름 신호 (펜촉이 책상에 닿음). 왼쪽 버튼으로 쓴다.
        obj_foot: 물체가 책상에 닿은 점 (정규화, 부드러운 포즈 기준). 종이 보정이 있을 때 커서 기준점으로 쓴다.
        ext_buttons: 매핑 엔진이 내보내는 마우스 버튼 (마우스 모드와 무관하게 OR 로 합친다)."""
        s = self.settings
        ext = ext_buttons or {}
        dt = 1 / 30 if self.t_prev is None else max(1e-3, t - self.t_prev)
        self.t_prev = t
        if s.mode == "off":
            self.sink.button("left", bool(ext.get("left")))
            self.sink.button("right", bool(ext.get("right")))
            self.status = {"mode": "off"}
            return self.status
        fresh = hands is not None and t - hands.t < HAND_STALE_S
        hand = self._pick_hand(hands.hands if fresh else [], obj_center)  # type: ignore[union-attr]
        use_gestures = s.mode == "hand" or s.hand_clicks
        g = self.gestures.update(hand if use_gestures else None, t)
        tap_enabled = s.mode == "object" and s.hand_clicks and s.object_tap and not obj_is_pen and obj_visible
        tap = self.object_tap.update(hands.hands if fresh and tap_enabled else [],
                                     obj_box, t, hands.t if fresh else None,
                                     s.object_tap_distance)

        raw = None
        touch = False
        touch_scroll = 0.0
        depth_active = False
        if s.mode == "hand" and s.hand_control == "depth":
            point = None if g.features is None else g.features.palm
            scale = 1. if hand is None else palm_scale(hand)
            dx, dy = self.depth_cursor.update(point, scale, t, self._depth_surface(),
                smoothing=s.smoothing, gain=s.depth_gain, freeze=g.freeze, deadzone=s.depth_deadzone,
                perspective=s.depth_perspective)
            self.sink.move_by(dx * s.depth_sensitivity * self._sx(), dy * s.depth_sensitivity * self._sy())
            depth_active = point is not None
        elif s.mode == "hand" and s.hand_control == "touchpad":
            dx, dy, touch_scroll, touch = self.touchpad.update(
                hand, g, self.touch_surface, t=t, smoothing=s.smoothing,
                height=s.touch_height, margin=s.touch_margin,
                depth_blend=s.touch_depth_blend, deadzone=s.touch_deadzone,
                scroll_gain=s.scroll_gain, overhead=self.desk_view, depth_gain=s.touch_depth_gain)
            if dx or dy:
                self.sink.move_by(dx * self._sx() * s.touch_sensitivity, dy * self._sy() * s.touch_sensitivity)
        elif s.mode == "hand" and hand is not None and g.features is not None:
            raw = self._map(g.features.palm, s.hand_region)
        elif s.mode == "object" and obj_is_pen and s.pen_relative:
            if obj_center is not None and obj_visible and obj_pressed:
                p = np.asarray(obj_center, float)
                if self.touch_surface is not None:
                    p = self.touch_surface.map(p)
                if self.pen_last is not None:
                    prev, prev_scale = self.pen_last
                    blend = 0. if self.touch_surface is not None and self.touch_surface.mode in ("quad", "deskview") else s.pen_depth_blend
                    scale_change = float(np.clip(math.log(max(obj_scale, .1) / max(prev_scale, .1)), -.15, .15))
                    dx = float(np.clip(p[0] - prev[0], -.12, .12))
                    dy = float(np.clip(-(p[1] - prev[1]) * (1 - blend) - scale_change * blend * s.pen_depth_gain, -.12, .12))
                    if math.hypot(dx, dy) < s.pen_deadzone:
                        dx = dy = 0.
                    else:
                        self.pen_last = (p, obj_scale)
                    self.sink.move_by(dx * s.pen_sensitivity * self._sx(), dy * s.pen_sensitivity * self._sy())
                if self.pen_last is None:
                    self.pen_last = (p, obj_scale)
            else:
                self.pen_last = None
        elif s.mode == "object" and s.coordinate_mode == "depth":
            point = np.asarray(obj_center, float) if obj_visible and obj_center is not None else None
            surface = self._depth_surface()
            if point is not None and surface is not None and surface.mode == "quad":
                # 종이 보정: 책상에 닿은 점을 책상 면에 투영한다. 매 프레임 마스크 맨 아래(박스 아래 변)는 640px 마스크의
                # 계단·가장자리 떨림·손 가림이 그대로 실려 커서가 떨렸다 → 부드러운 포즈 + 천천히 따라가는 오프셋(obj_foot).
                if obj_foot is not None:
                    point = np.asarray(obj_foot, float)
                elif obj_box is not None:
                    point = np.array([(obj_box[0] + obj_box[2]) * .5, obj_box[3]])
            dx, dy = self.depth_cursor.update(point, obj_scale, t, surface,
                smoothing=s.smoothing, gain=s.depth_gain, freeze=g.freeze and g.gesture != "scroll", deadzone=s.depth_deadzone,
                perspective=s.depth_perspective)
            self.sink.move_by(dx * s.depth_sensitivity * self._sx(), dy * s.depth_sensitivity * self._sy())
            depth_active = point is not None
        elif s.mode == "object" and obj_center is not None and obj_visible:
            raw = self._map(np.asarray(obj_center, float), s.object_region)
        if raw is not None:
            freeze = g.freeze if s.mode == "hand" else (g.freeze and g.gesture != "scroll")
            p = self.cursor.update(raw, t, freeze, dt)
            p = axis_adjust(p, s.sens_x, s.sens_y)  # 반전은 _map 에서 (거울·반전 뒤 가운데 기준 배율)
            self.sink.move(float(p[0]), float(p[1]))
        # 버튼·스크롤 (커서가 없어도 손 제스처는 반영)
        pressed = s.mode == "object" and obj_pressed
        gestures_enabled = s.mode != "hand" or s.hand_control != "touchpad" or touch
        self.sink.button("left", (g.left and gestures_enabled) or pressed or tap or bool(ext.get("left")))
        self.sink.button("right", (g.right and gestures_enabled) or bool(ext.get("right")))
        scroll = touch_scroll if s.mode == "hand" and s.hand_control == "touchpad" else g.scroll
        if scroll:
            self.sink.scroll(-scroll if s.invert_scroll else scroll)
        f = g.features
        self.status = {
            "mode": s.mode,
            "desk_view": self.desk_view,
            "hand_visible": hand is not None,
            "cursor_source": "hand" if s.mode == "hand" else "object",
            "cursor_active": raw is not None or depth_active or touch or (obj_is_pen and obj_pressed),
            "coordinate_mode": "depth" if depth_active else "image" if raw is not None else s.coordinate_mode,
            "depth_source": "desk" if self.depth_cursor.plane else "size",
            "perspective_active": bool(depth_active and not self.depth_cursor.plane and s.depth_perspective),
            "touching": touch,
            "surface_mode": None if self.touch_surface is None else self.touch_surface.mode,
            "gesture": "object-tap" if tap else "pen" if pressed and not g.left else g.gesture,
            "freeze": g.freeze,
            "pinch_index": None if f is None else round(f.pinch_index, 3),
            "pinch_middle": None if f is None else round(f.pinch_middle, 3),
            "pinch_on": s.pinch_on,
        }
        return self.status

    def _map(self, p: np.ndarray, region: list[float]) -> np.ndarray:
        x0, y0, x1, y1 = region
        x = (float(p[0]) - x0) / (x1 - x0)
        y = (float(p[1]) - y0) / (y1 - y0)
        if self.settings.mirror != self.input_mirror:
            x = 1.0 - x
        if self.settings.invert_y:
            y = 1.0 - y
        return np.clip(np.array([x, y]), 0.0, 1.0)

    def _depth_surface(self) -> TouchSurface | None:
        """깊이 커서가 쓸 책상 면. 종이 4점 보정은 desk_correct 를 끄면 쓰지 않는다 (Desk View 는 항상)."""
        sf = self.touch_surface
        if sf is not None and sf.mode == "quad" and not self.settings.desk_correct:
            return None
        return sf

    def _sx(self) -> float:
        """상대 이동의 x 배율: 감도 × 부호 (마우스 좌우 반전 XOR 전역 입력 거울)."""
        s = self.settings
        return s.sens_x * (-1. if s.mirror != self.input_mirror else 1.)

    def _sy(self) -> float:
        s = self.settings
        return s.sens_y * (-1. if s.invert_y else 1.)

    def _pick_hand(self, hands: list[Hand], obj_center: tuple[float, float] | None) -> Hand | None:
        """손이 여럿이면: 직전 손과 가까운 손을 계속 쓴다 (커서가 손 사이를 오가지 않게).

        물체 모드에서는 물체에서 먼 손을 고른다 (물체를 쥔 손은 제스처가 가려지기 쉽다)."""
        if not hands:
            self.last_palm = None
            return None
        palms = [h.points[[0, 5, 9, 13, 17]].mean(0) for h in hands]
        if self.settings.mode == "object" and obj_center is not None and len(hands) > 1:
            i = int(np.argmax([np.linalg.norm(p - np.asarray(obj_center)) for p in palms]))
        elif self.last_palm is not None:
            i = int(np.argmin([np.linalg.norm(p - self.last_palm) for p in palms]))
        else:
            i = int(np.argmax([h.score for h in hands]))
        self.last_palm = palms[i]
        return hands[i]
