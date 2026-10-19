"""정지 잠금: 상태 전이, 측정 게이트, 추적기 통합 (모델 없이 Tier 0 로)."""

import dataclasses
import math

import cv2
import numpy as np
import pytest

from vision_input.tracking.api import InitPrompt, TrackState
from vision_input.tracking.still import StillConfig, StillLock
from vision_input.tracking.vi_tracker import TrackerConfig, ViTracker


# ---------------------------------------------------------------- StillLock 단위
def lock_ready(**kw) -> StillLock:
    cfg = StillConfig(enabled=True, **kw)
    lk = StillLock(cfg)
    m = np.zeros((40, 40), bool)
    m[10:30, 10:30] = True
    for _ in range(cfg.enter_frames):
        lk.observe(True, m)
    assert lk.ready(hand_frac=0.0, region_conf=1.0, tracking=True, disagree=0)
    lk.lock()
    return lk


def test_lock_needs_enough_calm_frames_and_no_hand_and_region_support():
    cfg = StillConfig(enabled=True)
    lk = StillLock(cfg)
    m = np.ones((20, 20), bool)
    for _ in range(cfg.enter_frames - 1):
        lk.observe(True, m)
    ok = dict(hand_frac=0.0, region_conf=1.0, tracking=True, disagree=0)
    assert not lk.ready(**ok)
    lk.observe(True, m)
    assert lk.ready(**ok)
    assert not lk.ready(**{**ok, "hand_frac": 0.3})
    assert not lk.ready(**{**ok, "region_conf": 0.1})
    assert not lk.ready(**{**ok, "disagree": 1})
    lk.observe(False, m)                                   # 한 번이라도 움직임이 있으면 처음부터
    assert not lk.ready(**ok)
    assert not StillLock(StillConfig(enabled=False)).ready(**ok)


def test_stable_mask_is_a_majority_vote_that_removes_flicker():
    lk = StillLock(StillConfig(enabled=True, enter_frames=5, mask_votes=9))
    rng = np.random.default_rng(0)
    base = np.zeros((30, 30), bool)
    base[8:22, 8:22] = True
    for _ in range(9):
        flick = base.copy()
        noise = rng.random(base.shape) < 0.05              # 가장자리 5% 깜빡임
        flick ^= noise
        lk.observe(True, flick)
    stable = lk.lock()
    assert (stable & base).sum() / (stable | base).sum() > 0.97


def test_accumulated_motion_commits_only_past_noise_and_noise_does_not_accumulate():
    lk = lock_ready()
    rng = np.random.default_rng(1)
    size = 100.0
    # 평균 0 잡음은 √n 으로만 쌓이므로 오래 둬도 반영되지 않는다
    commits = sum(lk.integrate(np.array([rng.normal(0, 0.04), rng.normal(0, 0.04), 0.0, 0.0]), size) is not None
                  for _ in range(60))
    assert commits == 0
    # 느린 실제 이동(0.15 px/프레임)은 결국 반영된다
    lk2 = lock_ready()
    got = None
    for i in range(20):
        step = lk2.integrate(np.array([0.15, 0.0, 0.0, 0.0]), size)
        if step is not None:
            got = (i, step)
            break
    assert got is not None and got[0] < 12 and got[1][0] >= 1.4   # 한계(물체 크기 1.5% = 1.5px) 근처에서 한 번에 반영
    assert abs(lk2.acc[0]) < 0.8                                                      # 반영 뒤 누적은 비워진다


def test_measurements_are_gated_until_deviation_is_confirmed_repeatedly():
    lk = lock_ready(confirm=3)
    size = 100.0
    assert not lk.accept("t1", 0.5, 0.004, 0.2, size)                 # 잡음 수준: 버림
    assert not lk.accept("refresh", 1.0, 0.007, None, size)           # 2초마다 오는 크기 보정(0.7%)도 버림
    assert not lk.accept("t1", 9.0, None, None, size)                 # 크게 벗어나도 한 번은 버린다 (튐 방지)
    assert not lk.accept("region", 9.0, None, None, size)
    assert lk.accept("t1", 9.0, None, None, size)                     # 연속 3번이면 받는다 (호출한 쪽이 푼다)
    lk2 = lock_ready(confirm=3)
    lk2.accept("t1", 9.0, None, None, size)
    lk2.accept("t1", 0.1, None, None, size)                           # 중간에 돌아오면 횟수 초기화
    assert lk2.breach == 0
    assert StillLock(StillConfig(enabled=True)).accept("t1", 99.0, None, None, size)   # 안 잠겼으면 항상 받는다


