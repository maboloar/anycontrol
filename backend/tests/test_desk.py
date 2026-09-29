"""책상 보정: 합성 카메라에서 호모그래피 복원, 수평(퇴화) 판정, 책상 위 회전 추정."""

import math

import cv2
import numpy as np
import pytest

from vision_input.tracking.desk import DeskAxes, DeskCalibration, order_quad


def camera(pitch_deg: float, height=0.5, f=900.0, size=(1280, 720)):
    """책상(Y=0)을 높이 height 에서 아래로 pitch 만큼 숙여 보는 핀홀 카메라. 책상 점 (X, Z) → 이미지."""
    w, h = size
    p = math.radians(pitch_deg)
    R = np.array([[1, 0, 0], [0, math.cos(p), -math.sin(p)], [0, math.sin(p), math.cos(p)]])
    K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]])

    def proj(X, Z):
        Pw = np.array([X - 0.15, height, Z + 0.4])  # 카메라 좌표 (y 아래 +): 책상은 카메라 아래
        pc = R @ Pw
        uv = K @ pc
        return uv[:2] / uv[2]

    return proj


def quad_img(proj, W=0.297, D=0.21):
    return np.array([proj(0, 0), proj(W, 0), proj(W, D), proj(0, D)])


@pytest.mark.parametrize("pitch", [25, 45, 70])
def test_homography_recovers_desk_points(pitch):
    proj = camera(pitch)
    q = quad_img(proj)
    cal = DeskCalibration.from_points(q[[2, 0, 3, 1]], (1280, 720))  # 순서 섞어도 됨
    for X, Z in [(0.1, 0.05), (0.25, 0.18), (0.4, 0.3)]:
        got = cal.to_desk(np.array([proj(X, Z)]))[0]
        assert np.allclose(got, [X, Z], atol=1e-3)
    assert cal.yaw_ok


def test_grazing_camera_is_flagged():
    cal = DeskCalibration.from_points(quad_img(camera(3, height=0.05)), (1280, 720))
    assert cal.tilt < 0.15 and not cal.yaw_ok
    with pytest.raises(ValueError):
        DeskCalibration.from_points(np.array([[0, 0], [10, 0], [20, 0], [30, 0]], float), (1280, 720))


def test_order_quad():
    q = order_quad(np.array([[100, 50], [10, 200], [200, 210], [20, 60]], float))
    assert q.tolist() == [[10, 200], [200, 210], [100, 50], [20, 60]]


def test_desk_yaw_of_flat_object_rotating():
    proj = camera(50)
    cal = DeskCalibration.from_points(quad_img(proj), (1280, 720))
    da = DeskAxes()
    out = []
    for yaw in (0, 20, 40):
        a = math.radians(yaw)
        corners = [(0.2 + 0.08 * math.cos(a) * sx - 0.02 * math.sin(a) * sy,
                    0.15 + 0.08 * math.sin(a) * sx + 0.02 * math.cos(a) * sy)
                   for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        poly = np.array([proj(X, Z) for X, Z in corners], np.int32)
        m = np.zeros((720, 1280), np.uint8)
        cv2.fillConvexPoly(m, poly, 1)
        d = da.measure(cal, m.astype(bool))
        assert d is not None and d.yaw is not None
        out.append(d.yaw)
    assert out[1] - out[0] == pytest.approx(20, abs=3)
    assert out[2] - out[0] == pytest.approx(40, abs=3)
