"""카메라 없이 전원·반전·일시정지의 상태 보존과 실제 캡처 해제를 검사한다."""
import time
from unittest.mock import Mock

import cv2
import numpy as np
from fastapi.testclient import TestClient

from vision_input.capture.slot import Frame
from vision_input.capture.sources import CameraSource, SyntheticSource
from vision_input.pipeline import VisionProcessor
from vision_input.engine import PreviewEncoder
from vision_input.config import PreviewSettings
from vision_input.server import app as server
from vision_input.server.protocol import unpack_preview
from vision_input.tracking.vi_tracker import TrackerConfig, ViTracker
from .test_server import RectSeg, _wait_frame


def wait_until(check, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(.02)
    assert check()


def test_camera_pause_mirror_and_power_keep_registration_calibration_and_mouse(monkeypatch):
    built = []
    def build(spec):
        src = SyntheticSource(spec.width, spec.height, spec.fps, paused=spec.paused)
        src.kind = "camera"
        src.mirror, src.enabled = spec.mirror, spec.enabled
        built.append(src)
        return src
    monkeypatch.setattr(server, "build_source", build)
    processor = VisionProcessor(lambda: ViTracker(TrackerConfig(tier1="off")))
    spec = server.CameraSpec(index=0, width=320, height=240, fps=30)
    app = server.create_app(initial_source=spec, processor=processor, segmenter=RectSeg(), serve_frontend=False)
    with TestClient(app) as client:
        oid = _wait_frame(client).json()["id"]
        assert client.put("/api/mouse", json={"mode": "object", "object_id": oid, "hand_clicks": False}).status_code == 200
        cal = client.put("/api/calibration/line", json={"points": [[.1, .6], [.9, .6]]}).json()
        tr = processor.tracker
        assert client.put("/api/source/playback", json={"paused": True}).json() == {"paused": True}
        # 정지 중에도 미리보기 반전만 바꿀 수 있다.
        current = client.get("/api/source").json()["spec"]
        assert client.put("/api/source", json={**current, "mirror": True}).status_code == 200
        assert client.put("/api/source/power", json={"enabled": False}).json() == {"enabled": False}
        assert client.put("/api/source/power", json={"enabled": True}).json() == {"enabled": True}
        assert client.put("/api/source/playback", json={"paused": False}).status_code == 200
        assert len(built) == 1 and processor.tracker is tr
        assert [o["id"] for o in client.get("/api/objects").json()] == [oid]
        assert client.get("/api/calibration").json() == cal
        assert client.get("/api/mouse").json()["settings"]["object_id"] == oid
        assert client.post("/api/source/restart").status_code == 409


def test_synthetic_pause_preserves_registration_restart_clears_and_stops_at_first_frame():
    processor = VisionProcessor(None)
    app = server.create_app(initial_source=server.SyntheticSpec(width=320, height=240, fps=30),
                            processor=processor, segmenter=RectSeg(), serve_frontend=False)
    with TestClient(app) as client:
        oid = _wait_frame(client).json()["id"]
        client.put("/api/source/playback", json={"paused": True})
        assert [o["id"] for o in client.get("/api/objects").json()] == [oid]
        assert client.put("/api/source/power", json={"enabled": False}).status_code == 409
        r = client.post("/api/source/restart")
        assert r.status_code == 200 and r.json()["spec"]["paused"]
        assert client.get("/api/objects").json() == []
        wait_until(lambda: processor.latest is not None)
        src = app.state.engine.source
        assert np.array_equal(processor.latest.image, src.render(0))
        assert _wait_frame(client).status_code == 201  # 정지한 첫 장면에서도 선택 가능


def test_frozen_frames_release_input_without_tracking_and_resume_once():
    processor = VisionProcessor(None)
    processor.tracker = Mock()
    processor.hands = None
    processor.hand_drawing.set_enabled(True)
    processor.sink.button("left", True)
    processor.sink.key("w", True)
    image = np.zeros((48, 64, 3), np.uint8)
    for seq in range(1, 4):
        state = processor.process_frozen(Frame(seq, image, seq, seq, True))
        assert state["paused"] and not state["mouse"]["left"]
        assert not state["controller"]["keys"] and not state["hand_drawing"]["contact"]
    processor.tracker.step.assert_not_called()
    assert processor.hand_drawing.enabled
    processor.process(Frame(4, image, 10, 10))
    processor.process(Frame(5, image, 11, 11))
    processor.tracker.resume.assert_called_once_with(10)


def test_opencv_camera_off_releases_device_pause_reuses_raw_frame_and_on_reopens(monkeypatch):
    image = np.zeros((48, 64, 3), np.uint8)
    image[:, :20] = 200
    captures = []
    class Capture:
        released = False
        def read(self):
            time.sleep(.015)
            return True, image.copy()
        def release(self):
            self.released = True
    def open_capture():
        cap = Capture()
        captures.append(cap)
        return cap
    src = CameraSource(mirror=True, enabled=False)
    monkeypatch.setattr(src, "_open", open_capture)
    src.start()
    try:
        wait_until(lambda: src.status == "off")
        assert not captures
        src.enabled = True
        first = src.slot.wait_newer(-1, 2)
        assert first is not None and np.array_equal(first.image, image)  # mirror is preview only
        src.paused = True
        wait_until(lambda: src.slot.latest() is not None and src.slot.latest().frozen)
        src.enabled = False
        wait_until(lambda: captures[0].released and src.status == "off")
        src.enabled = True
        wait_until(lambda: len(captures) == 2)
        src.paused = False
        wait_until(lambda: not src.slot.latest().frozen)
    finally:
        src.stop()
    assert all(c.released for c in captures)


def test_synthetic_paused_time_does_not_advance_on_resume():
    src = SyntheticSource(320, 240, 30, paused=True)
    rendered = []
    original = src.render
    def render(t):
        rendered.append(t)
        return original(t)
    src.render = render
    src.start()
    try:
        first = src.slot.wait_newer(-1, 2)
        repeat = src.slot.wait_newer(first.seq, 2)
        assert repeat.frozen and np.array_equal(first.image, repeat.image)
        assert rendered == [0]
        src.paused = False
        wait_until(lambda: len(rendered) >= 2)
        assert rendered[1] < .08
    finally:
        src.stop()


def test_preview_mirror_flips_jpeg_without_changing_canonical_frame():
    image = np.zeros((120, 160, 3), np.uint8)
    image[:, :60] = 200
    original = image.copy()
    payloads = []
    hub = Mock()
    hub.publish_frame.side_effect = payloads.append
    encoder = PreviewEncoder(hub, PreviewSettings())
    encoder.start()
    try:
        encoder.offer(Frame(1, image, 1, 1, True), flags=3)
        wait_until(lambda: bool(payloads))
        header, jpeg = unpack_preview(payloads[0])
        decoded = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        assert header.flags == 3
        assert decoded[:, :60].mean() < 10 and decoded[:, 100:].mean() > 180
        assert np.array_equal(image, original)
    finally:
        encoder.stop()


def test_refresh_settings_support_partial_updates_and_survive_source_restart():
    processor = VisionProcessor(lambda: ViTracker(TrackerConfig(tier1="off")))
    app = server.create_app(initial_source=server.SyntheticSpec(width=320, height=240, paused=True),
                            processor=processor, segmenter=RectSeg(), serve_frontend=False)
    with TestClient(app) as client:
        r = client.put("/api/tracking", json={"segmentation_enabled": True, "segmentation_hz": .25})
        assert r.status_code == 200 and r.json()["segmentation_hz"] == .25
        assert client.put("/api/tracking", json={"hand_occlusion": False}).json()["segmentation_enabled"]
        assert client.put("/api/tracking", json={"segmentation_hz": 10}).status_code == 422
        assert client.post("/api/source/restart").status_code == 200
        after = client.get("/api/tracking").json()
        assert after["segmentation_enabled"] and after["segmentation_hz"] == .25
