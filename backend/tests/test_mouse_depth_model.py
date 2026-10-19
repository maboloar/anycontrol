"""물체 마우스의 깊이 모델 옵션(depth_source=model): 순수 계산과 파이프라인 경로. 실제 모델은 쓰지 않는다."""
import numpy as np
import pytest
from vision_input import depth_model as dm
from vision_input.io.mouse import MouseSettings
from vision_input.pipeline import VisionProcessor

W, H = 160, 120


def _depth(plane=(0.0, 0.6, 0.1), obj=None, size=(W, H)):
    w, h = size
    gy, gx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = plane[0] * (gx + .5) / w + plane[1] * (gy + .5) / h + plane[2]
    if obj is not None:
        m, add = obj
        d = np.where(m, d + add, d)
    return d.astype(np.float32)


def _box(x0, y0, x1, y1):
    m = np.zeros((H, W), bool)
    m[y0:y1, x0:x1] = True
    return m


def test_position_follows_the_desk_depth_and_ignores_per_frame_scale_and_shift():
    far = dm.object_depth_position(_depth(), _box(60, 50, 80, 62))
    near = dm.object_depth_position(_depth(), _box(60, 96, 80, 108))
    assert far["u"] < 0.5 < near["u"] and near["u"] > far["u"] + 0.3
    # 깊이 모델은 프레임마다 스케일·이동이 달라진다: 같은 장면을 3 배 키워 옮겨도 같은 위치
    again = dm.object_depth_position(_depth() * 3.0 + 0.7, _box(60, 96, 80, 108))
    assert again["u"] == pytest.approx(near["u"], abs=0.02)


def test_lifted_object_reads_nearer_than_the_same_footprint_on_the_desk():
    on_desk = dm.object_depth_position(_depth(), _box(60, 70, 80, 82))
    m = _box(60, 70, 80, 82)
    lifted = dm.object_depth_position(_depth(obj=(m, 0.15)), m)
    assert lifted["u"] > on_desk["u"] + 0.2


def test_position_is_none_when_the_desk_is_flat_or_the_object_tiny():
    assert dm.object_depth_position(_depth(plane=(0.0, 0.0, 0.5)), _box(60, 70, 80, 82)) is None
    assert dm.object_depth_position(_depth(), _box(60, 70, 62, 72)) is None


def test_object_depth_holds_then_expires_and_clamps():
    od = dm.ObjectDepth()
    assert od.scale(0.0) is None
    od.update({"u": 0.5}, 1.0)
    assert od.scale(1.3) == pytest.approx(np.exp(0.5)) and od.scale(2.0) is None       # 오래되면 크기로 돌아간다
    od.update({"u": 9.0}, 3.0)
    assert od.scale(3.0) == pytest.approx(np.exp(od.U_MAX))
    od.update(None, 3.1)
    assert od.fail == 1


def test_reference_rows_follow_slowly_and_ignore_a_single_outlier():
    od = dm.ObjectDepth()
    for i in range(10):
        od.update({"u": 0.5, "rows": (0.55, 0.95)}, i * 0.1)
    assert od.rows == pytest.approx((0.55, 0.95), abs=1e-6) and od.n_ref == 10
    od.update({"u": 0.5, "rows": (0.60, 0.95)}, 2.0)                    # 한 번 어긋난 측정은 5%만 반영
    assert od.rows[0] == pytest.approx(0.5525, abs=1e-4)


def test_reference_is_retaken_automatically_when_the_camera_moves_and_manually_on_request():
    od = dm.ObjectDepth()
    for i in range(8):
        od.update({"u": 0.5, "rows": (0.55, 0.95)}, i * 0.1)
    gen = od.ref_generation
    for i in range(5):                                                 # 카메라가 움직여 책상이 크게 어긋남
        od.update({"u": 0.5, "rows": (0.40, 0.85)}, 1 + i * 0.1)
    assert od.reference_resets == 1 and od.ref_generation == gen + 1
    assert od.rows == pytest.approx((0.40, 0.85)) and od.n_ref == 1
    od.reset_reference()
    assert od.rows is None and od.scale(2.0) is None and od.reference_resets == 2


