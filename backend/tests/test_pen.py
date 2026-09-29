"""펜 모드: 펜촉 기하, 늦게 도착한 정밀 마스크 옮기기, 책상 면 모델."""

import math

import cv2
import numpy as np
import pytest

from vision_input.pen import PenConfig, PenTracker, SurfaceModel, measure_tip, table_xy
from vision_input.tracking import InitPrompt, TrackState
from vision_input.tracking.api import Pose, RefinedMask, TrackOutput
from vision_input.tracking.desk import DeskCalibration
from vision_input.tracking.tier0 import similarity_about
from vision_input.tracking.vi_tracker import TrackerConfig, ViTracker


def pen_mask(size=(720, 1280), tip=(700, 500), tail=(600, 200), width=14) -> np.ndarray:
    m = np.zeros(size, np.uint8)
    cv2.line(m, tail, tip, 1, width)
    return m.astype(bool)


def pen_frame(tip=(700, 500), tail=(600, 200), width=14) -> np.ndarray:
    img = np.full((720, 1280, 3), 200, np.uint8)
    cv2.line(img, tail, tip, (40, 40, 40), width)
    return img


def test_measure_tip_finds_far_end_along_expected_direction():
    m = pen_mask()
    d = np.array([100.0, 300.0]) / math.hypot(100, 300)
    t = measure_tip(m, None, None, d)
    assert t is not None
    assert np.hypot(*(t.tip - (700, 500))) < 8  # 선 끝(둥근 캡 포함)
    assert t.axis @ d > 0.99
    assert 10 < t.width < 18


def test_measure_tip_rejects_blob():
    m = np.zeros((200, 200), bool)
    m[50:120, 50:120] = True
    assert measure_tip(m, None, None, np.array([0.0, 1.0])) is None


def test_measure_tip_transform_moves_tip_and_axis():
    """정밀 마스크를 M 으로 옮기면 펜촉과 축도 같은 변환을 따른다."""
    m = pen_mask()
    M = similarity_about(650, 350, 1.2, 20.0, 30.0, -10.0)
    d = np.array([100.0, 300.0]) / math.hypot(100, 300)
    base = measure_tip(m, None, None, d)
    moved = measure_tip(m, None, None, d, M)
    assert base is not None and moved is not None
    expect = M[:, :2] @ base.tip + M[:, 2]
    assert np.allclose(moved.tip, expect, atol=1e-6)
    assert moved.width == pytest.approx(base.width * 1.2, rel=1e-6)
    # 옮긴 결과는 옮긴 마스크에서 직접 잰 것과 같아야 한다
    warped = cv2.warpAffine(m.astype(np.uint8), M, (1280, 720), flags=cv2.INTER_NEAREST).astype(bool)
    direct = measure_tip(warped, None, None, moved.axis)
    assert direct is not None and np.hypot(*(direct.tip - moved.tip)) < 4


def test_edge_refinement_stays_near_mask_end():
    img = pen_frame()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    m = pen_mask()
    d = np.array([100.0, 300.0]) / math.hypot(100, 300)
    t = measure_tip(m, gray, None, d)
    assert t is not None and t.sharpness > 0
    assert np.hypot(*(t.tip - (700, 500))) < 8


def _out(mask: np.ndarray, refined: RefinedMask | None) -> TrackOutput:
    return TrackOutput(TrackState.TRACKING, (0, 0, 1, 1), Pose(650, 350), mask, 1.0, {}, refined)


def test_pen_tracker_prefers_fresh_refined_mask_and_falls_back_when_stale():
    img = pen_frame()
    good = pen_mask()
    bad = pen_mask(tip=(760, 420), tail=(600, 200), width=30)  # Tier 0: 손가락이 붙고 회전이 틀림
    ident = np.array([[1.0, 0, 0], [0, 1.0, 0]])
    p = PenTracker((700, 500), (600, 200), PenConfig(tip_min_cutoff=1000))
    p.update(img, _out(bad, RefinedMask(good, ident, 0.05)), 0.0)
    assert p.debug["src"] == "t1"
    assert np.hypot(p.tip[0] - 700, p.tip[1] - 500) < 8
    p2 = PenTracker((700, 500), (600, 200), PenConfig(tip_min_cutoff=1000))
    p2.update(img, _out(bad, RefinedMask(good, ident, 5.0)), 0.0)  # 너무 오래됨
    assert p2.debug["src"] == "t0"


def test_shortened_pen_mask_keeps_rigid_tip_and_lifts_contact():
    img = pen_frame()
    full = pen_mask()
    cut = full.copy()
    cut[350:] = False  # 손이 펜촉을 가려 보이는 몸통만 남음
    p = PenTracker((700, 500), (600, 200), PenConfig(tip_min_cutoff=1000))
    p.update(img, _out(full, None), 0.0)
    original = p.tip.copy()
    p.contact = True
    p.cur = [(0.0, 1.0)] * 5
    p.update(img, _out(cut, None), 1 / 30)
    assert p.debug["src"] == "rigid"
    assert np.linalg.norm(p.tip - original) < 5
    assert p.uncertain  # 짧은 가림에서는 획을 유지하되 입력을 차단
    p.update(img, _out(cut, None), .2)
    assert not p.contact


