"""Desk View 장치 선택과 입력 모드 분리. 실제 카메라/UI는 켜지 않는다."""
import numpy as np
import pytest

from vision_input.capture.devices import select_camera
from vision_input.io.mouse import MouseController, MouseSettings
from vision_input.io.sink import VirtualSink
from vision_input.io.touchpad import TouchSurface
from vision_input.pen import PenTracker
from vision_input.pen_contact import OverheadContact
from vision_input.pipeline import VisionProcessor
from vision_input.server import app as server

from .handkit import make_hand
from .test_pen import pen_frame, pen_mask, _out


def cameras():
    return [dict(index=0, unique_id='mac', is_continuity=False, is_desk_view=False),
            dict(index=1, unique_id='phone', is_continuity=True, is_desk_view=False, companion_id='desk'),
            dict(index=2, unique_id='desk', is_continuity=False, is_desk_view=True, parent_id='phone')]


def test_camera_selection_pairs_desk_and_uses_id_over_changed_index():
    cams = cameras()
    assert select_camera(cams)['unique_id'] == 'phone'
    assert select_camera(cams, 0, 'phone', True)['unique_id'] == 'desk'
    assert select_camera(cams, 2, 'desk', False)['unique_id'] == 'phone'
    assert select_camera(cams, -1, None, True)['unique_id'] == 'desk'
    with pytest.raises(ValueError):
        select_camera(cams, 0, None, True)
    with pytest.raises(ValueError):
        select_camera(cams, 0, 'disconnected', True)


def test_source_preserves_normal_camera_resolution_and_fps(monkeypatch):
    monkeypatch.setattr(server, 'list_cameras', cameras)
    monkeypatch.setattr(server, 'AVF_AVAILABLE', True)
    monkeypatch.setattr(server, 'AVFCameraSource', lambda *a, **kw: (a, kw))
    s = server.CameraSpec(device_id='phone', width=1280, height=720, fps=60, mirror=True, desk_view=True)
    args, kw = server.build_source(s)
    assert args == (2, 1920, 1440, 30, True)
    assert kw['device_id'] == 'desk' and kw['desk_view']
    assert (s.width, s.height, s.fps) == (1280, 720, 60)
    args, kw = server.build_source(s.model_copy(update={'desk_view': False}))
    assert args == (1, 1280, 720, 60, True)
    assert not kw['desk_view']


def test_view_mode_default_plane_and_clear_do_not_change_user_settings():
    p = VisionProcessor(None)
    settings = MouseSettings(touch_depth_blend=.7, pen_depth_blend=.8)
    p.mouse.configure(settings)
    p.set_view_mode(True)
    assert p.calibration_info()['mode'] == 'deskview'
    assert p.mouse.settings == settings
    p.clear_calibration()
    assert p.calibration_info()['mode'] == 'deskview'
    p.set_view_mode(False)
    assert p.mouse.touch_surface is None and not p.mouse.desk_view
    assert p.mouse.settings == settings


def test_desk_touchpad_ignores_size_depth_and_gates_raised_finger():
    sink = VirtualSink()
    c = MouseController(sink)
    c.configure(MouseSettings(mode='hand', hand_control='touchpad', mirror=False, touch_depth_blend=1, touch_deadzone=0))
    c.desk_view = True
    c.set_surface(TouchSurface.overhead())
    from vision_input.hands.detector import HandFrame
    for i, size in enumerate([.10, .10, .14, .14]):
        h = make_hand(.5, .6, size)
        h.points[8] = (.5, .5)  # 같은 책상 위치, 손 크기만 변함
        c.update(i / 30, HandFrame(i / 30, [h]), None, False)
    assert sink.y == pytest.approx(.5)
    h.depth[8] = -.2  # 위로 든 검지
    h.points[8] = (.8, .5)
    st = c.update(.2, HandFrame(.2, [h]), None, False)
    assert not st['touching'] and sink.x == pytest.approx(.5)


