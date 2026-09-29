"""맨손 마우스 제스처, 마우스 컨트롤러, 가상 싱크, API."""

import json
import time

import numpy as np
import pytest

from vision_input.hands.detector import HandFrame
from vision_input.hands.gestures import GestureConfig, GestureRecognizer, features
from vision_input.io.mouse import MouseController, MouseSettings
from vision_input.io.sink import VirtualSink

from .handkit import make_hand


# ---------------------------------------------------------------- 제스처
def test_features_scale_invariant():
    cfg = GestureConfig()
    a = features(make_hand(0.5, 0.5, 0.1, pinch=1.0), cfg)
    b = features(make_hand(0.5, 0.5, 0.25, pinch=1.0), cfg)
    assert a.pinch_index == pytest.approx(b.pinch_index, rel=0.02)
    assert a.extended == b.extended


def test_pinch_press_release_with_hysteresis_and_debounce():
    g = GestureRecognizer()
    seq = [1.0, 1.0, 0.2, 0.2, 0.2, 0.38, 0.38, 0.6, 0.6, 0.6]  # 0.38 은 on(0.3)~off(0.45) 사이: 유지
    downs = [g.update(make_hand(0.5, 0.5, 0.15, pinch=p), i / 30).left for i, p in enumerate(seq)]
    # 누름·놓음 모두 2프레임 연속이어야 바뀐다
    assert downs == [False, False, False, True, True, True, True, True, False, False]


def test_single_frame_noise_does_not_click():
    g = GestureRecognizer()
    seq = [1.0, 0.2, 1.0, 1.0, 0.2, 1.0]
    assert not any(g.update(make_hand(0.5, 0.5, 0.15, pinch=p), i / 30).left for i, p in enumerate(seq))


def test_right_click_uses_middle_finger_only_when_index_open():
    g = GestureRecognizer()
    outs = [g.update(make_hand(0.5, 0.5, 0.15, pinch=1.0, pinch_middle=0.2), i / 30) for i in range(4)]
    assert outs[-1].right and not outs[-1].left
    g2 = GestureRecognizer()
    both = [g2.update(make_hand(0.5, 0.5, 0.15, pinch=0.2, pinch_middle=0.2), i / 30) for i in range(4)]
    assert both[-1].left and not both[-1].right


def test_two_finger_scroll_follows_hand_motion():
    g = GestureRecognizer()
    total = 0.0
    for i in range(10):
        o = g.update(make_hand(0.5, 0.4 + 0.02 * i, 0.15, pinch=1.0, scroll_pose=True), i / 30)
        assert o.gesture == "scroll" and o.freeze
        total += o.scroll
    assert total > 2  # 손을 내리면 + (아래로 스크롤)


def test_losing_hand_releases_buttons():
    g = GestureRecognizer()
    for i in range(3):
        g.update(make_hand(0.5, 0.5, 0.15, pinch=0.2), i / 30)
    assert g.left.down
    o = g.update(None, 0.2)
    assert not o.left and not g.left.down


# ---------------------------------------------------------------- 컨트롤러
def _ctl(**kw):
    sink = VirtualSink()
    c = MouseController(sink)
    c.configure(MouseSettings(**kw))
    return c, sink


def test_hand_mode_maps_region_with_mirror():
    c, sink = _ctl(mode="hand", hand_control="air", mirror=True, hand_region=[0.2, 0.2, 0.8, 0.8])
    for i in range(40):
        h = make_hand(0.2, 0.8, 0.12, pinch=1.0)  # 영역 왼쪽 아래 → 거울이면 화면 오른쪽 아래
        hf = HandFrame(i / 30, [h])
        c.update(i / 30, hf, None, False)
    palm = h.points[[0, 5, 9, 13, 17]].mean(0)
    ex = 1 - (palm[0] - 0.2) / 0.6
    ey = (palm[1] - 0.2) / 0.6
    assert sink.x == pytest.approx(min(1, max(0, ex)), abs=0.02)
    assert sink.y == pytest.approx(min(1, max(0, ey)), abs=0.02)


