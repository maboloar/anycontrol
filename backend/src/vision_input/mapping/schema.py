"""매핑 프로필 스키마: 무엇(입력)을 어디(출력)로, 어떻게(변환) 보낼지.

사람이 JSON을 직접 읽고 쓰거나 앱의 프로필 편집기에서 저장할 때 동일한 스키마로 검증한다.

물체는 이름으로 가리킨다 (id 는 실행마다 바뀌므로 저장한 프로필이 다시 쓰이려면 이름이 낫다). "#3" 처럼 쓰면 id.
"""

from __future__ import annotations

import re
import math
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

AxisName = Literal["x", "y", "depth", "angle", "stretch", "contact"]
AXIS_HELP = ("x: 좌우 이동(프레임 폭 비율, 오른쪽 +). y: 상하 이동(프레임 높이 비율, 아래 +). "
             "depth: log(크기/중립), 카메라 쪽으로 오면 +. angle: 화면상 회전(도, 시계방향 +). "
             "stretch: log(길쭉함/중립), 옆에서 본 책상 위 회전. contact: 바닥 접촉선 이동(아래 +). "
             "desk_x/desk_z/desk_yaw: 카메라 보정 후 책상 좌표(좌우 m 비율, 앞뒤, 책상 위 회전 도)")
DeskAxisName = Literal["desk_x", "desk_z", "desk_yaw"]

# W3C Gamepad API standard 레이아웃 (Xbox 배치). 트리거는 아날로그(0..1)라 축으로 둔다.
GamepadAxis = Literal["left_x", "left_y", "right_x", "right_y", "lt", "rt"]
GAMEPAD_AXES: tuple[str, ...] = ("left_x", "left_y", "right_x", "right_y", "lt", "rt")
UNIPOLAR_AXES = frozenset({"lt", "rt"})
GamepadButton = Literal["a", "b", "x", "y", "lb", "rb", "back", "start", "ls", "rs",
                        "up", "down", "left", "right", "home"]
GAMEPAD_BUTTONS: tuple[str, ...] = ("a", "b", "x", "y", "lb", "rb", "back", "start", "ls", "rs",
                                    "up", "down", "left", "right", "home")
KEY_RE = re.compile(r"^([a-z0-9]|space|enter|tab|escape|backspace|shift|ctrl|alt|meta|"
                    r"arrowup|arrowdown|arrowleft|arrowright|f([1-9]|1[0-2]))$")
HandGesture = Literal["pinch", "pinch_middle"]


# ---------------------------------------------------------------- 입력
class ObjectAxisInput(BaseModel):
    """추적 중인 물체의 연속 축 값."""

    source: Literal["object"] = "object"
    object: str = Field(min_length=1, max_length=40, description="물체 이름 (또는 '#id')")
    axis: AxisName | DeskAxisName = Field(description=AXIS_HELP)


class ObjectVisibleInput(BaseModel):
    """물체가 보이면 1, 가려지거나 놓치면 0."""

    source: Literal["visible"] = "visible"
    object: str = Field(min_length=1, max_length=40)


class PenContactInput(BaseModel):
    """펜으로 등록한 물체의 펜촉이 책상에 닿으면 1."""

    source: Literal["pen"] = "pen"
    object: str = Field(min_length=1, max_length=40)


class HandInput(BaseModel):
    """손 제스처. pinch = 엄지+검지 집기, pinch_middle = 엄지+가운뎃손가락 집기 (누르면 1)."""

    source: Literal["hand"] = "hand"
    gesture: HandGesture = "pinch"


Input = Annotated[ObjectAxisInput | ObjectVisibleInput | PenContactInput | HandInput, Field(discriminator="source")]


# ---------------------------------------------------------------- 출력
class GamepadAxisOutput(BaseModel):
    """가상 게임패드 축. 스틱은 -1..1 (left_y 는 아래 +), 트리거 lt/rt 는 0..1."""

    target: Literal["gamepad_axis"] = "gamepad_axis"
    axis: GamepadAxis


class GamepadButtonOutput(BaseModel):
    target: Literal["gamepad_button"] = "gamepad_button"
    button: GamepadButton


class KeyOutput(BaseModel):
    """키 누름. 소문자 한 글자, 숫자, 또는 space/enter/tab/escape/backspace/shift/ctrl/alt/meta/arrow*/f1..f12."""

    target: Literal["key"] = "key"
    key: str = Field(min_length=1, max_length=12)

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        v = v.strip().lower()
        if not KEY_RE.match(v):
            raise ValueError(f"지원하지 않는 키: {v}")
        return v


class MouseOutput(BaseModel):
    """마우스. move_x/move_y = 커서 속도(-1..1 → 초당 화면 폭·높이 비율), scroll = 초당 스크롤 줄 수 비율,
    left/right = 버튼."""

    target: Literal["mouse"] = "mouse"
    action: Literal["move_x", "move_y", "scroll", "left", "right"]


Output = Annotated[GamepadAxisOutput | GamepadButtonOutput | KeyOutput | MouseOutput, Field(discriminator="target")]


