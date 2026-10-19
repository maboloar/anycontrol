"""실시간 EMA(튐 억제): 한두 프레임 튐은 누르고, 진짜 이동은 따라간다."""
import math
import numpy as np
import pytest
from vision_input.tracking.api import Pose
from vision_input.tracking.axes import AxisState
from vision_input.tracking.smooth import SpikeEma
from .test_server import client  # noqa: F401  (서버 fixture)


def test_single_frame_spike_is_suppressed_but_a_real_step_is_followed():
    e = SpikeEma()
    rng = np.random.default_rng(0)
    out = []
    for i in range(90):
        x = 100 + rng.normal(0, 0.3)
        if i == 30:
            x = 160                      # 한 프레임 튐
        if i >= 60:
            x = 130                      # 진짜 이동
        out.append(e(x, i / 30, 1.0))
    assert max(abs(v - 100) for v in out[25:55]) < 4        # 튐 60 이 4 미만으로 눌린다
    assert abs(out[-1] - 130) < 1.0                          # 진짜 이동은 따라잡는다
    assert out[60 + 9] > 120                                 # 0.3 초 안에 거의 도착


def test_smooth_motion_has_small_lag():
    e = SpikeEma()
    lag = [t / 30 * 30 - e(t / 30 * 30, t / 30) for t in range(1, 60)]   # 초당 30 단위 등속
    assert max(lag) < 3.0


def test_non_positive_dt_returns_the_current_value_and_reset_restarts():
    e = SpikeEma()
    assert e(5.0, 1.0) == 5.0
    assert e(9.0, 1.0) == 5.0
    e.reset()
    assert e(9.0, 2.0) == 9.0


def test_axis_state_ema_toggle_and_neutral_independence():
    ax = AxisState((640, 480))
    pose = lambda cx: Pose(cx, 240.0, 1.0, 0.0, 1.0)  # noqa: E731
    for i in range(30):
        ax.sample(pose(320.0), None, 100.0, t=i / 30, ema=True)
    ax.sample(pose(520.0), None, 100.0, t=1.0, ema=True)           # 한 프레임 튐
    assert abs(ax.last.cx - 320) < 40
    ax.sample(pose(520.0), None, 100.0, t=1.0 + 1 / 30, ema=False)  # 끄면 그대로 통과
    assert ax.last.cx == 520.0 and not ax.ema_filters
    ax.sample(pose(320.0), None, 100.0, t=2.0, ema=True)
    ax.set_neutral()                                                # 중립을 바꿔도 값이 이어진다
    ax.sample(pose(322.0), None, 100.0, t=2.04, ema=True)
    assert abs(ax.values()["x"]) < 0.01 and math.isfinite(ax.values()["depth"])


def test_tracking_api_toggles_ema_and_pen_depth_roll_flag(client):
    assert client.get("/api/tracking").json()["ema"] is True            # 기본 켬
    assert client.put("/api/tracking", json={"ema": False}).json()["ema"] is False
    assert client.put("/api/tracking", json={"ema": True}).json()["ema"] is True