def test_inlier_rows_ignore_a_non_planar_background_above_the_desk():
    d = _depth()
    d[30:60, :] = 0.9                       # 책상 먼 쪽 위의 벽/셔츠: 평면에 안 맞는 영역 (프레임 위쪽 절반)
    r = dm.object_depth_position(d, _box(60, 96, 80, 108))
    assert r is not None and r["rows"][0] > 0.45          # 먼 쪽 가장자리가 벽 쪽으로 끌려가지 않는다
    fixed = dm.object_depth_position(d, _box(60, 96, 80, 108), rows=(0.5, 0.95))
    assert fixed["u"] == pytest.approx((104.5 / H - 0.5) / 0.45, abs=0.03)       # rows 를 주면 그 기준으로 정규화


def test_settings_default_to_object_size_and_the_model_option_falls_back_without_weights(monkeypatch):
    s = MouseSettings()
    assert s.depth_source == "size" and s.depth_model_range >= 3.0         # 기본은 예전 방식(물체 크기), 모델은 선택
    vp = VisionProcessor(None)
    monkeypatch.setattr(dm, "is_available", lambda: False)
    vp.set_mouse(MouseSettings(mode="off", depth_source="model"))                              # 가중치가 없어도 설정은 받아들이고 크기를 쓴다
    assert vp.mouse_info()["depth_model_available"] is False
    assert "depth_reference" in vp.mouse_info()


def test_pipeline_uses_the_model_value_and_falls_back_to_size(monkeypatch):
    vp = VisionProcessor(None)
    monkeypatch.setattr(dm, "is_available", lambda: True)

    class Svc:
        available, busy, error = True, False, None

        def submit(self, bgr, job):
            job(_depth(size=dm.INPUT_SIZE))
            return True

    vp.depth = Svc()
    vp.mouse.settings = MouseSettings(mode="object", coordinate_mode="depth", depth_source="model")

    class Obj:
        id = 1

        class out:
            mask = np.zeros((480, 640), bool)

    Obj.out.mask[380:440, 280:360] = True          # 화면 아래쪽(가까운 쪽)의 물체
    Obj.out.state = type("S", (), {"visible": True})()

    class Frame:
        image = np.zeros((480, 640, 3), np.uint8)

    vp.latest = Frame
    vp.objects = {1: Obj}
    got = vp._model_depth_scale(Obj, False, True, 1.0, 1.0)
    assert vp.mouse.model_depth and got > np.exp(0.5)               # exp(u), 화면 아래쪽(가까운 쪽) 물체는 u 가 크다
    # 오래되면 (0.6 초 뒤 결과 없음) 크기 값으로 돌아간다
    vp.depth.submit = lambda bgr, job: False
    assert vp._model_depth_scale(Obj, False, True, 1.0, 2.0) == 1.0 and not vp.mouse.model_depth
    # 펜은 대상이 아니다
    assert vp._model_depth_scale(Obj, True, True, 1.0, 2.1) == 1.0


def test_a_full_desk_traverse_moves_the_cursor_several_screen_heights_more_than_size_based():
    """책상 맨 뒤(u 0.1)에서 맨 앞(0.9)까지: 모델 방식은 range(3.0)×Δu 만큼, 크기 방식(보통 1.3배)은 훨씬 적게 움직인다."""
    from vision_input.io.depth import DepthCursor
    s = MouseSettings()

    def travel(scales, gain):
        c, total = DepthCursor(), 0.0
        for i, sc in enumerate(scales):
            _, dy = c.update(np.array([.5, .5]), float(sc), i / 30, None, smoothing=s.smoothing, gain=gain,
                             deadzone=0.003, perspective=False)
            total += dy * s.depth_sensitivity                        # 위가 +
        return abs(total)

    us = np.linspace(0.1, 0.9, 90)
    model = travel(np.exp(us), s.depth_model_range / s.depth_sensitivity)
    size = travel(np.linspace(1.0, 1.3, 90), s.depth_gain)           # 물체가 앞으로 오며 30% 커짐
    assert model == pytest.approx(0.8 * s.depth_model_range, rel=0.2)
    assert model > 3 * size
