"""깊이 마우스 원근 보정(크기 기반), 종이 보정 시 물체 닿은 점(포즈 + 오프셋), 축별 감도·반전."""
import math

import numpy as np
import pytest

from vision_input.io.depth import DepthCursor
from vision_input.io.mouse import MouseController, MouseSettings
from vision_input.io.sink import VirtualSink
from vision_input.io.touchpad import TouchSurface
from vision_input.pipeline import FOOT_CLIP, TrackedObject, VisionProcessor
from vision_input.tracking.api import Pose, TrackOutput, TrackState
from vision_input.tracking.desk import mask_foot


def _approach(x_world: float, perspective: bool, steps: int = 60) -> tuple[float, float]:
    """핀홀 카메라: 가장자리의 물체가 카메라 쪽으로 곧게 다가온다 (좌우 위치 X 고정, 크기 1 → 1.6)."""
    c = DepthCursor()
    sx = sy = 0.
    for i in range(steps):
        s = 1 + 0.6 * i / (steps - 1)
        x = 0.5 + x_world * s  # x - 가운데 ∝ X / Z ∝ X · 크기
        dx, dy = c.update(np.array([x, 0.5]), s, i / 30, None, smoothing=50, gain=1.4, deadzone=0,
                          perspective=perspective)
        sx += dx
        sy += dy
    return sx, sy


def test_depth_perspective_removes_diagonal_at_edge():
    raw_dx, raw_dy = _approach(0.25, perspective=False)
    fix_dx, fix_dy = _approach(0.25, perspective=True)
    assert raw_dy < -0.3 and fix_dy == pytest.approx(raw_dy, rel=1e-6)  # 위아래(깊이)는 그대로
    assert abs(raw_dx) > 0.1                    # 보정 없으면 사선: 좌우로 크게 샌다
    assert abs(fix_dx) < 0.1 * abs(raw_dx)      # 보정하면 거의 위아래로만


def test_depth_perspective_is_noop_at_center_and_for_lateral_moves():
    dx, _ = _approach(0.0, perspective=True)
    assert abs(dx) < 1e-6
    c1, c2 = DepthCursor(), DepthCursor()
    for i in range(30):  # 크기 변화 없는 좌우 이동은 보정과 무관
        p = np.array([0.3 + 0.01 * i, 0.5])
        a = c1.update(p, 1.0, i / 30, None, smoothing=50, gain=1.4, deadzone=0, perspective=True)
        b = c2.update(p, 1.0, i / 30, None, smoothing=50, gain=1.4, deadzone=0, perspective=False)
        assert a == pytest.approx(b)


def test_mouse_sensitivity_and_invert_for_relative_depth():
    def run(**kw):
        sink = VirtualSink()
        c = MouseController(sink)
        c.configure(MouseSettings(mode="object", object_id=1, hand_clicks=False, depth_perspective=False, **kw))
        for i in range(30):
            c.update(i / 30, None, (0.4 + 0.004 * i, 0.5), True, obj_scale=1 + 0.01 * i)
        return sink.x - 0.5, sink.y - 0.5

    bx, by = run()
    assert bx > 0 and by < 0  # 오른쪽으로, 가까워짐 = 위
    sx, sy = run(sens_x=2.0, sens_y=0.5)
    assert sx == pytest.approx(2 * bx, rel=0.05) and sy == pytest.approx(0.5 * by, rel=0.05)
    ix, iy = run(mirror=True, invert_y=True)
    assert ix == pytest.approx(-bx, rel=0.05) and iy == pytest.approx(-by, rel=0.05)


def test_mask_foot_ignores_single_protruding_pixel():
    m = np.zeros((200, 200), bool)
    m[50:120, 80:120] = True
    base = mask_foot(m)
    m[140, 60] = True  # 튀어나온 점 하나
    f = mask_foot(m)
    assert base is not None and f is not None
    assert abs(f[1] - base[1]) <= 2 and abs(f[0] - base[0]) <= 2


def _obj(size0=40.0) -> TrackedObject:
    from vision_input.tracking.axes import AxisState
    out = TrackOutput(TrackState.TRACKING, (80, 50, 120, 120), Pose(100, 85, 1.0, 0.0, 1.0), None, 1.0)
    return TrackedObject(1, "a", "#fff", None, {}, AxisState((200, 200)), size0, out)  # type: ignore[arg-type]


def test_foot_offset_is_smooth_under_mask_jitter_and_follows_rotation():
    rng = np.random.default_rng(0)
    obj = _obj()
    feet = []
    for i in range(200):
        m = np.zeros((200, 200), bool)
        bottom = 120 + int(rng.integers(-2, 3))  # 가장자리 ±2px 떨림
        if i % 17 == 0:
            bottom += 12  # 가끔 크게 튐 (분할 번짐)
        m[50:bottom, 80:120] = True
        VisionProcessor._update_foot(obj, obj.out, m)
        feet.append(VisionProcessor._foot_px(obj))
    ys = np.array([f[1] for f in feet[50:]])
    assert np.std(ys) < 0.6 and abs(np.mean(ys) - 119.5) < 2.5
    # 한 번에 크게 튄 값은 등록 크기의 FOOT_CLIP 까지만 반영
    step = np.abs(np.diff(ys)).max()
    assert step <= FOOT_CLIP * 40 * 0.1 + 1e-6 + 0.5
    # 포즈가 90° 돌면 닿은 점도 같이 돈다 (오프셋은 물체 좌표)
    obj.out = TrackOutput(TrackState.TRACKING, None, Pose(100, 85, 1.0, 90.0, 1.0), None, 1.0)
    fx, fy = VisionProcessor._foot_px(obj)
    assert fx == pytest.approx(100 - (np.mean(ys) - 85), abs=0.5) and fy == pytest.approx(85, abs=1.5)


def test_object_mouse_on_paper_uses_foot_point_not_box_bottom():
    """종이 보정이 있으면 obj_foot(부드러운 기준점)을 쓴다: 박스 아래 변이 떨려도 커서가 가만히 있다."""
    sink = VirtualSink()
    c = MouseController(sink)
    c.set_surface(TouchSurface.quad([[0.2, 0.9], [0.8, 0.9], [0.7, 0.5], [0.3, 0.5]]))
    c.configure(MouseSettings(mode="object", object_id=1, hand_clicks=False, depth_deadzone=0))
    rng = np.random.default_rng(1)
    for i in range(60):
        jitter = float(rng.normal(0, 0.01))
        c.update(i / 30, None, (0.5, 0.6), True, obj_box=(0.45, 0.5, 0.55, 0.7 + jitter), obj_foot=(0.5, 0.7))
    assert math.hypot(sink.x - 0.5, sink.y - 0.5) < 1e-6
    assert c.status["depth_source"] == "desk"