def test_click_does_not_drag_cursor_while_fingers_close():
    """손가락을 모으는 동안 손바닥이 조금 흔들려도 커서가 따라가지 않는다 (freeze)."""
    c, sink = _ctl(mode="hand", hand_control="air", mirror=False)
    t = 0.0
    for i in range(30):
        t = i / 30
        c.update(t, HandFrame(t, [make_hand(0.5, 0.45, 0.12, pinch=1.0)]), None, False)
    x0 = sink.x
    for j, p in enumerate([0.55, 0.45, 0.35, 0.25, 0.2, 0.2, 0.2]):
        t += 1 / 30
        c.update(t, HandFrame(t, [make_hand(0.5 + 0.004 * j, 0.45, 0.12, pinch=p)]), None, False)
    ev = sink.snapshot()["events"]
    assert any(e["type"] == "down" and e["button"] == "left" for e in ev)
    assert abs(sink.x - x0) < 0.01


def test_stale_hand_results_are_ignored():
    c, sink = _ctl(mode="hand", hand_control="air")
    for i in range(3):
        c.update(i / 30, HandFrame(i / 30, [make_hand(0.5, 0.5, 0.12, pinch=0.2)]), None, False)
    assert sink.buttons["left"]
    st = c.update(5.0, HandFrame(0.1, [make_hand(0.5, 0.5, 0.12, pinch=0.2)]), None, False)
    assert not sink.buttons["left"] and st["hand_visible"] is False


def test_object_mode_uses_object_for_cursor_and_pen_contact_as_click():
    c, sink = _ctl(mode="object", coordinate_mode="image", object_id=1, hand_clicks=False, mirror=False, object_region=[0, 0, 1, 1])
    for i in range(40):
        c.update(i / 30, None, (0.25, 0.75), True)
    assert sink.x == pytest.approx(0.25, abs=0.01) and sink.y == pytest.approx(0.75, abs=0.01)
    c.update(2.0, None, (0.25, 0.75), True, obj_pressed=True)
    assert sink.buttons["left"]
    c.update(2.1, None, (0.25, 0.75), True, obj_pressed=False)
    assert not sink.buttons["left"]


def test_off_mode_and_emergency_stop_release_everything():
    c, sink = _ctl(mode="hand", hand_control="air")
    for i in range(3):
        c.update(i / 30, HandFrame(i / 30, [make_hand(0.5, 0.5, 0.12, pinch=0.2)]), None, False)
    assert sink.buttons["left"]
    c.emergency_stop()
    assert not any(sink.buttons.values()) and c.settings.mode == "off"
    assert c.update(1.0, HandFrame(1.0, [make_hand(0.5, 0.5, 0.12, pinch=0.2)]), None, False) == {"mode": "off"}


@pytest.mark.parametrize("region", [[0.5, 0.5, 0.55, 0.9], [0.8, 0.1, 0.2, 0.9], [0, 0, 1.2, 1]])
def test_invalid_regions_rejected(region):
    with pytest.raises(ValueError):
        MouseSettings(hand_region=region)


def test_needs_hands():
    assert MouseSettings(mode="hand").needs_hands
    assert MouseSettings(mode="object", hand_clicks=True).needs_hands
    assert not MouseSettings(mode="object", hand_clicks=False).needs_hands
    assert not MouseSettings(mode="off").needs_hands


# ---------------------------------------------------------------- API
class FakeHands:
    """HandWorker 대역: 켜고 끄기만 기록한다."""

    def __init__(self):
        self.running = False
        self.error = None
        self.starts = 0
        self.backend = "vision"

    def set_backend(self, backend):
        if backend not in ("vision", "mediapipe"):
            raise ValueError(backend)
        self.backend = backend

    def start(self):
        if not self.running:
            self.starts += 1
        self.running = True

    def stop(self):
        self.running = False

    def offer(self, img, t):
        pass

    def latest(self):
        return HandFrame(time.monotonic(), [])


@pytest.fixture()
def client_hands():
    from fastapi.testclient import TestClient

    from vision_input.config import Settings
    from vision_input.pipeline import VisionProcessor
    from vision_input.server.app import SyntheticSpec, create_app

    from .test_server import RectSeg

    hands = FakeHands()
    proc = VisionProcessor(None, hand_worker=hands)
    app = create_app(Settings(), SyntheticSpec(width=320, height=240, fps=60), serve_frontend=False,
                     segmenter=RectSeg(), processor=proc)
    with TestClient(app) as c:
        yield c, hands


