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
from ..hands.finger_click import FingerClickConfig, FingerClickDetector, FingerClickOutput
from ..hands.tip_click import TipClickDetector
from ..hands.tip_track import TipFrame
from ..hands.gestures import GestureConfig, GestureRecognizer, features
from ..hands.object_tap import ObjectTapDetector
from ..tracking.smooth import OneEuro
from .sink import OutputSink
from .touchpad import RelativeTouchpad, TouchSurface
from .depth import DepthCursor, palm_scale
from .hybrid import HybridRouter

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


# 깊이 모델 u(0~1)의 프레임 간 잡음은 0.005~0.01 (정지한 펜 쌍 실측). 이보다 작은 변화는 누적했다가 넘을 때 한 번에 반영한다.
MODEL_DEPTH_DEADZONE = 0.003


class MouseSettings(BaseModel):
    mode: Mode = "off"
    object_id: int | None = None
    mirror: bool = False
    hand_region: list[float] = Field(default_factory=lambda: [0.2, 0.15, 0.8, 0.75], min_length=4, max_length=4)
    object_region: list[float] = Field(default_factory=lambda: [0.1, 0.1, 0.9, 0.9], min_length=4, max_length=4)
    # 물체 마우스의 손 클릭·한 손 하이브리드: 삭제한 기능. 물체 마우스는 손 추적을 전혀 쓰지 않는다 (커서 이동만).
    # 저장값·요청이 켜져 있어도 항상 끈다 (아래 validator). 필드는 이전 설정 호환용.
    hand_clicks: bool = False
    object_hybrid: bool = False
    hybrid_detach: float = Field(.25, ge=.1, le=1.)
    hybrid_hand_control: Literal['air', 'depth'] = 'air'  # legacy saved settings; ignored (hand is click-only)
    # 맨손 모드 클릭 방식: finger = 검지·중지를 든 채 내려서 누름 (검지 = 오른쪽, 중지 = 왼쪽) / pinch = 엄지 집기 (스크롤 포함)
    hand_click_style: Literal["finger", "pinch"] = "pinch"
    finger_press: float = Field(.60, ge=.3, le=.85)  # 든 높이의 이 비율 이하로 내려가면 누름. 높을수록 민감
    # 물체 마우스: 검지·중지 끝점을 영상에서 직접 따라가 (손을 오므려 랜드마크가 틀려도) 원래 자리에서 내려와 물체에 닿으면 클릭.
    finger_track: bool = False   # 검지·중지 끝점 추적: 삭제한 기능. 저장값이 켜져 있어도 항상 끈다 (아래 validator)
    tip_drop: float = Field(.22, ge=.1, le=.8)   # 원래 자리에서 이만큼(손 크기) 내려와야 누름
    tip_refine: bool = True                      # 가끔 EfficientTAM 으로 손끝 주변 살색을 분할해 점을 바로잡음
    object_tap: bool = True            # 더 이상 쓰지 않음 (손가락 클릭이 대체). 이전 설정 호환용
    object_tap_distance: float = Field(.25, ge=.03, le=.4)  # 손가락 끝이 물체에 닿았다고 보는 거리 (손 크기 대비)
    smoothing: float = Field(1.0, ge=0.1, le=10.0)   # One Euro min_cutoff (Hz). 낮을수록 부드럽고 느림
    pinch_on: float = Field(0.30, ge=0.1, le=0.8)
    hand_control: Literal["depth", "touchpad", "air"] = "air"
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
    # 물체의 바닥 아래-가운데 기준점을 광학 흐름으로 따라가 커서를 움직인다 (분할 영역이 손 때문에 흔들려도 커서가 안 흔들린다). 끄면 분할 중심.
    anchor_cursor: bool = True
    # 물체 마우스의 앞뒤(깊이) 신호: size = 물체 크기 (기본, 예전 방식), model = Depth Anything V2 Small 로 잰 책상 위 앞뒤 위치 (선택).
    # model 인데 가중치가 없으면 자동으로 size 를 쓴다.
    depth_source: Literal["size", "model"] = "size"
    # model 일 때 감도: 물체가 책상 맨 뒤에서 맨 앞까지 가면 커서가 움직이는 화면 높이의 배수 (이전 크기 방식은 훨씬 적게 움직였다)
    depth_model_range: float = Field(3.0, ge=0.5, le=10)
    # 종이(책상 4점) 보정이 있으면 깊이 커서를 책상 면 좌표로 계산한다 (가장자리 사다리꼴을 편다). 끄면 크기 기반.
    desk_correct: bool = True
    invert_scroll: bool = False
    pen_relative: bool = True
    pen_sensitivity: float = Field(1.5, ge=0.2, le=6.0)
    pen_depth_blend: float = Field(1., ge=0, le=1)
    pen_depth_gain: float = Field(1.4, ge=.2, le=5)
    pen_deadzone: float = Field(.001, ge=0, le=.04)

    @field_validator("finger_track", "hand_clicks", "object_hybrid")
    @classmethod
    def _removed_hand_features(cls, v: bool) -> bool:
        return False

    @field_validator("hand_region", "object_region")
    @classmethod
    def _region(cls, v: list[float]) -> list[float]:
        x0, y0, x1, y1 = v
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1) or x1 - x0 < 0.1 or y1 - y0 < 0.1:
            raise ValueError("region must be [x0,y0,x1,y1] within 0..1 and at least 0.1 wide")
        return v

    @property
    def needs_hands(self) -> bool:
        return self.mode == "hand"   # 물체 마우스는 손 추적을 쓰지 않는다


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
        self.finger_clicks = FingerClickDetector()
        self.tip_clicks = TipClickDetector()
        self.tip_mode = False
        self.finger_hands_t: float | None = None
        self.finger_out = self.finger_clicks.update(None, 0.)
        self.finger_lm = self.finger_out
        self.object_tap = ObjectTapDetector()
        self.hybrid = HybridRouter()
        self.hybrid_xy = DepthCursor()
        self._new_cursor()
        self.t_prev: float | None = None
        self.hand_idx: int | None = None
        self.last_palm: np.ndarray | None = None
        self.status: dict[str, Any] = {}
        self.touch_surface: TouchSurface | None = None
        self.touchpad = RelativeTouchpad()
        self.pen_last: tuple[np.ndarray, float] | None = None
        self.desk_view = False

    model_depth = False   # VisionProcessor 가 매 프레임 정한다: 이번 프레임 깊이 신호가 깊이 모델 값인가

    def _depth_gain(self, s: "MouseSettings", model: bool) -> float:
        return s.depth_model_range / s.depth_sensitivity if model else s.depth_gain

    def _depth_deadzone(self, s: "MouseSettings", model: bool) -> float:
        return max(s.depth_deadzone, MODEL_DEPTH_DEADZONE) if model else s.depth_deadzone

    def _new_cursor(self) -> None:
        mc = self.settings.smoothing
        self.cursor = _Cursor(OneEuro(mc, 3.0, 1.0), OneEuro(mc, 3.0, 1.0), np.zeros(2))
        self.depth_cursor = DepthCursor()

    def configure(self, s: MouseSettings) -> None:
        old = self.settings
        switch = (old.mode, old.object_id, old.hand_control, old.mirror, old.invert_y,
                  old.pen_relative, old.coordinate_mode, old.object_hybrid, old.hybrid_hand_control) != (s.mode, s.object_id, s.hand_control, s.mirror,
                                       s.invert_y, s.pen_relative, s.coordinate_mode, s.object_hybrid, s.hybrid_hand_control)
        if switch:
            self.sink.release_all()
        self.settings = s
        if switch or old.object_tap != s.object_tap or old.hand_clicks != s.hand_clicks:
            self.object_tap.reset()
        if not switch and s.mode == 'object' and s.object_hybrid and (old.pinch_on != s.pinch_on or old.hybrid_detach != s.hybrid_detach):
            self.hybrid.reset()
            self.hybrid_xy.reset()
            self.depth_cursor.reset()
            self.sink.button("left", False)
            self.sink.button("right", False)
        if switch or old.pinch_on != s.pinch_on:
            self.gestures = GestureRecognizer(GestureConfig(pinch_on=s.pinch_on, pinch_off=s.pinch_on * 1.5))
            if not switch:
                self.sink.button("left", False)
                self.sink.button("right", False)
        self.gestures.cfg.scroll_gain = s.scroll_gain
        self.tip_clicks.cfg.drop = s.tip_drop
        self.tip_clicks.cfg.touch = s.object_tap_distance
        if old.finger_track != s.finger_track:
            self.tip_clicks.reset()
        self.finger_clicks.cfg.press = s.finger_press
        self.finger_clicks.cfg.release = min(.9, s.finger_press + .15)
        self.finger_clicks.cfg.touch_gap = s.object_tap_distance
        if switch or old.hand_click_style != s.hand_click_style:
            self.finger_clicks.reset()
            self.tip_clicks.reset()
            self.finger_hands_t = None
            if not switch:
                self.sink.button("left", False)
                self.sink.button("right", False)
        if not switch and old.desk_correct != s.desk_correct:
            self.depth_cursor.reset()  # 기준 좌표계가 바뀌므로 상대 이동을 새로 시작 (커서 점프 방지)
        if switch or old.smoothing != s.smoothing:
            self._new_cursor()
        if switch:
            self.hybrid.reset()
            self.hybrid_xy.reset()
            self.last_palm = None
            self.touchpad.reset()
            self.pen_last = None

    def set_surface(self, surface: TouchSurface | None) -> None:
        self.touch_surface = surface
        self.touchpad.reset()
        self.pen_last = None
        self.depth_cursor.reset()
        self.hybrid_xy.reset()

    def emergency_stop(self) -> None:
        self.sink.release_all()
        self.configure(self.settings.model_copy(update={"mode": "off"}))

    # ---------------------------------------------------------------- 매 프레임
    def update(self, t: float, hands: HandFrame | None, obj_center: tuple[float, float] | None,
               obj_visible: bool, obj_pressed: bool = False,
               ext_buttons: dict[str, bool] | None = None,
               obj_is_pen: bool = False, obj_scale: float = 1.0,
               obj_box: tuple[float, float, float, float] | None = None,
               obj_foot: tuple[float, float] | None = None,
               tips: TipFrame | None = None) -> dict[str, Any]:
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
        if s.mode == 'object' and s.object_hybrid and not obj_is_pen:
            return self._update_hybrid(t, hands, obj_center, obj_visible, obj_scale, obj_box, obj_foot, ext)
        fresh = hands is not None and t - hands.t < HAND_STALE_S
        hand = self._pick_hand(hands.hands if fresh else [], obj_center)  # type: ignore[union-attr]
        # 물체 모드에서는 쥔 손이 집기·스크롤로 오인식되므로 쓰지 않는다. 대신 검지·중지를 내려 물체에 닿으면 클릭.
        finger_style = (s.mode == "hand" and s.hand_click_style == "finger" and s.hand_control != "touchpad") or (s.mode == "object" and s.hand_clicks and not obj_is_pen)
        g = self.gestures.update(hand if s.mode == "hand" and not finger_style else None, t)
        fc = self.finger_out
        self.tip_mode = False
        tip_out = None
        if finger_style and s.mode == "object" and s.finger_track and not obj_is_pen:
            # 끝점 추적 방식: 점을 영상에서 직접 따라가므로 손을 오므려 랜드마크가 틀려도 계속 판정한다.
            tip_out = self.tip_clicks.update(t, tips, obj_box if obj_visible else None)
            self.tip_mode = self.tip_clicks.ready_any
        if finger_style:
            # 랜드마크 방식은 항상 함께 돌려 둔다: 끝점 기준이 아직 없는 손가락만 이쪽 결과를 쓴다 (예: 검지만 점이 안 잡힌 경우)
            if hand is None:
                self.finger_hands_t = None
                self.finger_clicks.reset()
                lm = self.finger_clicks.update(None, t)
            elif hands is not None and hands.t != self.finger_hands_t:
                self.finger_hands_t = hands.t
                box = obj_box if s.mode == "object" and obj_visible else None
                if s.mode == "object" and box is None:
                    lm = self.finger_clicks.update(None, t)  # 물체가 안 보이면 누르지 않는다
                else:
                    lm = self.finger_clicks.update(hand, hands.t, box)
            else:
                lm = self.finger_lm
            self.finger_lm = lm
            fc = lm
            if tip_out is not None and self.tip_mode:
                use_mid, use_idx = self.tip_clicks.has_rest("middle"), self.tip_clicks.has_rest("index")
                fc = FingerClickOutput(tip_out.left if use_mid else lm.left, tip_out.right if use_idx else lm.right,
                                       tip_out.freeze or lm.freeze, tip_out.approaching or lm.approaching,
                                       tip_out.ratios, tip_out.touching)
            self.finger_out = fc
            if g.features is None and hand is not None:
                g.features = features(hand, self.gestures.cfg)
            g.freeze = fc.freeze
            g.left, g.right = fc.left, fc.right
            g.gesture = "left" if fc.left else "right" if fc.right else "approach" if fc.approaching else "move"
        tap = False

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
                smoothing=s.smoothing, gain=self._depth_gain(s, self.model_depth), freeze=g.freeze and g.gesture != "scroll",
                deadzone=self._depth_deadzone(s, self.model_depth),
                perspective=s.depth_perspective and not self.model_depth)
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
            "depth_source": "desk" if self.depth_cursor.plane else "model" if self.model_depth else "size",
            "perspective_active": bool(depth_active and not self.depth_cursor.plane and s.depth_perspective),
            "touching": touch,
            "surface_mode": None if self.touch_surface is None else self.touch_surface.mode,
            "gesture": "object-tap" if tap else "pen" if pressed and not g.left else g.gesture,
            "freeze": g.freeze,
            "tip_mode": self.tip_mode,
            "tip_debug": {n: self.tip_clicks.debug(n) for n in ("index", "middle")} if self.tip_mode else None,
            "pinch_index": None if f is None else round(f.pinch_index, 3),
            "pinch_middle": None if f is None else round(f.pinch_middle, 3),
            "pinch_on": s.pinch_on,
        }
        return self.status

    def _update_hybrid(self, t: float, hands: HandFrame | None, center: tuple[float, float] | None,
                       visible: bool, scale: float, box: tuple[float, float, float, float] | None,
                       foot: tuple[float, float] | None, ext: dict[str, bool]) -> dict[str, Any]:
        s, route = self.settings, self.hybrid
        fresh = hands is not None and 0 <= t - hands.t < .15
        hand = route.pick(hands.hands, center, t) if fresh else None
        g = route.update(hand, hands.t if fresh and hand is not None else None, t,
                         box if visible else None, detach=s.hybrid_detach, pinch=s.pinch_on,
                         external_down=any(ext.values()))
        if route.changed:
            self.depth_cursor.reset()
            self.hybrid_xy.reset()
        freeze = route.source == 'hand' or route.changed or route.blocked or g.freeze
        point = None
        source_scale = scale
        control = s.coordinate_mode
        if route.source == 'object':
            if visible and center is not None:
                point = np.asarray(center)
                if control == 'depth' and self._depth_surface() is not None and self._depth_surface().mode == 'quad' and foot is not None:
                    point = np.asarray(foot)
        if control == 'depth':
            model = self.model_depth and route.source == 'object'   # 하이브리드의 맨손 단계는 손바닥 크기를 쓴다
            dx, dy = self.depth_cursor.update(point, source_scale, t,
                self._depth_surface() if route.source == 'object' else None,
                smoothing=s.smoothing, gain=self._depth_gain(s, model), freeze=freeze,
                deadzone=self._depth_deadzone(s, model), perspective=s.depth_perspective and not model)
        else:
            # Object XY stays relative, preserving the parked cursor after a hand click.
            xy = point
            if point is not None:
                region = s.object_region
                xy = np.array([(point[0] - region[0]) / (region[2] - region[0]),
                               (point[1] - region[1]) / (region[3] - region[1])])
            sf = TouchSurface.overhead()
            dx, dy = self.hybrid_xy.update(xy, 1., t, sf, smoothing=s.smoothing,
                gain=1., freeze=freeze, deadzone=s.depth_deadzone)
            dy = -dy  # DepthCursor maps a desk plane's near direction to screen up; XY follows video y.
        if dx or dy:
            self.sink.move_by(dx * s.depth_sensitivity * self._sx(), dy * s.depth_sensitivity * self._sy())
        # Click-only: one immediate down/up pair per pinch onset, never hold a button.
        for name, pressed in (('left', g.left), ('right', g.right)):
            logical = route.source == 'hand' and pressed
            if logical and not route.click_latched[name] and not ext.get(name):
                self.sink.button(name, True)
                self.sink.button(name, False)
            route.click_latched[name] = logical
            self.sink.button(name, bool(ext.get(name)))
        self.status = {'mode': 'object', 'hybrid': True, 'cursor_source': route.source,
            'hybrid_pending': route.pending, 'hybrid_armed': route.armed,
            'hybrid_gap': None if route.gap is None else round(route.gap, 2),
            'hand_visible': hand is not None, 'cursor_active': point is not None and not freeze,
            'coordinate_mode': 'depth' if control == 'depth' else 'image',
            'gesture': g.gesture if route.source == 'hand' else 'move', 'freeze': freeze,
            'pinch_index': None if g.features is None else round(g.features.pinch_index, 3),
            'pinch_middle': None if g.features is None else round(g.features.pinch_middle, 3),
            'pinch_on': s.pinch_on, 'tip_mode': False}
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

        물체 모드에서는 물체에 가장 가까운 손(물체를 쥔 손)을 고른다."""
        if not hands:
            self.last_palm = None
            return None
        palms = [h.points[[0, 5, 9, 13, 17]].mean(0) for h in hands]
        if self.settings.mode == "object" and obj_center is not None and len(hands) > 1:
            i = int(np.argmin([np.linalg.norm(p - np.asarray(obj_center)) for p in palms]))
        elif self.last_palm is not None:
            i = int(np.argmin([np.linalg.norm(p - self.last_palm) for p in palms]))
        else:
            i = int(np.argmax([h.score for h in hands]))
        self.last_palm = palms[i]
        return hands[i]
