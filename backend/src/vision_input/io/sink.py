"""출력 싱크. 지금은 가상 싱크(웹앱 데모)만 있다. 실제 HID(CGEvent, RP2040 게임패드 등)는 같은 인터페이스로 붙인다.

계약 (tests/test_sink.py)
- release_all() 뒤에는 눌린 버튼·키가 하나도 없고 게임패드 축은 중립이다. 긴급 정지·모드 전환·소스 변경 때 부른다.
- 상태가 바뀐 버튼·키만 이벤트로 남긴다 (같은 값을 매 프레임 넣어도 이벤트가 쌓이지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

GAMEPAD_AXES = ("left_x", "left_y", "right_x", "right_y", "lt", "rt")
GAMEPAD_BUTTONS = ("a", "b", "x", "y", "lb", "rb", "back", "start", "ls", "rs", "up", "down", "left", "right", "home")


class OutputSink(Protocol):
    def move(self, x: float, y: float) -> None:
        """커서 절대 위치. 화면 정규화 좌표 0..1."""

    def move_by(self, dx: float, dy: float) -> None:
        """커서 상대 이동. 화면 비율."""

    def button(self, name: str, down: bool) -> None:
        """마우스 버튼. name: left | right"""

    def scroll(self, lines: float) -> None:
        """+ 는 아래로."""

    def key(self, name: str, down: bool) -> None:
        """키보드 키 (mapping.schema.KEY_RE 이름)."""

    def gamepad(self, axes: dict[str, float], buttons: dict[str, bool]) -> None:
        """게임패드 전체 상태. 스틱 -1..1, 트리거 0..1."""

    def release_all(self) -> None:
        """긴급 정지·모드 전환 시 눌린 것을 모두 놓는다."""


@dataclass
class VirtualSink:
    """브라우저 가상 데스크톱·게임패드로 보낼 상태를 모은다. 이벤트는 snapshot 때 비운다."""

    x: float = 0.5
    y: float = 0.5
    buttons: dict[str, bool] = field(default_factory=lambda: {"left": False, "right": False})
    scroll_acc: float = 0.0
    keys: set[str] = field(default_factory=set)
    pad_axes: dict[str, float] = field(default_factory=lambda: dict.fromkeys(GAMEPAD_AXES, 0.0))
    pad_buttons: dict[str, bool] = field(default_factory=lambda: dict.fromkeys(GAMEPAD_BUTTONS, False))
    events: list[dict] = field(default_factory=list)
    key_events: list[dict] = field(default_factory=list)

    def move(self, x: float, y: float) -> None:
        self.x, self.y = min(1.0, max(0.0, x)), min(1.0, max(0.0, y))

    def move_by(self, dx: float, dy: float) -> None:
        self.move(self.x + dx, self.y + dy)

    def button(self, name: str, down: bool) -> None:
        if self.buttons.get(name) != down:
            self.buttons[name] = down
            self.events.append({"type": "down" if down else "up", "button": name,
                                "x": round(self.x, 4), "y": round(self.y, 4)})

    def scroll(self, lines: float) -> None:
        if lines:
            self.scroll_acc += lines

    def key(self, name: str, down: bool) -> None:
        if (name in self.keys) != down:
            (self.keys.add if down else self.keys.discard)(name)
            self.key_events.append({"type": "down" if down else "up", "key": name})

    def set_keys(self, pressed: set[str]) -> None:
        for k in sorted(self.keys - pressed):
            self.key(k, False)
        for k in sorted(pressed - self.keys):
            self.key(k, True)

    def gamepad(self, axes: dict[str, float], buttons: dict[str, bool]) -> None:
        for a in GAMEPAD_AXES:
            lo = 0.0 if a in ("lt", "rt") else -1.0
            self.pad_axes[a] = max(lo, min(1.0, float(axes.get(a, 0.0))))
        for b in GAMEPAD_BUTTONS:
            self.pad_buttons[b] = bool(buttons.get(b, False))

    def release_all(self) -> None:
        for b in list(self.buttons):
            self.button(b, False)
        self.set_keys(set())
        self.gamepad({}, {})
        self.scroll_acc = 0.0

    def snapshot(self) -> dict:
        ev, self.events = self.events, []
        sc, self.scroll_acc = self.scroll_acc, 0.0
        return {"x": round(self.x, 4), "y": round(self.y, 4), "left": self.buttons["left"],
                "right": self.buttons["right"], "scroll": round(sc, 3), "events": ev}

    def controller_snapshot(self) -> dict:
        ev, self.key_events = self.key_events, []
        return {"axes": {k: round(v, 4) for k, v in self.pad_axes.items()},
                "buttons": dict(self.pad_buttons), "keys": sorted(self.keys), "key_events": ev}
