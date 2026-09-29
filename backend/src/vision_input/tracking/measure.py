"""마스크에서 축 값을 잰다.

물체 종류와 무관한 기하량만 쓴다.
- 중심(cx, cy): 면적 중심
- 크기: sqrt(면적). 등록 대비 비율 = scale (옆에서 보면 깊이 신호)
- 주축 각도: 2차 모멘트 고유벡터. 축은 방향이 없으므로 180° 주기이며,
  AngleTracker 가 직전 값과 이어지게 펼친다. 거의 원형이면 각도가 정의되지 않아 무효로 표시한다.
- elongation: 주축/부축 길이비 (면외 회전 시 변함)
- 바닥 접촉선: 마스크 아래쪽 경계. 손은 대부분 위에서 쥐므로 가림에 가장 덜 영향을 받는 부분이다.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import cv2
import numpy as np

ROUND_ELONGATION = 1.12  # 이보다 둥글면 주축 각도가 불안정


@dataclass(slots=True)
class MaskMeasure:
    cx: float
    cy: float
    area: float           # px²
    size: float           # sqrt(area)
    angle: float          # 주축 각도, 도, (-90, 90] (화면 기준, 시계방향 +; y 가 아래로)
    angle_valid: bool
    elongation: float     # >= 1
    box: tuple[float, float, float, float]
    bottom_y: float       # 접촉선 (아래쪽 경계의 강건한 추정)
    bottom_width: float   # 접촉선 근처 폭

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items()}



def bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    """0 이 아닌 픽셀의 경계 (x, y, w, h). 비었으면 w = h = 0."""
    m = mask.view(np.uint8) if mask.dtype == bool else mask
    if m.dtype != np.uint8:
        m = (m != 0).view(np.uint8)
    return cv2.boundingRect(np.ascontiguousarray(m))

def measure_mask(mask: np.ndarray, weights: np.ndarray | None = None) -> MaskMeasure | None:
    """mask: bool/uint8 (H, W). weights: 픽셀 신뢰도(선택, 경계 불확실성 등)."""
    m = mask.astype(bool)
    ys, xs = np.nonzero(m)
    n = xs.size
    if n < 6:
        return None
    if weights is not None:
        w = weights[ys, xs].astype(np.float64)
        wsum = float(w.sum())
        if wsum <= 0:
            return None
    else:
        w, wsum = None, float(n)
    xf, yf = xs.astype(np.float64), ys.astype(np.float64)
    cx = float((xf * w).sum() / wsum) if w is not None else float(xf.mean())
    cy = float((yf * w).sum() / wsum) if w is not None else float(yf.mean())
    dx, dy = xf - cx, yf - cy
    if w is not None:
        cxx, cyy, cxy = (w * dx * dx).sum() / wsum, (w * dy * dy).sum() / wsum, (w * dx * dy).sum() / wsum
    else:
        cxx, cyy, cxy = (dx * dx).mean(), (dy * dy).mean(), (dx * dy).mean()
    # 2x2 대칭 행렬 고유값
    tr, det = cxx + cyy, cxx * cyy - cxy * cxy
    disc = math.sqrt(max(tr * tr / 4 - det, 0.0))
    l1, l2 = tr / 2 + disc, max(tr / 2 - disc, 1e-9)
    elong = math.sqrt(l1 / l2) if l2 > 0 else 1e6
    ang = 0.5 * math.degrees(math.atan2(2 * cxy, cxx - cyy))  # (-90, 90]
    if ang <= -90:
        ang += 180
    area = float(n)
    x1, x2 = float(xs.min()), float(xs.max() + 1)
    y1, y2 = float(ys.min()), float(ys.max() + 1)
    # 접촉선: 열마다 가장 아래 픽셀의 90 분위 (가는 돌출부·잡음에 강함)
    col_bottom = _column_bottoms(m, int(x1), int(x2))
    bottom = float(np.percentile(col_bottom, 90)) + 1 if col_bottom.size else y2
    band = max(2.0, 0.08 * (y2 - y1))
    near = col_bottom >= bottom - 1 - band
    bottom_width = float(near.sum())
    return MaskMeasure(cx, cy, area, math.sqrt(area), float(ang), elong >= ROUND_ELONGATION, float(elong),
                       (x1, y1, x2, y2), bottom, bottom_width)


def _column_bottoms(m: np.ndarray, x1: int, x2: int) -> np.ndarray:
    sub = m[:, x1:x2]
    has = sub.any(0)
    if not has.any():
        return np.zeros(0)
    # 각 열에서 마지막 True 의 행 번호
    rev = sub[::-1].argmax(0)
    bottoms = (sub.shape[0] - 1 - rev).astype(np.float64)
    return bottoms[has]


class AngleTracker:
    """180° 주기 각도를 연속 값으로 펼친다.

    측정은 (-90, 90] 이지만 물체를 계속 돌리면 연속으로 늘어나야 한다.
    한 번에 ±90° 이상 돈 것은 구분할 수 없으므로 가장 가까운 쪽을 고른다(프레임 간 회전이 90° 미만이라는 가정).
    angle_valid=False(거의 원형) 인 측정은 무시하고 직전 값을 유지한다.
    """

    def __init__(self) -> None:
        self.value: float | None = None

    def update(self, measured: float, valid: bool = True) -> float | None:
        if not valid:
            return self.value
        if self.value is None:
            self.value = measured
            return self.value
        d = (measured - self.value + 90.0) % 180.0 - 90.0
        self.value += d
        return self.value

    def reset(self, value: float | None = None) -> None:
        self.value = value


def mask_contour(mask: np.ndarray, max_points: int = 120) -> list[list[float]]:
    """오버레이용 바깥 윤곽 (가장 큰 성분). 점 수를 제한한다."""
    m = mask.astype(np.uint8)
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return []
    c = max(cs, key=cv2.contourArea)
    peri = cv2.arcLength(c, True)
    eps = max(1.0, peri / (max_points * 2))
    while True:
        approx = cv2.approxPolyDP(c, eps, True)
        if len(approx) <= max_points:
            break
        eps *= 1.5
    return approx.reshape(-1, 2).astype(float).tolist()


def largest_component(mask: np.ndarray) -> tuple[np.ndarray, float]:
    """가장 큰 연결 성분과, 전체 면적 중 그 비율."""
    m = mask.astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n <= 1:
        return m.astype(bool), 1.0 if m.any() else 0.0
    areas = stats[1:, cv2.CC_STAT_AREA]
    k = int(np.argmax(areas)) + 1
    return lab == k, float(areas.max() / areas.sum())