def test_pen_foreshortening_is_not_treated_as_occlusion():
    p = PenTracker((700, 500), (600, 200))
    p.update(pen_frame(), _out(pen_mask(), None), 0)
    mask = pen_mask(tip=(700, 500), tail=(650, 350))
    out = TrackOutput(TrackState.TRACKING, None, Pose(675, 425, math.sqrt(.5), 0, .5), mask, 1)
    p.update(pen_frame(tip=(700, 500), tail=(650, 350)), out, 1 / 30)
    assert not p.uncertain and p.debug["src"] == "t0"


def test_pen_stroke_uses_calibrated_desk_plane():
    desk = DeskCalibration.from_points(np.array([[300, 550], [1000, 550], [900, 400], [400, 400]]),
                                       (1280, 720))
    p = PenTracker((700, 500), (600, 200))
    p.manual_contact = True
    p.update(pen_frame(), _out(pen_mask(), None), 0, desk)
    assert p.cur is not None
    expected = desk.to_desk(p.tip.reshape(1, 2))[0]
    assert p.cur[-1] == pytest.approx(expected, abs=1e-5)


def test_pen_lifts_when_not_visible():
    p = PenTracker((700, 500), (600, 200))
    p.contact, p.cur = True, [(0.0, 1.0)] * 5
    p.update(pen_frame(), TrackOutput(TrackState.OCCLUDED, None, Pose(0, 0)), 0.0)
    assert not p.contact and p.tip is None
    ev = p.state()["events"]
    assert ev and ev[-1]["type"] == "up"


def test_vi_tracker_pen_exposes_refined_mask_without_tier1():
    """Tier 1 이 꺼져 있어도 등록 마스크가 첫 정밀 마스크가 되고, 포즈 변화만큼 옮겨진다."""
    img = pen_frame()
    m = pen_mask()
    tr = ViTracker(TrackerConfig(tier1="off"))
    out = tr.add(img, 1, InitPrompt(box=(590, 190, 710, 510), mask=m, kind="pen"))
    assert out.refined is not None and out.refined.mask.shape == m.shape
    assert np.allclose(out.refined.M, [[1, 0, 0], [0, 1, 0]], atol=1e-6)
    shifted = np.roll(img, 12, axis=1)
    out2 = tr.step(shifted, 1 / 30)[1]
    assert out2.refined is not None
    assert out2.refined.M[0, 2] > 3  # 오른쪽으로 옮겨짐
    obj = ViTracker(TrackerConfig(tier1="off"))
    assert obj.add(img, 1, InitPrompt(mask=m)).refined is None  # 일반 물체는 없음


def test_surface_model_fits_lower_boundary_and_calibrates():
    rng = np.random.default_rng(0)
    w = rng.uniform(8, 24, 400)
    y_surf = 300 + 12 * w
    touching = rng.random(400) < 0.5
    y = np.where(touching, y_surf + rng.normal(0, 1.0, 400), y_surf - rng.uniform(10, 120, 400))
    s = SurfaceModel()
    for a, b in zip(w, y, strict=True):
        s.add(float(a), float(b))
    assert s.fit()
    assert s.K == pytest.approx(12, rel=0.15)
    # expectile 은 든 점 쪽으로 조금 치우친다(여기서 약 13px). 중요한 것은 닿음과 확실히 든 상태의 구분.
    h = np.array([s.height(float(a), float(b)) for a, b in zip(w, y, strict=True)])
    thr = 0.6 * w + 13
    assert np.mean(h[touching] < thr[touching]) > 0.97
    high = ~touching & (y < y_surf - 50)
    assert np.mean(h[high] > thr[high]) > 0.97
    s2 = SurfaceModel()
    assert s2.calibrate([(10, 420), (20, 540)]) and s2.K == pytest.approx(12) and s2.fixed


def test_table_xy_undoes_perspective():
    # 카메라 높이 1, 소실선 y=360: 같은 폭의 가로선은 멀수록(위) 화면에서 짧아진다
    f = 900.0
    near = [table_xy(np.array([x, 560.0]), 640, f, 360) for x in (540, 740)]
    far = [table_xy(np.array([x, 460.0]), 640, f, 360) for x in (590, 690)]
    assert near[0] and near[1] and far[0] and far[1]
    assert near[1][0] - near[0][0] == pytest.approx(far[1][0] - far[0][0], rel=1e-6)
    assert far[0][1] > near[0][1]  # 멀수록 Z 가 크다
    assert table_xy(np.array([640, 350.0]), 640, f, 360) is None  # 소실선 위는 책상이 아님


def test_hover_cursor_shares_stroke_projection_without_creating_a_stroke():
    p = PenTracker((700, 500), (600, 200))
    p.update(pen_frame(), _out(pen_mask(), None), 0.)
    assert not p.contact
    point = p.state(consume=False)['draw_point']
    assert point is not None and not p.cur
    p.manual_contact = True
    p._decide(.01)
    assert np.allclose(p.cur[-1], point, atol=1e-5)
    p.uncertain = True
    assert p.state(consume=False)['draw_point'] is None


def test_overhead_hover_cursor_uses_same_axes_as_drawing():
    p = PenTracker((700, 500), (600, 200))
    p.update(pen_frame(), _out(pen_mask(), None), 0., overhead=True)
    assert p.drawing_point() == (p.tip[0] / p.frame_w, -p.tip[1] / p.frame_w)
