"""깊이 모델 기울기(롤)를 바닥 평면의 좌우 기울기로 쓰는 기본 동작. 실제 모델 없이 가짜 서비스로 검사한다."""
import math
import numpy as np
import pytest
from vision_input import depth_model as dm
from vision_input.pen import PenConfig, PenTracker
from vision_input.pen_floor import FloorModel

W, H = 1280, 720


def _fit(roll_deg, inlier=0.9):
    # 롤 = atan2(A/W, B/H): B=1 로 두고 A 를 맞춘다
    return {"A": math.tan(math.radians(roll_deg)) * W / H, "B": 1.0, "C": 0.0, "inlier_frac": inlier}


def test_plane_roll_and_a_px_follow_the_convention():
    assert dm.plane_roll_deg(_fit(5.0), (W, H)) == pytest.approx(5.0, abs=1e-6)
    r = dm.DepthRoll()
    for v in (4.9, 5.1, 5.0):
        r.add(_fit(v), (W, H))
    assert r.deg == pytest.approx(5.0, abs=0.01)
    assert r.a_px(W) == pytest.approx(-W * math.tan(math.radians(5.0)), abs=0.5)     # bench 에서 +5° → a ≈ -112 px


def test_depth_roll_needs_agreeing_measurements_and_rejects_bad_fits():
    r = dm.DepthRoll()
    r.add(_fit(5.0), (W, H))
    r.add(_fit(5.0), (W, H))
    assert r.deg is None                                  # 3 번 미만
    r.add(_fit(12.0), (W, H))
    assert r.deg is None                                  # 서로 안 맞는다
    r2 = dm.DepthRoll()
    for v in (1.0, 1.2, 0.9):
        r2.add(_fit(v, inlier=0.3), (W, H))               # 내점 비율이 낮은 적합
    assert r2.deg is None and r2.rejected == 3
    r2.add(_fit(40.0), (W, H))                            # 너무 기운 것은 평면이 아니다
    assert r2.vals == []


def test_set_touches_respects_a_fixed():
    fm = FloorModel()
    fm.a_max_px = 300.0
    fm.a_fixed = -50.0
    touches = [(10.0, 100.0 + 3.0 * 10 - 50 * (-0.4), -0.4), (20.0, 100.0 + 3.0 * 20 - 50 * 0.0, 0.0),
               (30.0, 100.0 + 3.0 * 30 - 50 * 0.4, 0.4)]
    # d = k·w + a·x − c, 여기서 c = -100 이 되도록 만들었다
    assert fm.set_touches([(w, 3.0 * w + (-50.0) * x + 100.0, x) for w, _, x in touches])
    assert fm.k == pytest.approx(3.0, abs=1e-6) and fm.a == pytest.approx(-50.0, abs=1e-6)


class _FakeService:
    available = True
    busy = False
    error = None

    def __init__(self, fit):
        self.fit, self.calls = fit, 0

    def submit(self, bgr, job):
        self.calls += 1
        job(np.zeros((dm.INPUT_SIZE[1], dm.INPUT_SIZE[0]), np.float32))
        return True


class _FakeFloorContact:
    def __init__(self):
        self.floor = FloorModel()
        self.floor.a_max_px = 300.0

    def floor_region(self, bgr, mask, size):
        return np.ones((size[1], size[0]), bool)


def _pen(monkeypatch, roll):
    fake = _FakeFloorContact()
    monkeypatch.setattr(PenTracker, "floor", property(lambda self: fake))
    monkeypatch.setattr(dm, "fit_depth_plane", lambda depth, region: _fit(roll))
    import vision_input.pen as pen_mod
    monkeypatch.setattr(pen_mod, "fit_depth_plane", lambda depth, region: _fit(roll))
    pen = PenTracker((100, 100), (100, 50), PenConfig(contact_method="floor"))
    pen.frame_w, pen.frame_h = W, H
    pen.depth_service = _FakeService(None)
    pen._floor = fake
    return pen, fake


def test_pen_applies_the_depth_roll_by_default_and_falls_back_without_it(monkeypatch):
    pen, fake = _pen(monkeypatch, 4.0)
    assert PenConfig().floor_depth_roll is True           # 기본 설정
    frame = np.zeros((H, W, 3), np.uint8)
    for i in range(4):                                    # 2초 간격으로 3 번 이상 잰다
        pen._depth_roll_tick(frame, None, 3.0 * i)
    assert pen.depth_service.calls >= 3
    assert fake.floor.a_fixed == pytest.approx(-W * math.tan(math.radians(4.0)), abs=1.0)
    st = pen._depth_roll_state()
    assert st["applied"] and st["source"] == "depth" and st["deg"] == pytest.approx(4.0, abs=0.01)
    pen.cfg.floor_depth_roll = False                      # 끄면 터치로 배운 롤로 돌아간다
    pen._depth_roll_tick(frame, None, 20.0)
    assert fake.floor.a_fixed is None and pen._depth_roll_state()["source"] == "touch"
    pen.cfg.floor_depth_roll = True
    pen.depth_service.available = False                   # 모델이 없으면 아무 것도 하지 않는다
    calls = pen.depth_service.calls
    pen._depth_roll_tick(frame, None, 40.0)
    assert pen.depth_service.calls == calls and fake.floor.a_fixed is None
