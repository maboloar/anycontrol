"""Tier 0: 매 프레임 빠른 전파 (작업 해상도에서).

두 독립 신호
1. 점 추적: 마스크 안(가림 영역 제외)의 코너+격자 점을 피라미드 LK 로 따라가 프레임 간
   유사변환을 RANSAC 으로 구한다. 무늬 있는 물체에서 강하다.
2. 영역 모델: 물체/주변 색 분포(Lab) 로 픽셀별 물체 확률을 만들고, 워프한 직전 마스크를
   사전 확률로 합쳐 마스크를 다시 정한다. 무늬 없는 물체에서 강하다.
둘 다 물체 종류에 대한 가정 없이 크기 상대값으로만 동작한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# ---------------------------------------------------------------- 색 모델
L_BINS, A_BINS, B_BINS = 8, 12, 12


def _lab_index(bgr: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    li = (lab[..., 0].astype(np.int32) * L_BINS) >> 8
    ai = (lab[..., 1].astype(np.int32) * A_BINS) >> 8
    bi = (lab[..., 2].astype(np.int32) * B_BINS) >> 8
    return (li * A_BINS + ai) * B_BINS + bi


UNSEEN_PROB = 0.2  # 물체에서 본 적 없는 색은 배경 쪽으로 기운다 ("물체 = 물체에서 본 색")
_EPS = 1e-4


def _smooth3(h: np.ndarray) -> np.ndarray:
    """(L, a, b) 각 축으로 [1,2,1]/4 평활. 조명·잡음으로 인접 칸으로 옮겨 가도 확률이 이어진다."""
    v = h.reshape(L_BINS, A_BINS, B_BINS)
    for ax in range(3):
        v = 0.5 * v + 0.25 * (np.roll(v, 1, ax) + np.roll(v, -1, ax))
    return v.ravel()


class ColorModel:
    """물체 vs 주변 Lab 히스토그램 → P(물체 | 색). 신뢰할 수 있는 프레임에서만 천천히 갱신한다."""

    NB = L_BINS * A_BINS * B_BINS

    def __init__(self) -> None:
        self.fg = np.zeros(self.NB)
        self.bg = np.zeros(self.NB)
        self.table = np.full(self.NB, UNSEEN_PROB, np.float32)

    def _hist(self, idx: np.ndarray, m: np.ndarray) -> np.ndarray | None:
        h = np.bincount(idx[m], minlength=self.NB).astype(float)
        if h.sum() < 20:
            return None
        h = _smooth3(h)
        return h / h.sum()

    def fit(self, idx: np.ndarray, fg_mask: np.ndarray | None, bg_mask: np.ndarray | None,
            rate_fg: float = 1.0, rate_bg: float = 1.0) -> None:
        if fg_mask is not None and rate_fg > 0:
            f = self._hist(idx, fg_mask)
            if f is not None:
                self.fg = (1 - rate_fg) * self.fg + rate_fg * f
        if bg_mask is not None and rate_bg > 0:
            b = self._hist(idx, bg_mask)
            if b is not None:
                self.bg = (1 - rate_bg) * self.bg + rate_bg * b
        a = UNSEEN_PROB / (1 - UNSEEN_PROB)
        self.table = ((self.fg + a * _EPS) / (self.fg + self.bg + (1 + a) * _EPS)).astype(np.float32)

    def prob(self, idx: np.ndarray) -> np.ndarray:
        return self.table[idx]

    def separability(self) -> float:
        """물체와 배경 분포가 얼마나 다른가 (0..1). 1 - Bhattacharyya 계수."""
        if self.fg.sum() <= 0 or self.bg.sum() <= 0:
            return 0.0
        f, b = self.fg / self.fg.sum(), self.bg / self.bg.sum()
        return float(np.clip(1.0 - np.sqrt(f * b).sum(), 0, 1))


def ring_mask(mask: np.ndarray, width: int) -> np.ndarray:
    k = max(3, width) | 1
    return cv2.dilate(mask.astype(np.uint8), np.ones((k, k), np.uint8)).astype(bool) & ~mask


# ---------------------------------------------------------------- 점 추적
LK = dict(winSize=(21, 21), maxLevel=4,
          criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))


def sample_points(gray: np.ndarray, mask: np.ndarray, exclude: np.ndarray | None, n_max: int = 150) -> np.ndarray:
    """마스크 안쪽(경계에서 물체 크기의 ~6% 떨어진 곳)의 코너 + 부족하면 격자 점."""
    m = mask.astype(np.uint8)
    size = np.sqrt(max(int(m.sum()), 1))
    k = max(3, int(size * 0.06)) | 1
    inner = cv2.erode(m, np.ones((k, k), np.uint8))
    if exclude is not None:
        inner[exclude] = 0
    if inner.sum() < 10:
        inner = m.copy()
        if exclude is not None:
            inner[exclude] = 0
    if inner.sum() < 4:
        return np.zeros((0, 2), np.float32)
    md = max(3, int(size / 18))
    pts = cv2.goodFeaturesToTrack(gray, n_max, 0.005, md, mask=inner, blockSize=5)
    pts = np.zeros((0, 2), np.float32) if pts is None else pts.reshape(-1, 2)
    if len(pts) < n_max // 3:  # 무늬가 적으면 격자로 채운다 (영역 전체 움직임을 잡도록)
        ys, xs = np.nonzero(inner)
        step = max(2, int(size / 10))
        sel = (xs % step == 0) & (ys % step == 0)
        grid = np.stack([xs[sel], ys[sel]], 1).astype(np.float32)
        if len(grid) > n_max:
            grid = grid[np.linspace(0, len(grid) - 1, n_max).astype(int)]
        pts = np.concatenate([pts, grid])[:n_max * 2]
    return pts.astype(np.float32)


@dataclass
class Motion:
    M: np.ndarray | None      # 2x3 유사변환 prev→cur (작업 해상도), 없으면 None
    inliers: int
    tracked: int
    sampled: int
    points: np.ndarray        # 살아남은 점 (cur), 다음 프레임에 계속 쓴다

    @property
    def ratio(self) -> float:
        return self.inliers / self.sampled if self.sampled else 0.0


def track_points(prev: np.ndarray, cur: np.ndarray, pts: np.ndarray, guess: np.ndarray | None,
                 size_px: float) -> Motion:
    """앞뒤 검사 LK + RANSAC 유사변환. guess: 예측 위치(등속 모델)로 초기화해 빠른 움직임에 대응."""
    n0 = len(pts)
    if n0 < 4:
        return Motion(None, 0, 0, n0, np.zeros((0, 2), np.float32))
    p0 = pts.reshape(-1, 1, 2)
    flags = 0
    p1 = None
    if guess is not None:
        p1 = guess.reshape(-1, 1, 2).astype(np.float32).copy()
        flags = cv2.OPTFLOW_USE_INITIAL_FLOW
    p1, st1, _ = cv2.calcOpticalFlowPyrLK(prev, cur, p0, p1, flags=flags, **LK)
    p0b, st2, _ = cv2.calcOpticalFlowPyrLK(cur, prev, p1, None, **LK)
    fb = np.linalg.norm((p0 - p0b).reshape(-1, 2), axis=1)
    fb_tol = max(0.8, 0.012 * size_px)
    ok = (st1.ravel() == 1) & (st2.ravel() == 1) & (fb < fb_tol)
    a, b = p0.reshape(-1, 2)[ok], p1.reshape(-1, 2)[ok]
    if len(a) < 4:
        return Motion(None, 0, len(a), n0, b.astype(np.float32))
    M, inl = cv2.estimateAffinePartial2D(a, b, method=cv2.RANSAC,
                                         ransacReprojThreshold=max(1.0, 0.015 * size_px),
                                         maxIters=500, confidence=0.99)
    if M is None:
        return Motion(None, 0, len(a), n0, b.astype(np.float32))
    inl = inl.ravel().astype(bool)
    return Motion(M, int(inl.sum()), len(a), n0, b[inl].astype(np.float32))


def similarity_params(M: np.ndarray) -> tuple[float, float]:
    """2x3 유사변환 → (scale, angle_deg). 화면 좌표(y 아래)에서 시계방향 +."""
    s = float(np.hypot(M[0, 0], M[1, 0]))
    ang = float(np.degrees(np.arctan2(M[1, 0], M[0, 0])))
    return s, ang


# ---------------------------------------------------------------- 마스크 정제
def refine_mask(prob: np.ndarray, prior: np.ndarray, size_px: float, exclude: np.ndarray | None,
                w_color: float) -> tuple[np.ndarray, float]:
    """prior(워프한 직전 마스크, bool) 와 색 확률을 합쳐 새 마스크.

    - prior 경계에서 물체 크기의 ~15% 안쪽은 색과 무관하게 물체 (내부 무늬가 배경색과 비슷해도 구멍이 안 나게)
    - 그 바깥 띠는 색 확률 + 거리 사전확률로 판정
    반환: (마스크, 색 일치도 = prior 안쪽 픽셀 중 색이 물체로 판정된 비율)
    """
    pm = prior.astype(np.uint8)
    band = max(2.0, 0.15 * size_px)
    din = cv2.distanceTransform(pm, cv2.DIST_L2, 3)
    dout = cv2.distanceTransform(1 - pm, cv2.DIST_L2, 3)
    signed = np.where(pm > 0, din, -dout)  # 안 +, 밖 -
    prior_logit = np.clip(signed / band, -1.5, 1.5) * 2.5
    p = np.clip(prob, 0.02, 0.98)
    color_logit = np.log(p / (1 - p))
    logit = prior_logit + w_color * color_logit
    # 깊은 안쪽은 물체로 강제하되, 물체에서 본 적 없는 색(손 등 가리는 것, 구멍으로 보이는 배경)은
    # 사전 확률과 무관하게 뺀다. 물체 자신의 무늬 색은 물체 히스토그램에 있으므로 여기서 빠지지 않는다.
    m = (logit > 0) | ((signed > band) & (prob > UNSEEN_PROB + 0.05))
    m &= prob > UNSEEN_PROB + 0.02
    if exclude is not None:
        m &= ~exclude
    # 사전 마스크와 겹치는 성분만 (주변 같은 색 물체로 번지지 않게)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    if n > 2:
        overlap = np.bincount(lab[pm > 0].ravel(), minlength=n)
        overlap[0] = 0
        keep = overlap > 0.1 * max(overlap.max(), 1)
        m = keep[lab]
    k = max(3, int(size_px * 0.04)) | 1
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((k, k), np.uint8)).astype(bool)
    inside = pm > 0
    if exclude is not None:
        inside &= ~exclude
    agree = float((prob[inside] > 0.5).mean()) if inside.any() else 0.0
    return m, agree


def warp_mask(mask: np.ndarray, M: np.ndarray) -> np.ndarray:
    h, w = mask.shape
    return cv2.warpAffine(mask.astype(np.uint8), M, (w, h), flags=cv2.INTER_NEAREST).astype(bool)


def similarity_about(cx: float, cy: float, s: float, ang_deg: float, tx: float, ty: float) -> np.ndarray:
    """(cx,cy) 기준으로 s 배·ang 회전 후 (tx,ty) 평행이동하는 2x3."""
    a = np.radians(ang_deg)
    c, si = s * np.cos(a), s * np.sin(a)
    R = np.array([[c, -si], [si, c]])
    t = np.array([cx + tx, cy + ty]) - R @ np.array([cx, cy])
    return np.hstack([R, t[:, None]])
