"""책상 평면 보정: 책상 위에 놓은 종이(기본 A4 가로)의 네 모서리 → 화면↔책상 호모그래피.

책상 좌표 (미터): X = 종이 가까운 변 왼쪽 모서리에서 오른쪽, Z = 카메라에서 멀어지는 쪽.
물체 축
- desk_x, desk_z: 물체가 책상에 닿은 점(보이는 마스크 아래 가운데)을 책상에 투영
- desk_yaw: 마스크 전체를 책상에 투영한 주축 각도 (책상에 납작하게 놓인 물체용, 도)
카메라가 거의 수평이면 종이가 화면에서 납작한 띠가 되어 앞뒤·회전 해상도가 없다 → yaw_ok=False 로 알린다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from .measure import AngleTracker, bbox


def order_quad(pts: np.ndarray) -> np.ndarray:
    """아무 순서로 찍은 네 점 → [가까운 왼쪽, 가까운 오른쪽, 먼 오른쪽, 먼 왼쪽] (화면 아래 = 가까움)."""
    p = pts[np.argsort(pts[:, 1])]
    far, near = p[:2], p[2:]
    near = near[np.argsort(near[:, 0])]
    far = far[np.argsort(far[:, 0])]
    return np.array([near[0], near[1], far[1], far[0]], np.float64)


def mask_foot(mask: np.ndarray, step: int = 2) -> tuple[float, float] | None:
    """보이는 마스크가 책상에 닿은 점 (px): 아래 끝 띠의 가운데.
    가장 아래 한 픽셀(max) 대신 아래쪽 1% 분위수를 끝으로 삼고, 그 위 물체 높이 5% 띠의 x 중앙값을 쓴다.
    마스크 가장자리가 한두 줄 떨리거나 튀어나온 점 하나에 덜 흔들린다. (물체 마우스 원근 보정의 기준점 측정용)"""
    bx, by, bw, bh = bbox(mask)
    if bw <= 0 or bh <= 0:
        return None
    y0, x0 = by - by % step, bx - bx % step
    ys, xs = np.nonzero(mask[y0:by + bh:step, x0:bx + bw:step])
    if xs.size < 5:
        return None
    ys = ys * float(step) + y0
    xs = xs * float(step) + x0
    yb = float(np.quantile(ys, 0.99))
    band = max(2.0 * step, 0.05 * bh)
    sel = ys >= yb - band
    return float(np.median(xs[sel])), yb
@dataclass
class DeskCalibration:
    H: np.ndarray           # 이미지 px → 책상 m
    quad: np.ndarray        # 정렬된 이미지 점 (4, 2)
    size: tuple[float, float]
    tilt: float             # 1 = 위에서 내려다봄, 0 = 수평 (종이의 겉보기 앞뒤/좌우 비 ÷ 실제 비)
    frame_size: tuple[int, int]

    @property
    def yaw_ok(self) -> bool:
        return self.tilt >= 0.15

    @classmethod
    def from_points(cls, pts_px: np.ndarray, frame_size: tuple[int, int], width_m: float = 0.297,
                    depth_m: float = 0.210) -> DeskCalibration:
        q = order_quad(np.asarray(pts_px, np.float64))
        dst = np.array([[0, 0], [width_m, 0], [width_m, depth_m], [0, depth_m]], np.float64)
        a, b = q[2] - q[0], q[3] - q[1]
        area = 0.5 * abs(a[0] * b[1] - a[1] * b[0])
        if area < 50:
            raise ValueError("네 점이 너무 가깝거나 한 줄에 있습니다")
        H = cv2.getPerspectiveTransform(q.astype(np.float32), dst.astype(np.float32)).astype(np.float64)
        w_img = 0.5 * (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3]))
        d_img = 0.5 * (abs(q[0][1] - q[3][1]) + abs(q[1][1] - q[2][1]))  # 앞뒤는 화면 세로로만 보인다
        tilt = float((d_img / max(w_img, 1e-6)) / (depth_m / width_m))
        return cls(H, q, (width_m, depth_m), min(1.5, tilt), frame_size)

    def to_desk(self, pts: np.ndarray) -> np.ndarray:
        return cv2.perspectiveTransform(np.asarray(pts, np.float64).reshape(-1, 1, 2), self.H).reshape(-1, 2)

    def info(self) -> dict:
        w, h = self.frame_size
        return {"quad": [[round(x / w, 4), round(y / h, 4)] for x, y in self.quad], "size": list(self.size),
                "tilt": round(self.tilt, 3), "yaw_ok": self.yaw_ok}


@dataclass
class DeskMeasure:
    x: float
    z: float
    yaw: float | None


class DeskAxes:
    """물체별 책상 축 측정기 (각도 연속화 상태를 가진다)."""

    def __init__(self) -> None:
        self.angle = AngleTracker()

    def measure(self, cal: DeskCalibration, mask: np.ndarray) -> DeskMeasure | None:
        ys, xs = np.nonzero(mask[::4, ::4])
        if xs.size < 5:
            return None
        xs, ys = xs * 4.0 + 2, ys * 4.0 + 2
        yb = ys.max()
        foot_x = float(np.median(xs[ys >= yb - 8]))
        fx, fz = cal.to_desk(np.array([[foot_x, yb]]))[0]
        yaw = None
        if cal.yaw_ok:
            P = cal.to_desk(np.stack([xs, ys], 1))
            ok = np.isfinite(P).all(1)
            if ok.sum() >= 5:
                P = P[ok] - P[ok].mean(0)
                ev, evec = np.linalg.eigh(np.cov(P.T))
                if ev[1] > 1.5 * max(ev[0], 1e-12):  # 길쭉해야 방향이 정해진다
                    u = evec[:, 1]
                    yaw = self.angle.update(math.degrees(math.atan2(u[1], u[0])), True)
        return DeskMeasure(float(fx), float(fz), yaw)