def test_mouse_api_toggles_hand_tracking(client_hands):
    c, hands = client_hands
    assert c.get("/api/mouse").json()["settings"]["mode"] == "off"
    r = c.put("/api/mouse", json={"mode": "hand"})
    assert r.status_code == 200 and r.json()["settings"]["mode"] == "hand"
    deadline = time.monotonic() + 2
    while not hands.running and time.monotonic() < deadline:
        time.sleep(0.02)
    assert hands.running
    c.put("/api/mouse", json={"mode": "off"})
    deadline = time.monotonic() + 2
    while hands.running and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not hands.running  # 끄면 손 추적도 멈춘다


def test_hand_drawing_api_works_with_mouse_off_and_emergency_stop(client_hands):
    c, hands = client_hands
    assert c.get("/api/drawing/hand").json()["enabled"] is False
    r = c.put("/api/drawing/hand", json={"enabled": True})
    assert r.status_code == 200 and r.json()["enabled"] is True
    assert c.get("/api/mouse").json()["settings"]["mode"] == "off"
    deadline = time.monotonic() + 2
    while not hands.running and time.monotonic() < deadline:
        time.sleep(.02)
    assert hands.running
    assert c.post("/api/drawing/hand/clear").status_code == 200
    assert c.put("/api/drawing/hand", json={}).status_code == 422
    c.post("/api/stop")
    assert c.get("/api/drawing/hand").json()["enabled"] is False
    assert c.put("/api/drawing/hand", json={"enabled": False}).status_code == 200


def test_object_mouse_requires_existing_object_and_stop_endpoint(client_hands):
    c, _ = client_hands
    assert c.put("/api/mouse", json={"mode": "object", "object_id": 42}).status_code == 409
    assert c.put("/api/mouse", json={"mode": "hand", "hand_region": [0.5, 0.5, 0.52, 0.9]}).status_code == 422
    c.put("/api/mouse", json={"mode": "hand"})
    r = c.post("/api/stop")
    assert r.status_code == 200 and r.json()["settings"]["mode"] == "off"


def test_line_calibration_api_preserves_valid_surface_on_error(client_hands):
    c, _ = client_hands
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        r = c.put("/api/calibration/line", json={"points": [[.1, .6], [.9, .6]]})
        if r.status_code == 200:
            break
        time.sleep(.02)
    assert r.status_code == 200 and r.json()["mode"] == "line"
    bad = c.put("/api/calibration/line", json={"points": [[.5, .5], [.51, .5]]})
    assert bad.status_code == 422
    assert c.get("/api/calibration").json()["mode"] == "line"
    assert c.delete("/api/calibration").status_code == 204
    assert not c.get("/api/calibration").json()["calibrated"]


def test_state_message_carries_mouse(client_hands):
    c, _ = client_hands
    c.put("/api/mouse", json={"mode": "hand"})
    with c.websocket_connect("/ws") as ws:
        ws.receive_text()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            m = ws.receive()
            if m.get("text"):
                o = json.loads(m["text"])
                if o["type"] == "state":
                    assert o["data"]["mouse"]["mode"] == "hand"
                    assert {"x", "y", "left", "right", "scroll", "events"} <= set(o["data"]["mouse"])
                    return
    pytest.fail("no state")


def test_line_registration_creates_pen(client_hands):
    c, _ = client_hands
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        r = c.post("/api/objects", json={"line": [0.4, 0.8, 0.6, 0.2]})
        if r.status_code != 409:
            break
        time.sleep(0.05)
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["kind"] == "pen"
    assert c.post(f"/api/objects/{o['id']}/pen/clear").status_code == 200
    assert c.post(f"/api/objects/{o['id']}/pen/config", json={"horizon": 0.4}).json()["horizon"] == 0.4
    assert c.post(f"/api/objects/{o['id']}/pen/nope").status_code == 404
    assert c.post("/api/objects", json={"line": [0.5, 0.5, 0.505, 0.5]}).status_code == 422  # 너무 짧음
    _ = np  # noqa