def test_overhead_contact_needs_distinct_touch_and_lift_examples():
    s = OverheadContact()
    p = np.array([.5, .5])
    for _ in range(9):
        s.observe(p, 10, 100, 20)
    assert s.mark(True) and s.classify() is None
    assert s.mark(False) and not s.ready  # 동일한 외형은 접촉 근거가 되지 않는다
    s = OverheadContact()
    for _ in range(9):
        s.observe(p, 10, 100, 20)
    s.mark(True)
    for _ in range(9):
        s.observe(p, 13, 106, 12)
    s.mark(False)
    assert s.ready and s.classify() < -.9
    s.observe(np.array([.6, .8]), 10, 100, 20)
    assert s.classify() > .8


def test_desk_pen_drawing_preserves_plane_shape_without_horizon_projection():
    p = PenTracker((700, 500), (600, 200))
    p.manual_contact = True
    p.update(pen_frame(), _out(pen_mask(), None), 0, overhead=True)
    assert p.cur[-1] == pytest.approx((p.tip[0] / 1280, -p.tip[1] / 1280), abs=1e-5)
    assert p.surface.K is None and p.state()['desk_view']


def test_manual_contact_lease_expires_and_stop_releases_it():
    p = PenTracker((700, 500), (600, 200))
    p.manual_press(True, 0)
    p.update(pen_frame(), _out(pen_mask(), None), .1, overhead=True)
    assert p.contact
    p.update(pen_frame(), _out(pen_mask(), None), 1.3, overhead=True)
    assert not p.contact
    processor = VisionProcessor(None)
    processor.pens[1] = p
    p.manual_press(True, 2)
    processor.emergency_stop()
    assert p.manual_contact is None and p.manual_until is None and not p.contact


def test_api_state_read_does_not_swallow_stroke_events():
    p = PenTracker((700, 500), (600, 200))
    p.events.append({'type': 'up', 'stroke': [(0, 0), (1, 1)]})
    assert p.state(consume=False)['events']
    assert p.state()['events']
    assert not p.state()['events']


def test_camera_missing_keeps_normal_startup_available_for_video_selection(monkeypatch):
    monkeypatch.setattr(server, 'list_cameras', lambda: [])
    monkeypatch.setattr(server, 'AVF_AVAILABLE', True)
    monkeypatch.setattr(server, 'AVFCameraSource', lambda *a, **kw: (a, kw))
    args, kw = server.build_source(server.CameraSpec())
    assert args[0] == 0
    with pytest.raises(ValueError):
        server.build_source(server.CameraSpec(desk_view=True))


def test_desk_setup_api_checks_availability_and_calls_launcher(monkeypatch):
    from fastapi.testclient import TestClient
    from vision_input.config import Settings
    from vision_input.capture import SyntheticSource
    from vision_input.capture import desk_setup
    from .test_server import RectSeg
    opened = []
    monkeypatch.setattr(server, 'list_cameras', lambda: [])
    monkeypatch.setattr(desk_setup, 'present_desk_view', lambda: opened.append(True))
    proc = VisionProcessor(None)
    app = server.create_app(Settings(), server.SyntheticSpec(width=320, height=240),
                            processor=proc, segmenter=RectSeg(), serve_frontend=False)
    with TestClient(app) as client:
        assert client.post('/api/source/desk-view/setup').status_code == 409
        monkeypatch.setattr(server, 'list_cameras', cameras)
        assert client.post('/api/source/desk-view/setup').json() == {'opened': True}
        assert opened == [True]
        def build(spec):
            src = SyntheticSource(320, 240, 60)
            src.desk_view = bool(getattr(spec, 'desk_view', False))
            return src
        monkeypatch.setattr(server, 'build_source', build)
        assert client.put('/api/source', json={'kind': 'camera', 'desk_view': True}).status_code == 200
        import time
        deadline = time.monotonic() + 3
        while not proc.desk_view and time.monotonic() < deadline:
            time.sleep(.01)
        assert proc.desk_view and proc.mouse.touch_surface.mode == 'deskview'
        assert client.put('/api/source', json={'kind': 'camera', 'desk_view': False}).status_code == 200
        deadline = time.monotonic() + 3
        while proc.desk_view and time.monotonic() < deadline:
            time.sleep(.01)
        assert not proc.desk_view and proc.mouse.touch_surface is None
