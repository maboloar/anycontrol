"""Tier 0 구성 요소와 ViTracker 기본 동작."""

import cv2
import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vision_input.eval.harness import run_synth
from vision_input.eval.synth import SynthSpec
from vision_input.tracking import InitPrompt, TrackState
from vision_input.tracking.kalman import PoseKalman, pose_meas
from vision_input.tracking.tier0 import (
    UNSEEN_PROB,
    ColorModel,
    _lab_index,
    refine_mask,
    sample_points,
    similarity_about,
    similarity_params,
    track_points,
)
from vision_input.tracking.gpu import ml_available
from vision_input.tracking.vi_tracker import TrackerConfig, ViTracker


# ---------------------------------------------------------------- Kalman
@settings(max_examples=40, deadline=None)
@given(ops=st.lists(st.tuples(st.floats(0.005, 0.2), st.floats(-50, 50), st.floats(0.3, 30)), min_size=1, max_size=40))
def test_kalman_covariance_stays_symmetric_psd(ops):
    kf = PoseKalman(100, 100, 80)
    for dt, dz, sig in ops:
        kf.predict(dt)
        kf.update(pose_meas(kf.x[0] + dz, kf.x[1] - dz, kf.x[2], kf.x[3], sig), gate=False)
        assert np.allclose(kf.P, kf.P.T, atol=1e-6)
        assert np.linalg.eigvalsh(kf.P).min() > -1e-6


def test_kalman_gate_rejects_outlier_and_tracks_motion():
    kf = PoseKalman(0, 0, 100)
    for i in range(1, 31):  # 등속 60px/s
        kf.predict(1 / 30)
        kf.update(pose_meas(2.0 * i, 0, 0, 0, 1.0))
    assert kf.velocity[0] == pytest.approx(60, rel=0.15)
    before = kf.pose
    kf.predict(1 / 30)
    assert not kf.update(pose_meas(500, 500, 0, 0, 1.0))  # 튀는 측정
    assert abs(kf.pose[0] - before[0]) < 5


def test_kalman_damping_slows_velocity():
    kf = PoseKalman(0, 0, 100)
    kf.x[4] = 100.0
    for _ in range(30):
        kf.predict(1 / 30, damping=4.0)
    assert abs(kf.velocity[0]) < 5


# ---------------------------------------------------------------- 점 추적
def _textured(h=240, w=320, seed=0):
    rng = np.random.default_rng(seed)
    return cv2.GaussianBlur(rng.integers(0, 255, (h, w), dtype=np.uint8), (0, 0), 1.5)


@pytest.mark.parametrize("s,ang,tx,ty", [(1.0, 0, 6, -3), (1.08, 5, 2, 2), (0.93, -8, -4, 5)])
def test_track_points_recovers_similarity(s, ang, tx, ty):
    img = _textured()
    M = similarity_about(160, 120, s, ang, tx, ty)
    img2 = cv2.warpAffine(img, M, (320, 240), borderMode=cv2.BORDER_REFLECT)
    mask = np.zeros((240, 320), bool)
    mask[70:170, 100:220] = True
    pts = sample_points(img, mask, None)
    assert len(pts) >= 30
    mo = track_points(img, img2, pts, None, 110)
    assert mo.M is not None and mo.ratio > 0.7
    s2, a2 = similarity_params(mo.M)
    assert s2 == pytest.approx(s, abs=0.02) and a2 == pytest.approx(ang, abs=1.0)
    assert mo.M[:, 2] == pytest.approx(M[:, 2], abs=1.5)


def test_sample_points_uses_grid_on_flat_object_and_respects_exclude():
    img = np.full((200, 200), 40, np.uint8)
    mask = np.zeros((200, 200), bool)
    mask[50:150, 50:150] = True
    excl = np.zeros_like(mask)
    excl[:, :100] = True
    pts = sample_points(img, mask, excl)
    assert len(pts) > 10  # 코너가 없어도 격자 점
    assert (pts[:, 0] >= 100).all()


