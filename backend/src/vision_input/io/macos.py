"""실제 macOS 입력 (마우스·키보드): Quartz CGEventPost.

- 시스템 전체에 진짜 마우스·키보드처럼 들어간다 (kCGHIDEventTap). 게임패드는 드라이버 없이는 만들 수 없어 가상 전용.
- 손쉬운 사용(Accessibility) 권한이 필요하다. 권한은 서버를 실행한 프로세스(터미널 앱 등)에 준다.
- 안전 장치 (RealOutput)
  - 기본은 꺼짐. 켜면 ARM_S 초 카운트다운 뒤에 실제로 켜진다 (위험한 곳에서 손을 뗄 시간).
  - 어디서든 ESC: 브라우저가 포커스를 잃어도 하드웨어 ESC 상태를 매 프레임 확인해 즉시 끈다.
  - 끄거나 긴급 정지하면 눌린 버튼·키를 모두 놓는다.

게시는 Backend 로 분리했다 (테스트는 FakeBackend 로 커서를 건드리지 않는다).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import functools
import logging
import math
import subprocess
import time
import threading
from dataclasses import dataclass, field
from typing import Any, Protocol

log = logging.getLogger(__name__)

# macOS 가상 키 코드 (ANSI 배열, Carbon kVK_*). mapping.schema.KEY_RE 의 이름과 맞춘다.
KEYCODES: dict[str, int] = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12, "w": 13,
    "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "9": 25, "7": 26,
    "8": 28, "0": 29, "o": 31, "u": 32, "i": 34, "p": 35, "enter": 36, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
    "tab": 48, "space": 49, "backspace": 51, "escape": 53, "meta": 55, "shift": 56, "alt": 58, "ctrl": 59,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100, "f9": 101, "f10": 109,
    "f11": 103, "f12": 111, "arrowleft": 123, "arrowright": 124, "arrowdown": 125, "arrowup": 126,
}
ESCAPE = 53
# 수식 키를 누르고 있는 동안 다른 키 이벤트에 붙일 플래그 (kCGEventFlagMask*)
MODIFIER_FLAGS = {"shift": 1 << 17, "ctrl": 1 << 18, "alt": 1 << 19, "meta": 1 << 20}
DOUBLE_CLICK_S = 0.35
DOUBLE_CLICK_PX = 6.0
SCROLL_PX_PER_LINE = 12.0


# ---------------------------------------------------------------- 게시 계층
class Backend(Protocol):
    def screen(self) -> tuple[float, float, float, float]: ...
    def mouse(self, kind: str, x: float, y: float, button: str, clicks: int) -> None:
        """kind: move | down | up | drag. button: left | right."""
    def key(self, code: int, down: bool, flags: int) -> None: ...
    def scroll(self, dy_px: int) -> None:
        """+ 는 위로 (macOS 휠 부호)."""
    def escape_down(self) -> bool: ...


class QuartzBackend:
    """진짜 게시. 권한이 없으면 macOS 가 조용히 무시하므로 켜기 전에 trusted() 로 확인한다."""

    def __init__(self) -> None:
        import Quartz

        self.Q = Quartz

    def screen(self) -> tuple[float, float, float, float]:
        b = self.Q.CGDisplayBounds(self.Q.CGMainDisplayID())
        return float(b.origin.x), float(b.origin.y), float(b.size.width), float(b.size.height)

    def mouse(self, kind: str, x: float, y: float, button: str, clicks: int) -> None:
        Q = self.Q
        left = button == "left"
        t = {("move", True): Q.kCGEventMouseMoved, ("move", False): Q.kCGEventMouseMoved,
             ("down", True): Q.kCGEventLeftMouseDown, ("down", False): Q.kCGEventRightMouseDown,
             ("up", True): Q.kCGEventLeftMouseUp, ("up", False): Q.kCGEventRightMouseUp,
             ("drag", True): Q.kCGEventLeftMouseDragged, ("drag", False): Q.kCGEventRightMouseDragged}[(kind, left)]
        ev = Q.CGEventCreateMouseEvent(None, t, (x, y), Q.kCGMouseButtonLeft if left else Q.kCGMouseButtonRight)
        if kind in ("down", "up"):
            Q.CGEventSetIntegerValueField(ev, Q.kCGMouseEventClickState, clicks)
        Q.CGEventPost(Q.kCGHIDEventTap, ev)

    def key(self, code: int, down: bool, flags: int) -> None:
        Q = self.Q
        ev = Q.CGEventCreateKeyboardEvent(None, code, down)
        Q.CGEventSetFlags(ev, flags)
        Q.CGEventPost(Q.kCGHIDEventTap, ev)

    def scroll(self, dy_px: int) -> None:
        Q = self.Q
        ev = Q.CGEventCreateScrollWheelEvent(None, Q.kCGScrollEventUnitPixel, 1, dy_px)
        Q.CGEventPost(Q.kCGHIDEventTap, ev)

    def escape_down(self) -> bool:
        return bool(self.Q.CGEventSourceKeyState(self.Q.kCGEventSourceStateHIDSystemState, ESCAPE))


# ---------------------------------------------------------------- 권한
@functools.cache
def _ax_lib() -> Any:
    path = ctypes.util.find_library("ApplicationServices")
    if path is None:
        return None
    lib = ctypes.cdll.LoadLibrary(path)
    lib.AXIsProcessTrusted.restype = ctypes.c_bool
    lib.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
    lib.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
    return lib


def accessibility_trusted() -> bool:
    try:
        lib = _ax_lib()
        return bool(lib and lib.AXIsProcessTrusted())
    except OSError:
        return False


def request_accessibility() -> bool:
    """권한 요청 창을 띄우고(이 프로세스를 목록에 추가) 시스템 설정의 손쉬운 사용 화면을 연다."""
    try:
        import objc
        from Foundation import NSDictionary

        lib = _ax_lib()
        if lib is not None:
            opts = NSDictionary.dictionaryWithObject_forKey_(True, "AXTrustedCheckOptionPrompt")
            if lib.AXIsProcessTrustedWithOptions(ctypes.c_void_p(objc.pyobjc_id(opts))):
                return True
    except Exception:  # 요청 창이 안 떠도 설정 화면은 연다
        log.debug("AXIsProcessTrustedWithOptions failed", exc_info=True)
    subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
                   check=False)
    return accessibility_trusted()


# ---------------------------------------------------------------- 싱크
@dataclass
class MacSink:
    """OutputSink 를 실제 마우스·키보드로. 상태가 바뀔 때만 게시한다 (매 프레임 같은 값을 넣어도 조용하다)."""

    backend: Backend
    x: float = 0.5
    y: float = 0.5
    buttons: dict[str, bool] = field(default_factory=lambda: {"left": False, "right": False})
    keys: set[str] = field(default_factory=set)
    _px: tuple[float, float] | None = None
    _scroll_rem: float = 0.0
    _last_down: dict[str, tuple[float, float, float, int]] = field(default_factory=dict)  # t, px, py, clicks

    def _to_px(self) -> tuple[float, float]:
        ox, oy, w, h = self.backend.screen()
        return ox + self.x * (w - 1), oy + self.y * (h - 1)

    def move(self, x: float, y: float) -> None:
        self.x, self.y = min(1.0, max(0.0, x)), min(1.0, max(0.0, y))
        px = self._to_px()
        if self._px is not None and math.hypot(px[0] - self._px[0], px[1] - self._px[1]) < 0.5:
            return  # 1px 도 안 움직이면 이벤트를 만들지 않는다
        self._px = px
        held = "left" if self.buttons["left"] else "right" if self.buttons["right"] else None
        self.backend.mouse("drag" if held else "move", px[0], px[1], held or "left", 0)

    def move_by(self, dx: float, dy: float) -> None:
        self.move(self.x + dx, self.y + dy)

    def button(self, name: str, down: bool) -> None:
        if name not in self.buttons or self.buttons[name] == down:
            return
        self.buttons[name] = down
        px = self._to_px()
        now = time.monotonic()
        clicks = 1
        if down:
            prev = self._last_down.get(name)
            if prev and now - prev[0] < DOUBLE_CLICK_S and math.hypot(px[0] - prev[1], px[1] - prev[2]) < DOUBLE_CLICK_PX:
                clicks = min(3, prev[3] + 1)
            self._last_down[name] = (now, px[0], px[1], clicks)
        else:
            clicks = self._last_down.get(name, (0, 0, 0, 1))[3]
        self.backend.mouse("down" if down else "up", px[0], px[1], name, clicks)

    def scroll(self, lines: float) -> None:
        # 우리 규약: + 는 아래로. macOS 휠은 + 가 위로 → 부호를 뒤집는다. 소수점은 다음 프레임으로 넘긴다
        self._scroll_rem += -lines * SCROLL_PX_PER_LINE
        n = int(self._scroll_rem)
        if n:
            self._scroll_rem -= n
            self.backend.scroll(n)

    def _flags(self) -> int:
        f = 0
        for k, m in MODIFIER_FLAGS.items():
            if k in self.keys:
                f |= m
        return f

    def key(self, name: str, down: bool) -> None:
        code = KEYCODES.get(name)
        if code is None or (name in self.keys) == down:
            return
        (self.keys.add if down else self.keys.discard)(name)
        self.backend.key(code, down, self._flags())

    def set_keys(self, pressed: set[str]) -> None:
        for k in sorted(self.keys - pressed):
            self.key(k, False)
        # 수식 키를 먼저 눌러야 다른 키에 플래그가 붙는다
        for k in sorted(pressed - self.keys, key=lambda k: (k not in MODIFIER_FLAGS, k)):
            self.key(k, True)

    def gamepad(self, axes: dict[str, float], buttons: dict[str, bool]) -> None:
        """실제 게임패드는 없다 (macOS 는 드라이버 없이 가상 HID 장치를 만들 수 없다). 가상 싱크만 받는다."""

    def release_all(self) -> None:
        for b in list(self.buttons):
            self.button(b, False)
        self.set_keys(set())
        self._scroll_rem = 0.0


# ---------------------------------------------------------------- 켜기·끄기 (안전 장치)
def synchronized(fn):
    @functools.wraps(fn)
    def run(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)
    return run


class RealOutput:
    """off → arming(카운트다운) → on. on 일 때만 MacSink 로 보낸다."""

    ARM_S = 3.0

    def __init__(self, backend_factory: Any = None, trusted: Any = accessibility_trusted) -> None:
        self._lock = threading.RLock()
        self._stop_monitor = threading.Event()
        self._monitor = None
        self.last_frame = time.monotonic()
        self._factory = backend_factory or QuartzBackend
        self._trusted = trusted
        self.sink: MacSink | None = None
        self.state = "off"
        self.arm_until = 0.0
        self.stopped_by: str | None = None  # 마지막으로 끈 이유 (UI 표시)

    def start_monitor(self) -> None:
        """독립 감시: 캡처/추적이 멎어도 ESC와 입력 해제가 계속 동작한다."""
        if self._monitor is not None and self._monitor.is_alive():
            return
        self._stop_monitor.clear()
        self.last_frame = time.monotonic()
        def watch():
            while not self._stop_monitor.wait(.025):
                try:
                    self.tick(time.monotonic())
                    with self._lock:
                        if self.state != "off" and time.monotonic() - self.last_frame > .75:
                            self.off("stale")
                except Exception:
                    log.exception("native output monitor failed")
                    self.off("error")
        self._monitor = threading.Thread(target=watch, name="real-output-stop", daemon=True)
        self._monitor.start()

    def close(self) -> None:
        self.off("stop")
        self._stop_monitor.set()
        if self._monitor is not None:
            self._monitor.join(1.)

    @property
    def active(self) -> bool:
        return self.state == "on"

    @synchronized
    def request_on(self, now: float) -> None:
        if not self._trusted():
            raise PermissionError("손쉬운 사용 권한이 없습니다")
        if self.sink is None:
            self.sink = MacSink(self._factory())
        if self.state == "off":
            self.state, self.arm_until, self.stopped_by = "arming", now + self.ARM_S, None

    @synchronized
    def off(self, reason: str = "user") -> None:
        if self.state != "off":
            self.stopped_by = reason
        self.state = "off"  # 해제 중 오류가 나더라도 새 이벤트를 보내지 않는다.
        if self.sink is not None:
            self.sink.release_all()

    @synchronized
    def tick(self, now: float) -> None:
        """매 프레임. 카운트다운이 끝나면 켜고, 켜져 있으면 어디서든 ESC 로 끈다."""
        if self.state == "arming" and now >= self.arm_until:
            self.state = "on"
        if self.state != "off" and self.sink is not None:
            # 합성 ESC도 정지시킨다. ESC 매핑을 누른 상태에서 물리 ESC를 무시하지 않는다.
            if self.sink.backend.escape_down():
                self.off("escape")

    @synchronized
    def info(self, now: float) -> dict[str, Any]:
        return {"state": self.state, "remaining_s": round(max(0.0, self.arm_until - now), 2) if self.state == "arming"
                else None, "trusted": self._trusted(), "stopped_by": self.stopped_by,
                "supports": ["mouse", "keyboard"]}


class DualSink:
    """가상 싱크(웹앱 화면)에는 항상, 실제 싱크에는 RealOutput 이 켜져 있을 때만 보낸다.

    읽기(snapshot, x, pad_buttons 등)는 가상 싱크로 넘긴다. 그래서 기존 코드·UI 는 그대로 동작한다."""

    def __init__(self, virtual: Any, real: RealOutput) -> None:
        self.virtual = virtual
        self.real = real
        self._lock = real._lock

    def _real(self) -> MacSink | None:
        return self.real.sink if self.real.active else None

    @synchronized
    def move(self, x: float, y: float) -> None:
        self.virtual.move(x, y)
        if (r := self._real()) is not None:
            r.move(self.virtual.x, self.virtual.y)

    @synchronized
    def move_by(self, dx: float, dy: float) -> None:
        self.virtual.move_by(dx, dy)
        if (r := self._real()) is not None:
            r.move(self.virtual.x, self.virtual.y)

    @synchronized
    def button(self, name: str, down: bool) -> None:
        self.virtual.button(name, down)
        if (r := self._real()) is not None:
            r.button(name, down)

    @synchronized
    def scroll(self, lines: float) -> None:
        self.virtual.scroll(lines)
        if (r := self._real()) is not None:
            r.scroll(lines)

    @synchronized
    def key(self, name: str, down: bool) -> None:
        self.virtual.key(name, down)
        if (r := self._real()) is not None:
            r.key(name, down)

    @synchronized
    def set_keys(self, pressed: set[str]) -> None:
        self.virtual.set_keys(pressed)
        if (r := self._real()) is not None:
            r.set_keys(pressed)

    @synchronized
    def gamepad(self, axes: dict[str, float], buttons: dict[str, bool]) -> None:
        self.virtual.gamepad(axes, buttons)  # 실제 게임패드는 없다

    @synchronized
    def release_all(self) -> None:
        self.virtual.release_all()
        if self.real.sink is not None:
            self.real.sink.release_all()

    def __getattr__(self, name: str) -> Any:  # snapshot, controller_snapshot, x, y, pad_buttons, …
        return getattr(self.virtual, name)
