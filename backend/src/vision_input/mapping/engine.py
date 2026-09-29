"""매핑 엔진: 매 프레임 입력 스냅샷 → 가상 컨트롤러 상태.

순수 로직이다 (카메라·모델 없음). 엔진 스레드에서만 부른다.
합치기 규칙: 같은 아날로그 출력은 더한 뒤 범위로 자르고, 버튼·키는 하나라도 눌리면 눌림.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .schema import (
    GAMEPAD_AXES,
    GAMEPAD_BUTTONS,
    UNIPOLAR_AXES,
    GamepadAxisOutput,
    GamepadButtonOutput,
    HandInput,
    KeyOutput,
    Mapping,
    MouseOutput,
    ObjectAxisInput,
    ObjectVisibleInput,
    PenContactInput,
    Profile,
    Transform,
    output_kind,
)


@dataclass
class ObjectSnap:
    id: int
    name: str
    visible: bool
    axes: dict[str, float | None]
    pen_contact: bool | None = None


@dataclass
class InputSnapshot:
    t: float
    objects: list[ObjectSnap] = field(default_factory=list)
    hand: dict[str, bool] | None = None      # {"pinch": bool, "pinch_middle": bool} 또는 손 없음(None)

    def find(self, ref: str) -> ObjectSnap | None:
        if ref.startswith("#"):
            try:
                oid = int(ref[1:])
            except ValueError:
                return None
            return next((o for o in self.objects if o.id == oid), None)
        return next((o for o in self.objects if o.name == ref), None)


@dataclass
class ControllerState:
    axes: dict[str, float] = field(default_factory=lambda: dict.fromkeys(GAMEPAD_AXES, 0.0))
    buttons: dict[str, bool] = field(default_factory=lambda: dict.fromkeys(GAMEPAD_BUTTONS, False))
    keys: set[str] = field(default_factory=set)
    mouse_move: tuple[float, float] = (0.0, 0.0)   # -1..1 속도
    mouse_scroll: float = 0.0
    mouse_buttons: dict[str, bool] = field(default_factory=lambda: {"left": False, "right": False})

    def to_json(self) -> dict[str, Any]:
        return {"axes": {k: round(v, 4) for k, v in self.axes.items()}, "buttons": dict(self.buttons),
                "keys": sorted(self.keys), "mouse": {"move": [round(self.mouse_move[0], 4), round(self.mouse_move[1], 4)],
                                                    "scroll": round(self.mouse_scroll, 4), **self.mouse_buttons}}


# ---------------------------------------------------------------- 변환 (순수 함수)
def shape(v: float, tr: Transform, kind: str) -> float:
    """range·invert·deadzone·curve 적용. bipolar → -1..1, 그 외 → 0..1."""
    lo, hi = tr.range
    if kind == "bipolar":
        c, half = 0.5 * (lo + hi), 0.5 * (hi - lo)
        n = max(-1.0, min(1.0, (v - c) / half))
        if tr.invert:
            n = -n
        a = abs(n)
        a = 0.0 if a <= tr.deadzone else (a - tr.deadzone) / (1 - tr.deadzone)
        if tr.curve == "expo":
            a = (1 - tr.expo) * a + tr.expo * a ** 3
        return math.copysign(a, n)
    n = max(0.0, min(1.0, (v - lo) / (hi - lo)))
    if tr.invert:
        n = 1.0 - n
    n = 0.0 if n <= tr.deadzone else (n - tr.deadzone) / (1 - tr.deadzone)
    if tr.curve == "expo":
        n = (1 - tr.expo) * n + tr.expo * n ** 3
    return n


@dataclass
class _Run:
    """매핑 하나의 실행 상태."""

    prev_raw: float | None = None
    prev_t: float | None = None
    vel: float = 0.0
    value: float = 0.0           # 출력 (스무딩 후). digital 은 0/1
    pressed: bool = False
    lost_since: float | None = None
    lost_from: float = 0.0


@dataclass
class MappingLive:
    id: str
    raw: float | None
    value: float
    active: bool


class MappingEngine:
    def __init__(self, profile: Profile | None = None) -> None:
        self.profile = profile or Profile()
        self.runs: dict[str, _Run] = {}
        self.state = ControllerState()
        self.live: list[MappingLive] = []

    def set_profile(self, p: Profile) -> None:
        self.profile = p
        self.runs = {}
        self.state = ControllerState()
        self.live = []

    def reset(self) -> None:
        self.set_profile(self.profile)

    @property
    def needs_hands(self) -> bool:
        return any(m.enabled and isinstance(m.input, HandInput) for m in self.profile.mappings)

    # -------------------------------------------------------------- 매 프레임
    def update(self, snap: InputSnapshot) -> ControllerState:
        st = ControllerState()
        mx = my = sc = 0.0
        live = []
        for m in self.profile.mappings:
            if not m.enabled:
                continue
            run = self.runs.setdefault(m.id, _Run())
            raw = self._read(m, snap)
            kind = output_kind(m.output)
            val = self._value(m, run, raw, kind, snap.t)
            live.append(MappingLive(m.id, None if raw is None else round(raw, 5), round(val, 4), raw is not None))
            o = m.output
            if isinstance(o, GamepadAxisOutput):
                st.axes[o.axis] += val
            elif isinstance(o, GamepadButtonOutput):
                st.buttons[o.button] = st.buttons[o.button] or val >= 0.5
            elif isinstance(o, KeyOutput):
                if val >= 0.5:
                    st.keys.add(o.key)
            elif isinstance(o, MouseOutput):
                if o.action == "move_x":
                    mx += val
                elif o.action == "move_y":
                    my += val
                elif o.action == "scroll":
                    sc += val
                else:
                    st.mouse_buttons[o.action] = st.mouse_buttons[o.action] or val >= 0.5
        for a in st.axes:
            lo = 0.0 if a in UNIPOLAR_AXES else -1.0
            st.axes[a] = max(lo, min(1.0, st.axes[a]))
        st.mouse_move = (max(-1.0, min(1.0, mx)), max(-1.0, min(1.0, my)))
        st.mouse_scroll = max(-1.0, min(1.0, sc))
        self.state, self.live = st, live
        return st

    def _read(self, m: Mapping, snap: InputSnapshot) -> float | None:
        i = m.input
        if isinstance(i, HandInput):
            if snap.hand is None:
                return None
            return 1.0 if snap.hand.get(i.gesture) else 0.0
        o = snap.find(i.object)
        if o is None:
            return None
        if isinstance(i, ObjectVisibleInput):
            return 1.0 if o.visible else 0.0   # 보임 여부 자체가 입력이라 '없음'이 아니다
        if not o.visible:
            return None
        if isinstance(i, PenContactInput):
            return None if o.pen_contact is None else (1.0 if o.pen_contact else 0.0)
        assert isinstance(i, ObjectAxisInput)
        return o.axes.get(i.axis)

    def _value(self, m: Mapping, run: _Run, raw: float | None, kind: str, t: float) -> float:
        tr = m.transform
        dt = None if run.prev_t is None else max(1e-3, t - run.prev_t)
        if raw is None:
            run.prev_raw, run.prev_t = None, t
            if tr.on_lost == "hold" and kind != "digital":
                return run.value
            if run.lost_since is None:
                run.lost_since, run.lost_from = t, run.value
            run.vel = 0.0
            if kind == "digital" or tr.on_lost == "release" or tr.lost_ms <= 0:
                run.value, run.pressed = 0.0, False
            else:  # center: lost_ms 동안 선형으로 중립까지
                k = max(0.0, 1.0 - (t - run.lost_since) / (tr.lost_ms / 1000.0))
                run.value = run.lost_from * k
            return run.value
        run.lost_since = None
        x = raw
        if tr.mode == "velocity":
            if run.prev_raw is not None and dt is not None:
                a = 1.0 - math.exp(-dt / 0.05)  # 속도는 미분이라 잡음이 크다: 50ms 로 기본 평활
                run.vel += a * ((raw - run.prev_raw) / dt - run.vel)
            x = run.vel
        run.prev_raw, run.prev_t = raw, t
        if kind == "digital":
            u = shape(x, tr, "unipolar")
            run.pressed = u >= tr.on if not run.pressed else u > tr.off
            run.value = 1.0 if run.pressed else 0.0
            return run.value
        target = shape(x, tr, kind)
        if tr.smoothing_ms > 0 and dt is not None:
            a = 1.0 - math.exp(-dt / (tr.smoothing_ms / 1000.0))
            run.value += a * (target - run.value)
        else:
            run.value = target
        return run.value

    def live_json(self) -> list[dict[str, Any]]:
        return [{"id": v.id, "raw": v.raw, "value": v.value, "active": v.active} for v in self.live]
