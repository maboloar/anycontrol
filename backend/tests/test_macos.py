"""실제 macOS 입력: FakeBackend 로 검증한다 (진짜 커서·키는 건드리지 않는다)."""

from __future__ import annotations

import pytest

from vision_input.io.macos import ESCAPE, KEYCODES, MODIFIER_FLAGS, DualSink, MacSink, RealOutput
from vision_input.io.sink import VirtualSink


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.esc = False

    def screen(self):
        return 0.0, 0.0, 101.0, 51.0

    def mouse(self, kind, x, y, button, clicks):
        self.calls.append(("mouse", kind, round(x), round(y), button, clicks))

    def key(self, code, down, flags):
        self.calls.append(("key", code, down, flags))

    def scroll(self, dy_px):
        self.calls.append(("scroll", dy_px))

    def escape_down(self):
        return self.esc


def test_move_dedupes_and_drags_while_held():
    b = FakeBackend()
    s = MacSink(b)
    s.move(0.5, 0.5)
    s.move(0.5, 0.5)  # 같은 자리 → 이벤트 없음
    assert b.calls == [("mouse", "move", 50, 25, "left", 0)]
    s.button("left", True)
    s.move(1.0, 1.0)
    s.button("left", False)
    assert [c[1] for c in b.calls] == ["move", "down", "drag", "up"]
    assert b.calls[2][2:4] == (100, 50)


def test_double_click_count():
    b = FakeBackend()
    s = MacSink(b)
    for _ in range(2):
        s.button("left", True)
        s.button("left", False)
    assert [c[5] for c in b.calls] == [1, 1, 2, 2]


def test_scroll_sign_and_remainder():
    b = FakeBackend()
    s = MacSink(b)
    s.scroll(0.05)  # 0.6px → 아직 없음
    assert b.calls == []
    s.scroll(0.05)  # 누적 1.2px 아래 → macOS 는 음수
    assert b.calls == [("scroll", -1)]
    s.scroll(-1.0)
    assert b.calls[-1] == ("scroll", 11)


def test_keys_modifier_first_and_flags():
    b = FakeBackend()
    s = MacSink(b)
    s.set_keys({"a", "shift"})
    assert b.calls == [("key", KEYCODES["shift"], True, MODIFIER_FLAGS["shift"]),
                       ("key", KEYCODES["a"], True, MODIFIER_FLAGS["shift"])]
    s.set_keys({"shift", "a", "nope"})  # 모르는 키는 무시, 변화 없음
    assert len(b.calls) == 2
    s.button("right", True)
    s.release_all()
    assert s.keys == set() and not any(s.buttons.values())
    assert ("mouse", "up", 50, 25, "right", 1) in b.calls


def make_real(trusted=True):
    b = FakeBackend()
    return RealOutput(backend_factory=lambda: b, trusted=lambda: trusted), b


def test_real_arms_then_on_and_escape_stops():
    r, b = make_real()
    r.request_on(10.0)
    assert r.state == "arming" and r.info(11.0)["remaining_s"] == 2.0
    r.tick(12.9)
    assert not r.active
    r.tick(13.0)
    assert r.active
    r.sink.set_keys({"w"})
    b.esc = True
    r.tick(13.1)
    assert r.state == "off" and r.stopped_by == "escape"
    assert ("key", KEYCODES["w"], False, 0) in b.calls  # 끄면서 놓는다


def test_real_stops_even_when_escape_mapping_is_held():
    r, b = make_real()
    r.request_on(0.0)
    r.tick(5.0)
    r.sink.set_keys({"escape"})
    b.esc = True  # 우리 매핑이 누른 ESC
    r.tick(5.1)
    assert not r.active
    assert ESCAPE == KEYCODES["escape"]


def test_real_requires_permission():
    r, _ = make_real(trusted=False)
    with pytest.raises(PermissionError):
        r.request_on(0.0)
    assert r.state == "off" and r.info(0.0)["trusted"] is False


def test_dual_sink_forwards_only_when_on():
    r, b = make_real()
    d = DualSink(VirtualSink(), r)
    d.move(0.2, 0.2)
    r.request_on(0.0)
    d.move(0.3, 0.3)  # arming → 아직 가상만
    assert b.calls == []
    r.tick(3.0)
    d.move(0.4, 0.4)
    d.set_keys({"space"})
    d.gamepad({"lx": 1.0}, {"a": True})  # 게임패드는 가상만
    assert [c[0] for c in b.calls] == ["mouse", "key"]
    assert d.pad_buttons["a"] and abs(d.x - 0.4) < 1e-9  # 읽기는 가상 싱크


def test_processor_emergency_stop_turns_real_off():
    from vision_input.pipeline import VisionProcessor

    r, _ = make_real()
    p = VisionProcessor(None, real=r)
    r.request_on(0.0)
    r.tick(3.0)
    p.emergency_stop()
    assert r.state == "off" and r.stopped_by == "stop"


def test_api_real_403_when_untrusted():
    from fastapi.testclient import TestClient

    from vision_input.config import Settings
    from vision_input.pipeline import VisionProcessor
    from vision_input.server.app import SyntheticSpec, create_app

    from .test_server import RectSeg

    r, _ = make_real(trusted=False)
    app = create_app(Settings(), SyntheticSpec(width=320, height=240, fps=60), serve_frontend=False,
                     segmenter=RectSeg(), processor=VisionProcessor(None, real=r))
    with TestClient(app) as c:
        assert c.get("/api/real").json()["state"] == "off"
        res = c.put("/api/real", json={"on": True})
        assert res.status_code == 403 and "손쉬운 사용" in res.json()["detail"]
        assert c.put("/api/real", json={"on": False}).json()["state"] == "off"


def test_watchdog_releases_without_any_camera_frames():
    import time
    r, b = make_real()
    r.request_on(time.monotonic() - 4)
    r.tick(time.monotonic())
    r.sink.key('w', True)
    r.start_monitor()
    try:
        r.last_frame = time.monotonic() - 1
        deadline = time.monotonic() + 1
        while r.active and time.monotonic() < deadline:
            time.sleep(.01)
        assert not r.active and r.stopped_by == 'stale'
        assert ('key', KEYCODES['w'], False, 0) in b.calls
    finally:
        r.close()


def test_watchdog_detects_escape_without_engine_tick():
    import time
    r, b = make_real()
    r.request_on(time.monotonic() - 4)
    r.tick(time.monotonic())
    r.sink.button('left', True)
    r.start_monitor()
    try:
        b.esc = True
        deadline = time.monotonic() + 1
        while r.active and time.monotonic() < deadline:
            time.sleep(.01)
        assert r.stopped_by == 'escape' and not r.active
        assert any(c[:2] == ('mouse', 'up') for c in b.calls)
    finally:
        r.close()


def test_pausing_processor_disarms_real_output():
    from vision_input.pipeline import VisionProcessor
    r, _ = make_real()
    p = VisionProcessor(None, real=r)
    r.request_on(0)
    r.tick(3)
    p.set_paused(True)
    assert r.state == 'off' and r.stopped_by == 'paused'
