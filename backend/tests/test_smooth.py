"""출력 안정화 필터."""

import math

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from vision_input.tracking.smooth import OneEuro, PoseSmoother


def test_one_euro_reduces_noise_on_still_signal():
    rng = np.random.default_rng(0)
    f = OneEuro(1.0, 1.0)
    xs = 500 + rng.normal(0, 1.0, 300)
    ys = [f(x, i / 30, 100) for i, x in enumerate(xs)]
    assert np.std(ys[30:]) < 0.35 * np.std(xs[30:])


def test_one_euro_follows_fast_motion_with_small_lag():
    f = OneEuro(1.0, 1.5)
    # 물체 크기 100px 가 초당 5배(500px/s) 로 움직임
    out = [f(500 * i / 60, i / 60, 100) for i in range(120)]
    lag = 500 * 119 / 60 - out[-1]
    assert lag < 25  # 1.5 프레임 분량 미만


@settings(max_examples=30, deadline=None)
@given(size=st.floats(20, 400))
def test_pose_smoother_does_not_amplify_scale_noise(size):
    """크기 추정만 흔들리고 위치는 고정일 때, 출력 위치가 흔들리면 안 된다 (이전 버그)."""
    rng = np.random.default_rng(1)
    sm = PoseSmoother()
    outs = []
    for i in range(120):
        s = size * math.exp(rng.normal(0, 0.01))
        outs.append(sm(640.0, 360.0, 0.0, 0.0, 1.0, s, i / 30)[:2])
    o = np.array(outs[10:])
    assert o.std(0).max() < 1e-6


def test_reset_jumps_immediately():
    sm = PoseSmoother()
    for i in range(30):
        sm(100.0, 100.0, 0, 0, 1, 50, i / 30)
    sm.reset()
    assert sm(400.0, 300.0, 0, 0, 1, 50, 1.1)[:2] == (400.0, 300.0)