def test_release_reports_reason_and_clears_state():
    lk = lock_ready()
    assert lk.release("motion") and not lk.locked
    assert lk.stats.releases == {"motion": 1}
    assert not lk.release("motion")                                   # 이미 풀렸으면 False
    lk3 = lock_ready(lost_points_frames=3)
    assert not lk3.missing_points() and not lk3.missing_points() and lk3.missing_points()


# ---------------------------------------------------------------- ViTracker 통합 (Tier 1 없이)
def scene(shift=0.0, noise_seed=0, size=(360, 640), sigma=2.0):
    rng = np.random.default_rng(noise_seed)
    img = np.full((*size, 3), 150, np.uint8)
    cv2.randu(img, 100, 200)                                    # 배경 무늬
    obj = np.zeros((*size, 3), np.uint8)
    x0 = 250 + int(round(shift))
    cv2.rectangle(img, (x0, 130), (x0 + 120, 210), (30, 40, 200), -1)
    for k in range(14):                                         # 점 추적이 잡을 무늬
        cv2.circle(img, (x0 + 12 + 8 * k, 150 + 20 * (k % 3)), 4, (240, 240, 240), -1)
    img = np.clip(img.astype(np.float32) + rng.normal(0, sigma, img.shape), 0, 255).astype(np.uint8)
    m = np.zeros(size, bool)
    m[130:211, x0:x0 + 121] = True
    return img, m


def make(enabled: bool):
    cfg = dataclasses.replace(TrackerConfig(tier1="off"), still=StillConfig(enabled=enabled))
    return ViTracker(cfg)


def run_still(enabled: bool, n=90):
    tr = make(enabled)
    img0, m0 = scene()
    tr.add(img0, 1, InitPrompt(mask=m0))
    poses, masks, locked = [], [], []
    for i in range(1, n):
        img, _ = scene(noise_seed=i)
        out = tr.step(img, i / 30.0)[1]
        poses.append((out.pose.cx, out.pose.cy, out.pose.scale))
        masks.append(out.mask.copy())
        locked.append(bool(tr.tracks[1].still and tr.tracks[1].still.locked))
    return tr, np.array(poses), masks, locked


def test_tracker_locks_on_a_still_object_and_freezes_pose_and_mask():
    tr, poses, masks, locked = run_still(True)
    assert any(locked) and locked[-1]
    first = locked.index(True)
    assert first <= 25
    tail = slice(first + 3, None)
    assert np.ptp(poses[tail, 0]) < 0.05 and np.ptp(poses[tail, 1]) < 0.05 and np.ptp(poses[tail, 2]) < 1e-3
    assert all((masks[i] == masks[-1]).all() for i in range(first + 3, len(masks)))   # 윤곽이 깜빡이지 않는다
    assert tr.tracks[1].state == TrackState.TRACKING


def test_lock_is_on_by_default_and_can_be_turned_off():
    assert TrackerConfig().still.enabled is True
    tr = make(False)
    img0, m0 = scene()
    tr.add(img0, 1, InitPrompt(mask=m0))
    assert tr.tracks[1].still is None


def test_motion_releases_the_lock_quickly_and_the_object_is_followed():
    tr = make(True)
    img0, m0 = scene()
    tr.add(img0, 1, InitPrompt(mask=m0))
    t = 0
    for i in range(1, 40):
        tr.step(scene(noise_seed=i)[0], i / 30.0)
        t = i
    assert tr.tracks[1].still.locked
    x_start = tr.tracks[1].kf.x[0]
    first_free = None
    for k in range(1, 25):                                        # 프레임당 3px (화면 640 폭 기준) 로 움직인다
        out = tr.step(scene(shift=3.0 * k, noise_seed=100 + k)[0], (t + k) / 30.0)[1]
        if first_free is None and not tr.tracks[1].still.locked:
            first_free = k
    assert first_free is not None and first_free <= 3              # 몇 프레임 안에 풀린다
    moved = tr.tracks[1].kf.x[0] - x_start
    assert moved == pytest.approx(3.0 * 24, abs=10)                # 실제 이동을 따라간다
    assert tr.tracks[1].still.stats.releases.get("motion", 0) >= 1


def test_pens_are_never_locked():
    cfg = dataclasses.replace(TrackerConfig(tier1="off"), still=StillConfig(enabled=True))
    tr = ViTracker(cfg)
    img0, m0 = scene()
    tr.add(img0, 1, InitPrompt(mask=m0, kind="pen"))
    assert tr.tracks[1].still is None