# ---------------------------------------------------------------- 색 모델·마스크 정제
def test_color_model_unseen_colors_lean_background():
    img = np.zeros((100, 100, 3), np.uint8)
    img[:, :50] = (30, 30, 30)       # 물체: 어두움
    img[:, 50:] = (200, 200, 200)    # 배경: 밝음
    idx = _lab_index(img)
    fg = np.zeros((100, 100), bool); fg[:, :50] = True
    cm = ColorModel()
    cm.fit(idx, fg, ~fg)
    assert cm.prob(idx[0:1, 0:1])[0, 0] > 0.9
    assert cm.prob(idx[0:1, 99:100])[0, 0] < 0.1
    # 물체·배경 어느 쪽에서도 본 적 없는 색 (채도 높은 초록)
    unseen = _lab_index(np.full((1, 1, 3), (0, 200, 0), np.uint8))
    assert cm.prob(unseen)[0, 0] == pytest.approx(UNSEEN_PROB, abs=0.02)
    assert cm.separability() > 0.6  # 인접 칸 평활로 1 보다 낮다


def test_refine_mask_removes_occluder_inside_prior():
    """사전 마스크 깊은 안쪽이라도 물체에서 본 적 없는 색(가리는 손)은 빠진다."""
    prob = np.full((120, 160), 0.9, np.float32)
    prior = np.zeros((120, 160), bool); prior[20:100, 20:140] = True
    prob[~prior] = 0.05
    prob[30:90, 60:100] = UNSEEN_PROB  # 손
    m, agree = refine_mask(prob, prior, 90, None, 1.5)
    assert not m[60, 80] and m[25, 25] and m[60, 130]
    assert 0.5 < agree < 0.9


# ---------------------------------------------------------------- ViTracker
def _spec(obj, cond, seed=11, frames=90):
    return SynthSpec(f"t/{obj}-{cond}", obj, (cond,), seed, frames, 30.0, (480, 270))


def _tier0():
    return ViTracker(TrackerConfig(tier1="off"))


@pytest.mark.parametrize("obj,cond", [("textured", "pull"), ("dark", "rotate"), ("dark", "grasp"),
                                      ("pen", "lighting")])
def test_vi_tracks_basic_cases(obj, cond):
    r = run_synth(_tier0, _spec(obj, cond))
    assert r["success"] >= 0.9, r


def test_vi_goes_occluded_not_false_positive_under_full_occlusion():
    r = run_synth(_tier0, _spec("dark", "full_occlusion", frames=120))
    assert r["fp_rate"] is not None and r["fp_rate"] <= 0.2, r


@pytest.mark.skipif(not ml_available(), reason="EfficientTAM 모델 없음")
def test_vi_with_tier1_sim_recovers_after_full_occlusion():
    """Tier 1(sim) 이 붙으면 완전 가림 뒤 다시 잡는다."""
    r0 = run_synth(_tier0, _spec("dark", "full_occlusion", frames=120))
    r1 = run_synth(lambda: ViTracker(TrackerConfig(tier1="sim")), _spec("dark", "full_occlusion", frames=120))
    assert r1["success"] >= r0["success"] and r1["success"] >= 0.8, (r0, r1)
    assert (r1["fp_rate"] or 0) <= 0.2


def test_vi_output_contract_visible_implies_pose():
    tr = _tier0()
    img = np.full((180, 320, 3), 190, np.uint8)
    cv2.rectangle(img, (120, 70), (200, 110), (30, 30, 30), -1)
    m = np.zeros((180, 320), bool); m[70:111, 120:201] = True
    out = tr.add(img, 1, InitPrompt(box=(120, 70, 201, 111), mask=m))
    assert out.state == TrackState.TRACKING and out.pose is not None and out.pose.scale == pytest.approx(1.0)
    for i in range(1, 10):
        o = tr.step(img, i / 30)[1]
        assert (not o.state.visible) or o.pose is not None
        assert o.mask is None or o.mask.shape == (180, 320)