def output_kind(o: GamepadAxisOutput | GamepadButtonOutput | KeyOutput | MouseOutput) -> str:
    """bipolar(-1..1) | unipolar(0..1) | digital(on/off)."""
    if isinstance(o, GamepadAxisOutput):
        return "unipolar" if o.axis in UNIPOLAR_AXES else "bipolar"
    if isinstance(o, MouseOutput):
        return "bipolar" if o.action in ("move_x", "move_y", "scroll") else "digital"
    return "digital"


def output_key(o: GamepadAxisOutput | GamepadButtonOutput | KeyOutput | MouseOutput) -> str:
    if isinstance(o, GamepadAxisOutput):
        return f"axis:{o.axis}"
    if isinstance(o, GamepadButtonOutput):
        return f"button:{o.button}"
    if isinstance(o, KeyOutput):
        return f"key:{o.key}"
    return f"mouse:{o.action}"


# ---------------------------------------------------------------- 변환
class Transform(BaseModel):
    """입력 값 → 출력 값.

    1) mode: absolute = 입력 값 그대로, velocity = 입력의 초당 변화량
    2) range [lo, hi]: 이 구간을 출력 전체에 대응. 양방향 출력(스틱)은 lo→-1, hi→+1, 가운데→0.
       한방향 출력(트리거·버튼·키)은 lo→0, hi→1. 예: angle 을 [-45, 45] 로 두면 45° 기울이면 끝까지.
    3) invert, deadzone(중립 근처 무시, 출력은 끊김 없이 다시 늘린다), curve(expo 는 가운데를 둔하게)
    4) 버튼·키: 한방향 값이 on 이상이면 누름, off 이하이면 뗌 (히스테리시스)
    5) smoothing_ms: 1차 저역 통과 시간 상수 (0 = 없음)
    6) on_lost: 입력이 없을 때(물체가 가려짐·놓침) hold = 마지막 값 유지, center = lost_ms 동안 중립으로, release = 즉시 중립
    """

    mode: Literal["absolute", "velocity"] = "absolute"
    range: list[float] = Field(default_factory=lambda: [-1.0, 1.0], min_length=2, max_length=2)
    invert: bool = False
    deadzone: float = Field(0.05, ge=0.0, le=0.9)
    curve: Literal["linear", "expo"] = "linear"
    expo: float = Field(0.5, ge=0.0, le=1.0, description="curve=expo 일 때 세기")
    on: float = Field(0.6, ge=0.0, le=1.0, description="버튼·키 누름 문턱 (한방향 값)")
    off: float = Field(0.4, ge=0.0, le=1.0, description="버튼·키 뗌 문턱 (on 보다 작게)")
    smoothing_ms: float = Field(0.0, ge=0.0, le=1000.0)
    on_lost: Literal["hold", "center", "release"] = "center"
    lost_ms: float = Field(300.0, ge=0.0, le=5000.0)

    @model_validator(mode="after")
    def _check(self) -> Transform:
        lo, hi = self.range
        if not all(math.isfinite(v) for v in (lo, hi)) or not hi > lo:
            raise ValueError("range 는 [작은 값, 큰 값] 이어야 합니다")
        if self.off > self.on:
            raise ValueError("off 는 on 보다 클 수 없습니다")
        return self


class Mapping(BaseModel):
    id: str = Field(min_length=1, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    label: str = Field("", max_length=60, description="사람이 읽는 설명 (예: '조향')")
    enabled: bool = True
    input: Input
    output: Output
    transform: Transform = Field(default_factory=Transform)


class Profile(BaseModel):
    """매핑 프로필."""

    version: Literal[1] = 1
    name: str = Field("기본", min_length=1, max_length=40)
    description: str = Field("", max_length=500)
    mappings: list[Mapping] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def _unique(self) -> Profile:
        ids = [m.id for m in self.mappings]
        if len(ids) != len(set(ids)):
            raise ValueError("매핑 id 가 겹칩니다")
        return self


def warnings(p: Profile, object_names: list[str] | None = None) -> list[str]:
    """저장은 되지만 사용자가 알아야 할 것들."""
    out: list[str] = []
    seen: dict[str, list[str]] = {}
    for m in p.mappings:
        if m.enabled:
            seen.setdefault(output_key(m.output), []).append(m.label or m.id)
        obj = getattr(m.input, "object", None)
        if object_names is not None and obj is not None and not obj.startswith("#") and obj not in object_names:
            out.append(f"'{m.label or m.id}': '{obj}' 이름의 물체가 없습니다 (등록하거나 이름을 맞추세요)")
        kind = output_kind(m.output)
        if kind == "digital" and isinstance(m.input, ObjectAxisInput) and m.transform.mode == "absolute" \
                and m.transform.range[0] < 0 < m.transform.range[1]:
            out.append(f"'{m.label or m.id}': 버튼 출력인데 range 가 중립(0)을 가운데에 두고 있어 "
                       f"중립 위치에서 절반쯤 눌린 값이 됩니다. 예: [0, 0.2]")
    for k, names in seen.items():
        if len(names) > 1:
            how = "하나라도 누르면 눌림" if not k.startswith(("axis:", "mouse:move", "mouse:scroll")) else "값을 더합니다"
            out.append(f"{k} 에 매핑 {len(names)}개 ({', '.join(names)}): {how}")
    return out
