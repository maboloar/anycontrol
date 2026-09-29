"""펜 모드: 기다란 막대(펜)의 끝(펜촉)을 정밀하게 추적하고, 책상에 닿았는지 판정한다.

등록: 사용자가 펜촉과 반대쪽 끝, 두 점을 찍는다. 두 점을 잇는 선 위의 점들을 분할 모델에 주어
펜 마스크를 얻고, 일반 물체와 똑같이 추적한다 (가림·재검출은 ViTracker 가 담당).

펜촉 (매 프레임, 원본 해상도)
1. 추적 마스크에서 펜 축(PCA)과 대략적인 끝점을 구한다. 끝점 방향은 직전 펜촉과 가까운 쪽.
2. 원본 프레임에서 축을 따라 밝기 단면을 뽑아, 펜→배경으로 바뀌는 경계(기울기 최대)를 서브픽셀로 찾는다.
3. 칼만(등속) + One Euro 로 매끄럽게.

접촉 판정: 책상 면 위의 점은 카메라에서 멀수록 화면 위쪽에 보인다.
펜촉이 책상에 닿아 있으면 '펜 굵기(카메라 거리의 역수에 비례)'와 '펜촉 높이(y)'가 한 직선 위에 놓인다:
    y_surface ≈ y_horizon + K · w      (카메라 높이 H, 펜 지름 D 일 때 K = H / D)
펜을 들면 펜촉이 이 직선보다 위(작은 y)로 떨어진다. 직선은 쓰는 동안 관측된 (w, y) 의 '아래쪽 경계'로
스스로 보정한다 (펜촉은 책상 아래로 내려갈 수 없으므로). 직선 거리 + 펜촉 세로 속도 + 히스테리시스로 판정.
그리기 좌표: 닿아 있을 때 펜촉은 책상 면 위에 있으므로 원근을 풀어 책상 좌표 (X, Z) 를 얻는다.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from .tracking.api import Pose, TrackOutput
from .tracking.desk import DeskCalibration
from .tracking.smooth import OneEuro
from .pen_contact import OverheadContact


def line_prompts(tip: tuple[float, float], tail: tuple[float, float], n: int = 5) -> list[tuple[float, float, int]]:
    """두 점 사이 선 위의 양성 점들 (끝점은 경계라 조금 안쪽부터)."""
    return [(tip[0] + (tail[0] - tip[0]) * f, tip[1] + (tail[1] - tip[1]) * f, 1)
            for f in np.linspace(0.08, 0.92, n)]


def line_box(tip, tail, frame_size: tuple[int, int], pad_frac: float = 0.12) -> tuple[float, float, float, float]:
    L = math.hypot(tail[0] - tip[0], tail[1] - tip[1])
    pad = max(8.0, pad_frac * L)
    w, h = frame_size
    return (max(0.0, min(tip[0], tail[0]) - pad), max(0.0, min(tip[1], tail[1]) - pad),
            min(float(w), max(tip[0], tail[0]) + pad), min(float(h), max(tip[1], tail[1]) + pad))


def pen_mask_from_line(mask_candidates: list[np.ndarray], tip, tail) -> np.ndarray | None:
    """분할 후보 중 '선을 따라 길고 가늘게 덮는' 것을 고른다 (손까지 잡힌 후보를 배제)."""
    L = math.hypot(tail[0] - tip[0], tail[1] - tip[1])
    best, best_s = None, -1.0
    pts = np.array([[p[0], p[1]] for p in line_prompts(tip, tail, 15)])
    for m in mask_candidates:
        h, w = m.shape
        xi = np.clip(pts[:, 0].astype(int), 0, w - 1)
        yi = np.clip(pts[:, 1].astype(int), 0, h - 1)
        cover = float(m[yi, xi].mean())
        area = float(m.sum())
        thin = min(1.0, (0.25 * L * L) / max(area, 1.0))  # 펜은 길이²의 1/4 보다 훨씬 작다
        s = cover * thin
        if s > best_s:
            best, best_s = m, s
    return best


# ---------------------------------------------------------------- 펜촉 기하
@dataclass
class TipMeasure:
    tip: np.ndarray            # (2,) 원본 px
    axis: np.ndarray           # (2,) 펜촉 방향 단위벡터 (몸통 → 펜촉)
    width: float               # 펜촉 근처 펜 굵기 (px)
    length: float              # 보이는 펜 길이 (px)
    sharpness: float           # 경계 기울기 크기 (신뢰도)


def measure_tip(mask: np.ndarray, gray: np.ndarray | None, prev_tip: np.ndarray | None,
                prev_axis: np.ndarray | None, M: np.ndarray | None = None, edge_span: float = 0.4
                ) -> TipMeasure | None:
    """mask 에서 펜촉을 구한다. M(2x3 유사변환)이 있으면 마스크 기하를 M 으로 옮긴 뒤(늦게 도착한 정밀 마스크를
    지금 프레임으로) 경계 보정을 한다. gray 가 None 이면 경계 보정 없이 마스크 기하만."""
    g = tip_geometry(mask, prev_tip, prev_axis)
    if g is None:
        return None
    tip0, u, width, length = g
    if M is not None:
        A = M[:, :2]
        s = float(math.hypot(A[0, 0], A[1, 0]))
        tip0 = A @ tip0 + M[:, 2]
        u = A @ u / max(s, 1e-9)
        width, length = width * s, length * s
    v = np.array([-u[1], u[0]])
    if gray is None or edge_span <= 0:
        return TipMeasure(tip0, u, width, length, 0.0)
    tip, sharp = _refine_edge(gray, tip0, u, v, width if math.isfinite(width) else 6.0, edge_span)
    return TipMeasure(tip, u, width, length, sharp)


def tip_geometry(mask: np.ndarray, prev_tip: np.ndarray | None, prev_axis: np.ndarray | None
                 ) -> tuple[np.ndarray, np.ndarray, float, float] | None:
    """마스크의 펜촉 (tip0, 몸통→펜촉 단위벡터 u, 펜촉 근처 굵기, 보이는 길이). 길쭉하지 않으면 None."""
    ys, xs = np.nonzero(mask)
    if xs.size < 20:
        return None
    P = np.stack([xs, ys], 1).astype(np.float64)
    c = P.mean(0)
    cov = np.cov((P - c).T)
    evals, evecs = np.linalg.eigh(cov)
    u = evecs[:, 1]
    if evals[0] > 0 and evals[1] / max(evals[0], 1e-9) < 4.0:
        return None  # 길쭉하지 않다: 펜이 아니거나 손에 대부분 가림
    proj = (P - c) @ u
    # 펜촉 쪽 선택: 직전 펜촉에 가까운 끝, 없으면 직전 축 방향, 없으면 아래쪽(y 큰 쪽)
    lo, hi = np.percentile(proj, 0.5), np.percentile(proj, 99.5)
    end_hi, end_lo = c + hi * u, c + lo * u
    if prev_tip is not None:
        sign = 1.0 if np.linalg.norm(end_hi - prev_tip) <= np.linalg.norm(end_lo - prev_tip) else -1.0
    elif prev_axis is not None:
        sign = 1.0 if float(u @ prev_axis) >= 0 else -1.0
    else:
        sign = 1.0 if end_hi[1] >= end_lo[1] else -1.0
    u = u * sign
    proj = proj * sign
    far = float(np.percentile(proj, 99.5))
    length = far - float(np.percentile(proj, 0.5))
    # 끝 근처 픽셀들의 가로 중앙 = 축 위치 (마스크 경계 잡음에 강함)
    v = np.array([-u[1], u[0]])
    near = proj > far - 0.06 * length
    lat = float(np.median((P[near] - c) @ v)) if near.any() else 0.0
    base = c + lat * v
    tip0 = base + far * u
    # 굵기: 펜촉에서 길이의 8~25% 구간 단면 폭 (손가락에 덜 가리는 곳)
    band = (proj > far - 0.25 * length) & (proj < far - 0.08 * length)
    width = float(np.percentile(np.abs((P[band] - c) @ v - lat), 90) * 2) if band.sum() > 10 else float("nan")
    return tip0, u, width, length


def _refine_edge(gray: np.ndarray, tip0: np.ndarray, u: np.ndarray, v: np.ndarray, width: float,
                 span_k: float = 0.4) -> tuple[np.ndarray, float]:
    """마스크 끝 근처에서만 밝기 경계를 찾는다. 범위를 넓게(굵기의 1.5배) 잡으면 그림자·책상 모서리 같은
    다른 경계로 옮겨 갈 수 있다."""
    span = max(4.0, span_k * width)
    ts = np.arange(-span, span + 0.5, 0.5)
    half = max(1.0, 0.3 * width)
    offs = np.linspace(-half, half, 5)
    pts = tip0[None, None, :] + ts[:, None, None] * u[None, None, :] + offs[None, :, None] * v[None, None, :]
    mx = pts[..., 0].astype(np.float32)
    my = pts[..., 1].astype(np.float32)
    prof = cv2.remap(gray.astype(np.float32), mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).mean(1)
    prof = cv2.GaussianBlur(prof.reshape(1, -1), (1, 5), 0).ravel()
    g = np.abs(np.gradient(prof))
    # 마스크 끝 근처(±span) 에서 가장 뚜렷한 경계. 너무 멀리 옮기지 않도록 거리 가중.
    wgt = np.exp(-0.5 * (ts / (0.8 * span)) ** 2)
    i = int(np.argmax(g * wgt))
    if 0 < i < len(g) - 1:  # 포물선 보간
        a, b, cc = g[i - 1], g[i], g[i + 1]
        den = a - 2 * b + cc
        di = 0.5 * (a - cc) / den if abs(den) > 1e-9 else 0.0
    else:
        di = 0.0
    t = ts[i] + np.clip(di, -1, 1) * 0.5
    return tip0 + t * u, float(g[i])


# ---------------------------------------------------------------- 그림자 접촉
def shadow_features(gray: np.ndarray, tip: np.ndarray, axis: np.ndarray, width: float,
                    pen_mask: np.ndarray | None, radius_w: float = 3.0, dark_k: float = 0.62,
                    cap_w: float = 0.35, bgr: np.ndarray | None = None, hue_deg: float = 30.0,
                    desk_lab: tuple[float, float, float] | None = None) -> dict | None:
    """펜촉 주변이 '책상 면(또는 그 위 그림자)' 인지 본다.

    책상에 닿은 펜촉은 화면에서 반드시 책상 앞에 보인다. 들어 올리면 펜촉이 책상보다 위(뒤 배경 앞)로 올라간다.
    밝기만으로는 조명에 흔들리므로 **같은 프레임의 책상 색과 비교**한다 (desk_lab: 아래쪽 넓은 면의 Lab 중앙값).
      - 책상 면 = 책상과 색(Lab 색상)이 같고 밝기가 책상의 dark_k 배 이상 (그림자는 색이 같고 어둡다 → 포함)
      - 그림자 = 책상 색이면서 책상보다 뚜렷하게 어두움
    펜촉 끝의 검은 구멍(펜 일부)은 펜촉 앞 cap_w 굵기 · 옆 0.5 굵기 영역을 빼서 제외한다.
    반환: desk_near(펜촉 1.2 굵기 안이 책상 면인 비율), gap(펜촉→그림자, 굵기 배), adjacent(1 굵기 안 그림자 비율),
    desk(책상 밝기). desk_lab 이 없으면 프레임 아래 1/3 에서 구한다."""
    if not math.isfinite(width) or width < 2:
        return None
    h, w = gray.shape
    R = int(radius_w * width) + 2
    x0, y0 = int(tip[0]) - R, int(tip[1]) - R
    x1, y1 = x0 + 2 * R + 1, y0 + 2 * R + 1
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        return None
    g = cv2.GaussianBlur(gray[y0:y1, x0:x1], (5, 5), 0).astype(np.float32)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    dx, dy = xx - float(tip[0]), yy - float(tip[1])
    dist = np.hypot(dx, dy) / width
    u = axis / max(float(np.linalg.norm(axis)), 1e-9)
    along = (dx * u[0] + dy * u[1]) / width
    lat = np.abs(-dx * u[1] + dy * u[0]) / width
    disk = dist <= radius_w
    pen = np.zeros_like(disk)
    if pen_mask is not None:
        pen = pen_mask[y0:y1, x0:x1].astype(bool)
        pen = cv2.dilate(pen.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    cap = (along >= -0.05) & (along <= cap_w) & (lat <= 0.5)
    free = disk & ~pen & ~cap
    if free.sum() < 20:
        return None
    if desk_lab is None:
        desk_lab = desk_reference(bgr, gray, pen_mask)
    L0, a0, b0 = desk_lab
    if bgr is not None:
        lab = cv2.cvtColor(bgr[y0:y1, x0:x1], cv2.COLOR_BGR2LAB).astype(np.float32)
        Lp, ap, bp = lab[..., 0], lab[..., 1] - 128, lab[..., 2] - 128
    else:  # 색 정보가 없으면 밝기만 (그림자·책상 구분이 약해진다)
        Lp, ap, bp = g * (100.0 / 255.0), np.zeros_like(g), np.zeros_like(g)
    chroma0 = math.hypot(a0, b0)
    chroma = np.hypot(ap, bp)
    if chroma0 >= 4:  # 책상에 색이 있으면 색상 방향으로 가른다 (그림자는 색상 유지, 다른 물체는 다른 색)
        cosang = (ap * a0 + bp * b0) / np.maximum(chroma * chroma0, 1e-6)
        same_color = (cosang >= math.cos(math.radians(hue_deg))) | (chroma < 0.35 * chroma0)
    else:
        same_color = np.abs(ap - a0) + np.abs(bp - b0) < 18
    is_desk = free & same_color & (Lp >= dark_k * L0) & (Lp <= 1.35 * L0)
    dark = free & same_color & (Lp < 0.82 * L0) & (Lp >= dark_k * L0)
    ring1 = free & (dist <= 1.0)
    near = free & (dist <= 1.2)
    gap = float(dist[dark].min()) if dark.any() else radius_w
    full = np.zeros((h, w), bool)
    full[y0:y1, x0:x1] = dark
    return {"gap": gap, "adjacent": float(dark[ring1].mean()) if ring1.any() else 0.0,
            "desk_near": float(is_desk[near].mean()) if near.any() else 0.0,
            "desk": float(np.percentile(g[free], 80)), "_dark": full}


def desk_reference(bgr: np.ndarray | None, gray: np.ndarray, pen_mask: np.ndarray | None
                   ) -> tuple[float, float, float]:
    """책상 색 기준 (Lab). 책상은 화면 아래쪽의 넓고 밝은 면이라고 본다: 아래 1/3 에서 펜을 뺀 밝은 쪽(70%)."""
    h, w = gray.shape
    band = slice(int(h * 2 / 3), h)
    m = np.ones((h - band.start, w), bool)
    if pen_mask is not None:
        m &= ~pen_mask[band].astype(bool)
    gl = gray[band]
    thr = np.percentile(gl[m], 70) if m.any() else 128.0
    sel = m & (gl >= thr)
    if sel.sum() < 50:
        return (float(np.median(gl)) * 100 / 255, 0.0, 0.0)
    if bgr is None:
        return (float(np.median(gl[sel])) * 100 / 255, 0.0, 0.0)
    lab = cv2.cvtColor(bgr[band], cv2.COLOR_BGR2LAB).astype(np.float32)
    return (float(np.median(lab[..., 0][sel])), float(np.median(lab[..., 1][sel]) - 128),
            float(np.median(lab[..., 2][sel]) - 128))


# ---------------------------------------------------------------- 책상 면 (자기 보정)
def fit_upper_expectile(w: np.ndarray, y: np.ndarray, tau: float = 0.8, iters: int = 25) -> tuple[float, float]:
    """y ≈ a + b·w 의 위쪽 expectile (비대칭 최소제곱). 선 아래쪽(큰 y) 잔차에 tau, 위쪽에 1-tau 가중.

    펜촉은 책상 아래로 내려갈 수 없으므로 '닿은 점들'이 (w, y) 분포의 아래 경계(큰 y)를 이룬다.
    든 상태 점들은 선 위에 흩어지는데, 가중을 비대칭으로 주면 그 영향이 작다.
    """
    A = np.c_[np.ones_like(w), w]
    beta = np.linalg.lstsq(A, y, rcond=None)[0]
    for _ in range(iters):
        r = y - A @ beta
        sw = np.sqrt(np.where(r > 0, tau, 1 - tau))
        beta = np.linalg.lstsq(A * sw[:, None], y * sw, rcond=None)[0]
    return float(beta[0]), float(beta[1])


@dataclass
class SurfaceModel:
    """y_surface = y_h + K · w. 관측 (w, y) 의 아래 경계(큰 y)를 expectile 회귀로 맞춘다 (자기 보정)."""

    samples: deque = field(default_factory=lambda: deque(maxlen=1800))
    y_h: float | None = None
    K: float | None = None
    fixed: bool = False        # 사용자가 직접 보정했으면 자동 갱신 안 함
    min_samples: int = 90
    tau: float = 0.8

    def add(self, w: float, y: float) -> None:
        if math.isfinite(w) and w > 1.0:
            self.samples.append((w, y))

    def fit(self) -> bool:
        """굵기(=카메라 거리)가 충분히 다양하게 관측되어야 직선이 정해진다."""
        if self.fixed or len(self.samples) < self.min_samples:
            return False
        a = np.array(self.samples)
        w, y = a[:, 0], a[:, 1]
        if np.ptp(w) < 0.25 * float(np.median(w)):
            return False
        y_h, K = fit_upper_expectile(w, y, self.tau)
        if K > 0:  # 가까울수록(굵을수록) 화면 아래 — 물리적으로 맞는 경우만
            self.K, self.y_h = K, y_h
            return True
        return False

    def calibrate(self, samples: list[tuple[float, float]]) -> bool:
        """사용자가 '지금 닿아 있음' 으로 찍은 (w, y) 들로 직접 맞춘다 (모두 닿은 점이므로 보통 회귀)."""
        if len(samples) < 2:
            return False
        a = np.array(samples)
        if np.ptp(a[:, 0]) < 1e-3:  # 거리가 한 가지면 기울기를 알 수 없다: 기존 기울기 유지, 절편만
            if self.K is None:
                return False
            self.y_h = float(np.mean(a[:, 1] - self.K * a[:, 0]))
        else:
            K, y_h = np.polyfit(a[:, 0], a[:, 1], 1)
            if K <= 0:
                return False
            self.K, self.y_h = float(K), float(y_h)
        self.fixed = True
        return True

    def height(self, w: float, y: float) -> float | None:
        """책상 면 위 펜촉 높이 (px, + 가 위). 모델이 없으면 None."""
        if self.K is None or self.y_h is None or not math.isfinite(w):
            return None
        return (self.y_h + self.K * w) - y


def table_xy(tip: np.ndarray, cx: float, f: float, horizon_y: float) -> tuple[float, float] | None:
    """펜촉(책상 위에 있다고 가정) → 책상 좌표 (카메라 높이 = 1 단위).
        Z(카메라로부터 앞쪽 거리) = f / (y - y_horizon),   X(좌우) = (x - cx) / (y - y_horizon)
    책상 면을 옆에서 보면 멀수록 납작하게 눌리는데, 이 변환이 원근을 되돌린다.
    horizon_y: 책상 면의 소실선. 카메라가 수평이면 화면 가운데 높이.
    면 모델 절편은 굵기 측정 편향 때문에 소실선으로 쓰지 않는다."""
    d = float(tip[1]) - horizon_y
    if d <= 1.0:
        return None
    return float((tip[0] - cx) / d), float(f / d)


# ---------------------------------------------------------------- 펜 상태
@dataclass
class PenConfig:
    # 접촉 판정은 펜 굵기 단위 (카메라 거리와 무관): 면 위 높이 < on·w 이면 닿음, > off·w 면 뗌
    touch_on: float = 0.6
    touch_off: float = 1.0
    refit_every: int = 15           # 프레임마다 책상 면 다시 맞추기
    hfov_deg: float = 70.0          # 초점거리 추정용 가로 화각 (iPhone 광각·웹캠 대부분 65~78°)
    horizon: float = 0.5            # 책상 소실선 높이 (프레임 높이 비율). 카메라를 아래로 숙이면 작아진다
    min_stroke_pts: int = 3
    # 펜촉 One Euro: 속도 단위는 펜 굵기/초. 그리기는 지연이 거슬리므로 빠를 때 차단 주파수가 크게 오른다
    # 속도에 따라 필터 반응을 높여 빠른 펜 이동을 따라간다.
    tip_min_cutoff: float = 2.0
    tip_beta: float = 1.0
    refined_max_age: float = 0.35   # 이보다 오래된 정밀 마스크는 쓰지 않는다 (Tier 1 이 멈췄을 때)
    edge_span: float = 0.4          # 밝기 경계 탐색 범위 (펜 굵기 배). 0 이면 마스크 끝 그대로
    desk_contact_margin: float = .18
    shadow_assist: bool = False
    desk_near_on: float = .70


class PenTracker:
    def __init__(self, tip0: tuple[float, float], tail0: tuple[float, float], cfg: PenConfig | None = None) -> None:
        """tip0, tail0: 등록 때 사용자가 찍은 펜촉·반대쪽 끝 (원본 px)."""
        self.cfg = cfg or PenConfig()
        d = np.array([tip0[0] - tail0[0], tip0[1] - tail0[1]], float)
        self.dir0 = d / max(np.linalg.norm(d), 1e-6)   # 등록 시 몸통→펜촉 방향
        self.tip: np.ndarray | None = np.array(tip0, float)
        self.axis: np.ndarray | None = self.dir0.copy()
        self.touch_samples: list[tuple[float, float]] = []
        self.width = float("nan")
        self.surface = SurfaceModel()
        self.contact = False
        c = self.cfg
        self.fx, self.fy = OneEuro(c.tip_min_cutoff, c.tip_beta), OneEuro(c.tip_min_cutoff, c.tip_beta)
        self.strokes: list[list[tuple[float, float]]] = []
        self.cur: list[tuple[float, float]] | None = None
        self.events: list[dict[str, Any]] = []
        self.height: float | None = None
        self.t_prev: float | None = None
        self.y_hist: deque = deque(maxlen=5)
        self.frame_w = 1
        self.frame_h = 1
        self.mirror = False
        self.desk_near_s = None
        self.shadow_veto = False
        self.manual_contact: bool | None = None  # 디버그/수동 오버라이드
        self.manual_until: float | None = None
        self.overhead = False
        self.overhead_contact = OverheadContact()
        self._desk_press_frames = 0
        self.debug: dict[str, Any] = {}
        self._fit_every = 0
        # 처음 신뢰할 수 있는 전체 펜의 끝과 포즈를 강체 기준으로 보관한다.
        # 손가락이 펜촉을 가린 프레임의 잘린 마스크가 새로운 펜촉으로 바뀌는 것을 막는다.
        self._anchor_tip: np.ndarray | None = None
        self._anchor_pose: Pose | None = None
        self._anchor_axis: np.ndarray | None = None
        self._length0: float | None = None
        self.desk: DeskCalibration | None = None
        self.uncertain = False
        self.suspended = False  # 안내 보정 중 기하만 관측하고 획·접촉 모델은 변경하지 않는다.
        self._uncertain_since: float | None = None


    def redefine(self, tip0: tuple[float, float], tail0: tuple[float, float]) -> None:
        """다시 선택: 펜촉·반대쪽 끝을 새로 받는다. 그린 것·접촉 보정·설정은 그대로 둔다."""
        self.lift()
        d = np.array([tip0[0] - tail0[0], tip0[1] - tail0[1]], float)
        self.dir0 = d / max(np.linalg.norm(d), 1e-6)
        self.tip = np.array(tip0, float)
        self.axis = self.dir0.copy()
        self.width = float("nan")
        c = self.cfg
        self.fx, self.fy = OneEuro(c.tip_min_cutoff, c.tip_beta), OneEuro(c.tip_min_cutoff, c.tip_beta)
        self.y_hist.clear()
        self.t_prev = None
        self.desk_near_s = None
    def _rigid_tip(self, pose: Pose | None) -> np.ndarray | None:
        if pose is None or self._anchor_tip is None or self._anchor_pose is None:
            return None
        anchor = self._anchor_pose
        a = math.radians(pose.angle - anchor.angle)
        c, s = math.cos(a), math.sin(a)
        relative = self._anchor_tip - np.array([anchor.cx, anchor.cy])
        ratio = pose.scale / max(anchor.scale, 1e-5)
        if self._anchor_axis is not None:
            # 3D 막대를 기울이면 2D 투영 길이가 바뀐다. 면적 배율만으로 길이를 고정하면 안 된다.
            aspect = math.sqrt(max(.1, pose.aspect) / max(.1, anchor.aspect))
            along = float(relative @ self._anchor_axis) * self._anchor_axis
            relative = along * aspect + (relative - along) / aspect
        return np.array([pose.cx, pose.cy]) + ratio * np.array(
            [c * relative[0] - s * relative[1], s * relative[0] + c * relative[1]])

    def _pause_measurement(self, prediction: np.ndarray | None, t: float) -> None:
        self.uncertain = True
        self.desk_near_s = None
        self.tip = prediction
        if self._uncertain_since is None:
            self._uncertain_since = t
        # 짧은 가림에서는 점을 추가하지 않고 기존 획만 유지한다. 입력은 pipeline에서 차단한다.
        if t - self._uncertain_since > .10:
            self.lift()

    def lift(self) -> None:
        if self.contact:
            self.contact = False
            self._end_stroke()

    def update(self, frame_bgr: np.ndarray, out: TrackOutput, t: float,
               desk: DeskCalibration | None = None, overhead: bool = False) -> None:
        self.desk = desk
        self.overhead = overhead
        if self.manual_until is not None and t >= self.manual_until:
            self.manual_contact, self.manual_until = False, None
        self.frame_h, self.frame_w = frame_bgr.shape[:2]
        if not out.state.visible or out.mask is None:
            self.desk_near_s = None
            self.lift()
            self.tip = None
            self.uncertain = True
            self._uncertain_since = None
            return
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        # 펜촉 쪽 판단: 등록 방향을 추적 포즈 회전만큼 돌린 방향 (마스크 끝이 손에 잘려도 뒤집히지 않음)
        expected = self.dir0
        if out.pose is not None:
            a = math.radians(out.pose.angle)
            expected = np.array([math.cos(a) * self.dir0[0] - math.sin(a) * self.dir0[1],
                                 math.sin(a) * self.dir0[0] + math.cos(a) * self.dir0[1]])
        # 정밀 마스크(Tier 1, 늦게 도착)를 지금으로 옮겨 쓴다. Tier 0 마스크는 색·형태 추정이라 손가락이 붙거나
        # 회전을 늦게 따라가면 펜촉 위치가 어긋나므로 방향은 즉시 갱신한다.
        ref = out.refined
        src = "t0"
        m = None
        if ref is not None and ref.age <= self.cfg.refined_max_age:
            m = measure_tip(ref.mask, gray, None, expected, ref.M, self.cfg.edge_span)
            src = "t1"
        if m is None:
            m = measure_tip(out.mask, gray, None, expected, None, self.cfg.edge_span)
            src = "t0"
        if m is None:
            self._pause_measurement(self._rigid_tip(out.pose), t)
            self.debug = {"src": "rigid", "uncertain": True}
            return
        prediction = self._rigid_tip(out.pose)
        if self._length0 is not None and out.pose is not None:
            expected_length = self._length0 * out.pose.scale * math.sqrt(max(.1, out.pose.aspect))
            shortened = m.length < 0.6 * expected_length
            displaced = prediction is not None and np.linalg.norm(m.tip - prediction) > 0.28 * expected_length
            # 신선한 Tier 1 마스크는 면외 회전까지 모델이 본 관측이다. 강체 예측으로 덮어쓰지 않는다.
            # 초기/오래된 마스크에서 전파한 Tier 0 결과에만 보수적인 길이 제약을 적용한다.
            if src == "t0" and shortened and displaced:
                self._pause_measurement(prediction, t)
                self.axis = expected
                self.height = None
                self.debug = {"src": "rigid", "uncertain": True,
                              "observed_length": round(m.length, 1), "expected_length": round(expected_length, 1)}
                return
        if self._anchor_tip is None and out.pose is not None:
            self._anchor_tip = m.tip.copy()
            self._anchor_axis = m.axis.copy()
            self._anchor_pose = Pose(out.pose.cx, out.pose.cy, out.pose.scale, out.pose.angle, out.pose.aspect)
            self._length0 = m.length / max(out.pose.scale * math.sqrt(max(.1, out.pose.aspect)), 1e-5)
        self.uncertain = False
        self._uncertain_since = None
        unit = max(m.width if math.isfinite(m.width) else 8.0, 4.0)
        sx = self.fx(float(m.tip[0]), t, unit)
        sy = self.fy(float(m.tip[1]), t, unit)
        self.tip = np.array([sx, sy])
        self.axis = m.axis
        w = m.width
        if math.isfinite(w):
            self.width = w if not math.isfinite(self.width) else 0.8 * self.width + 0.2 * w
        if self.overhead:
            self.overhead_contact.observe(self.tip / [self.frame_w, self.frame_h], m.width, m.length, m.sharpness)
        elif not self.suspended:
            self.surface.add(self.width, float(m.tip[1]))
            self._fit_every += 1
            if self._fit_every % self.cfg.refit_every == 0:
                self.surface.fit()
        self.y_hist.append(float(m.tip[1]))
        self.desk_near_s = None if not self.cfg.shadow_assist or self.overhead else self.desk_near_s
        if self.cfg.shadow_assist and not self.overhead:
            pen_now = out.mask
            if src == "t1":
                pen_now = cv2.warpAffine(ref.mask.astype(np.uint8), ref.M, gray.shape[::-1], flags=cv2.INTER_NEAREST) > 0
            shadow = shadow_features(gray, m.tip, m.axis, self.width, pen_now, bgr=frame_bgr)
            # 유효하지 않은 관측의 이전 값을 재사용하지 않는다.
            if shadow is None:
                self.desk_near_s = None
            else:
                d = shadow["desk_near"]
                self.desk_near_s = d if self.desk_near_s is None else .6 * self.desk_near_s + .4 * d
        self._decide(t)
        self.debug = {"width": round(self.width, 2) if math.isfinite(self.width) else None,
                      "height": None if self.height is None else round(self.height, 2),
                      "sharp": round(m.sharpness, 1), "len": round(m.length, 1),
                      "raw_x": round(float(m.tip[0]), 2), "raw_y": round(float(m.tip[1]), 2), "src": src}

    def _decide(self, t: float) -> None:
        c = self.cfg
        h = None if self.overhead else self.surface.height(self.width, float(self.y_hist[-1]))
        self.height = h
        if self.suspended:
            self.lift()
            return
        w = max(self.width, 2.0) if math.isfinite(self.width) else 10.0
        was = self.contact
        if self.manual_contact is not None:
            now = self.manual_contact
        elif self.overhead:
            score = self.overhead_contact.classify()
            permitted = score is not None and score > (-.05 if was else c.desk_contact_margin)
            self._desk_press_frames = self._desk_press_frames + 1 if permitted else 0
            now = permitted and (was or self._desk_press_frames >= 2)
        elif h is None:
            now = False
        else:
            now = h < (c.touch_off if was else c.touch_on) * w
        self.shadow_veto = bool(now and not was and not self.overhead and c.shadow_assist
                                and self.manual_contact is None and self.desk_near_s is not None
                                and self.desk_near_s < c.desk_near_on)
        if self.shadow_veto:
            now = False
        if now and not was:
            self.cur = []
            self.events.append({"type": "down"})
        if now:
            xy = self.drawing_point()
            if xy is not None and self.cur is not None:
                self.cur.append((round(xy[0], 5), round(xy[1], 6)))
        if was and not now:
            self._end_stroke()
        self.contact = now

    def _end_stroke(self) -> None:
        stroke = None
        if self.cur is not None and len(self.cur) >= self.cfg.min_stroke_pts:
            stroke = self.cur
            self.strokes.append(stroke)
            del self.strokes[:-50]
        self.cur = None
        self.events.append({"type": "up", "stroke": stroke})

    def clear(self) -> None:
        self.strokes.clear()
        self.cur = [] if self.contact else None
        self.events.append({"type": "clear"})

    def mark_touching(self) -> bool:
        """사용자가 '지금 책상에 닿아 있음' 을 알려 준다. 두 곳 이상(가까운 곳·먼 곳) 찍으면 직선이 확정된다."""
        if self.tip is None or not math.isfinite(self.width):
            return False
        if self.overhead:
            return not self.uncertain and self.overhead_contact.mark(True)
        self.touch_samples.append((self.width, float(self.y_hist[-1])))
        return self.surface.calibrate(self.touch_samples)

    def mark_lifted(self) -> bool:
        return self.overhead and self.tip is not None and not self.uncertain and self.overhead_contact.mark(False)

    def manual_press(self, pressed: bool, t: float) -> None:
        self.manual_contact = pressed
        self.manual_until = t + 1.2 if pressed else None
        if not pressed:
            self.lift()

    def reset_calibration(self) -> None:
        self.touch_samples.clear()
        self.surface = SurfaceModel()
        self.overhead_contact = OverheadContact()
        self.manual_contact = self.manual_until = None
        self._desk_press_frames = 0
        self.lift()

    def drawing_point(self) -> tuple[float, float] | None:
        xy = self._drawing_point()
        return (-xy[0], xy[1]) if xy is not None and self.mirror else xy

    def _drawing_point(self) -> tuple[float, float] | None:
        """접촉 여부와 무관하게 획과 동일한 좌표계의 펜촉 위치를 제공한다."""
        if self.tip is None or self.uncertain:
            return None
        if self.desk is not None:
            p = self.desk.to_desk(self.tip.reshape(1, 2))[0]
            return (float(p[0]), float(p[1])) if np.isfinite(p).all() else None
        if self.overhead:
            return float(self.tip[0]) / self.frame_w, -float(self.tip[1]) / self.frame_w
        f = .5 * self.frame_w / math.tan(math.radians(self.cfg.hfov_deg / 2))
        return table_xy(self.tip, self.frame_w / 2, f, self.cfg.horizon * self.frame_h)

    def state(self, consume: bool = True) -> dict[str, Any]:
        ev = list(self.events)
        if consume:
            self.events = []
        return {
            "draw_point": self.drawing_point(),
            "tip": None if self.tip is None else [round(float(self.tip[0]), 2), round(float(self.tip[1]), 2)],
            "axis": None if self.axis is None else [round(float(self.axis[0]), 4), round(float(self.axis[1]), 4)],
            "contact": self.contact,
            "uncertain": self.uncertain,
            "shadow_assist": self.cfg.shadow_assist,
            "shadow_veto": self.shadow_veto,
            "desk_near": self.desk_near_s,
            "height": None if self.height is None else round(self.height, 2),
            "desk_view": self.overhead,
            "contact_mode": 'manual' if self.manual_contact is not None else 'auto',
            "contact_score": self.overhead_contact.score,
            "touch_samples": len(self.overhead_contact.touch),
            "lift_samples": len(self.overhead_contact.lift),
            "calibrated": self.overhead_contact.ready if self.overhead else self.surface.K is not None,
            "manual_calibration": self.overhead_contact.ready if self.overhead else self.surface.fixed,
            "samples": len(self.overhead_contact.touch) + len(self.overhead_contact.lift) if self.overhead else len(self.surface.samples),
            "surface": None if self.surface.K is None else {"y_h": round(self.surface.y_h, 2), "K": round(self.surface.K, 3)},
            "horizon": self.cfg.horizon,
            "settings": {"touch_on": self.cfg.touch_on, "touch_off": self.cfg.touch_off,
                         "tip_min_cutoff": self.cfg.tip_min_cutoff, "tip_beta": self.cfg.tip_beta,
                         "edge_span": self.cfg.edge_span, "refined_max_age": self.cfg.refined_max_age,
                         "desk_contact_margin": self.cfg.desk_contact_margin},
            "current": self.cur,
            "stroke_count": len(self.strokes),
            "events": ev,
            "debug": self.debug,
        }
