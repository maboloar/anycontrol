"""수평 카메라 펜 접촉: 바닥 기하(자기 보정) + 그림자 링 + 히스테리시스 상태기계.

independent_pen_algorithm_test/METHOD.md 의 방법을 AnyControl 에 맞게 옮겼다.

F 바닥 기하. 핀홀 카메라(책상 위 높이 Hc), 펜 지름 D, 깊이 Z.
    책상에 닿은 펜촉:  y_tip − y_horizon = f·Hc/Z,  펜 몸통 굵기 w = f·D/Z
    → 접촉이면 d = k·w − c  (d = y_tip − 기준선 y, k = Hc/D)
    → hover = k − (d + c)/w   [펜 지름 단위 높이. 0 = 닿음, + = 떠 있음, ≪0 = 책상 아래(마스크 오류)]
  (k, c) 는 라벨 없이 (w, d) 흐름에서 RANSAC + IRLS(Tukey) 로 맞춘다: 닿은 프레임은 한 직선 위에,
  떠 있는 프레임은 한쪽에만 흩어지고, 반대쪽(책상 아래)은 물리적으로 불가능하다.
  잔차의 MAD 로 σ(접촉 hover 잡음)를 스스로 추정해 이탈·불가능 문턱을 σ 에 비례시킨다.
G 게이트. 펜촉이 책상 먼 모서리보다 위에 찍히면 책상 위에 있을 수 없다 (모서리 추적 시에만).
S 그림자. 직사광일 때만(책상 밝기 이봉) 펜 끝 링이 밝으면 'gap'(떠 있음), 주변은 밝은데 끝에만
  그림자가 붙으면 'attached'(접촉 증거).
T 상태기계. 진입·이탈 디바운스, 접촉 baseline 대비 상승으로 이탈, 분할 탈락 동안 접촉 유지(객체 영속성).

원본과 다른 점
- 프레임 수 파라미터는 초 단위(fps 무관), 픽셀 파라미터는 프레임 크기 비율.
- 책상 판정은 HSV 상수 대신 같은 프레임의 책상 Lab 색(아래쪽 밝은 면)과 비교한다 (다른 책상에도 동작).
- 탈락 중 접촉을 끊었다 다시 잇는 대신 '유지'한다 (획이 둘로 쪼개지지 않게). 유지 시간을 넘거나
  다른 곳에서 다시 나타나거나 들어 올린 증거가 있으면 그때 끝낸다.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np


# ---------------------------------------------------------------- 설정
@dataclass
class FloorConfig:
    gate_frac: float = 0.0037        # G: 펜촉이 모서리보다 (프레임 높이 ×) 이만큼 아래여야 후보 (1080p 에서 4px)
    min_w_frac: float = 0.0104       # 최소 펜 굵기 (프레임 폭 ×). 1920 에서 20px
    roi_frac: float = 0.135          # 펜 기하를 볼 펜촉 주변 반경 (프레임 폭 ×)
    enter_h: float = 0.12            # [D] 바닥 단서 진입 문턱
    lift_sigmas: float = 1.5
    lift_min: float = 0.25           # [D] 이탈 = baseline 대비 max(lift_min, lift_sigmas·σ) 상승
    impossible_sigmas: float = 5.0
    impossible_min: float = 0.6      # [D] 책상 아래 판정 = max(impossible_min, impossible_sigmas·σ)
    baseline_tau_s: float = 0.05     # 접촉 baseline 추종 시상수 (초). 느린 자세 편향은 흡수, 빠른 들어 올림만 반응
    ring_near: float = 0.30          # S: 링 반지름 (펜 굵기 배)
    ring_far: float = 1.5
    w_window_s: float = 0.067        # 굵기 시간 안정성 창 (초)
    w_stable: float = 1.07
    smooth: int = 3
    ema: float = 0.5
    on_s: float = 0.033              # 진입·이탈에 필요한 지속 시간 (초)
    off_s: float = 0.033
    on_shadow_s: float = 0.067
    min_frames: int = 2              # 위 시간이 몇 프레임이든 최소 프레임 수
    memory_s: float = 0.33           # 분할 탈락 동안 접촉을 유지하는 최대 시간
    reacquire_tol: float = 0.2       # [D] 다시 나타날 때 baseline 대비 허용 높이
    min_samples: int = 40            # 바닥 모델 첫 적합에 필요한 표본 수
    width_pct: float = 100           # 굵기 = 축 단면별 최대 내접원의 이 분위수 (100 = 전체 최대, 원본 방식)
    shadow_release: bool = True      # 그림자 gap(+상승)으로 접촉을 끝낼 수 있다. False 면 gap 은 진입 거부만
    use_floor: bool = True
    use_shadow: bool = True
    use_memory: bool = True
    drift: str = "edge"              # edge: 책상 먼 모서리 추적 | off: 이미지 y 기준
    precise_width: bool = False      # 몸통 양쪽 윤곽을 서브픽셀로 재서 굵기를 구한다 (실험)
    roll: bool = True                # 바닥 평면에 좌우 기울기(카메라 롤) 항을 더한다 (a·x). 끄면 앞뒤 직선만


# ---------------------------------------------------------------- 책상 색 · 먼 모서리
def _same_color(a: np.ndarray, b: np.ndarray, a0: float, b0: float, hue_deg: float = 30.0) -> np.ndarray:
    chroma0 = math.hypot(a0, b0)
    chroma = np.hypot(a, b)
    if chroma0 >= 4:
        cosang = (a * a0 + b * b0) / np.maximum(chroma * chroma0, 1e-6)
        return (cosang >= math.cos(math.radians(hue_deg))) | (chroma < 0.35 * chroma0)
    return np.abs(a - a0) + np.abs(b - b0) < 18


def table_like(lab: np.ndarray, ref: tuple[float, float, float]) -> np.ndarray:
    """책상(밝은 면 + 그 위 그림자) 픽셀. ref = 밝은 책상 면의 Lab 중앙값 (L 0–100, a/b 부호 있음).

    밝은 면: 같은 색상(±25°), 채도 ≥ 책상의 0.5배, 밝기 0.72–1.3배. 회색 벽·흰 배경(채도 낮음)과 피부
    (색상이 다름)를 뺀다. 그림자: 밝기 0.15–0.72배, 색상 ±55°(그림자는 반사광으로 색상이 조금 돈다),
    채도 ≥ 0.4배이고 밝기 대비 채도(C/L)가 0.4 이상. 어두운 회색·무채색 배경은 C/L 이 작다.
    pen_test.mov 의 책상·그림자·벽·피부·청재킷 표본으로 정했다 (다른 장면에서 재검증 필요)."""
    L = lab[..., 0].astype(np.float32) * (100 / 255)
    a = lab[..., 1].astype(np.float32) - 128
    b = lab[..., 2].astype(np.float32) - 128
    L0, a0, b0 = ref
    c0 = math.hypot(a0, b0)
    chroma = np.hypot(a, b)
    if c0 < 6:  # 무채색 책상: 색상이 정의되지 않으니 밝기·무채색 여부만 본다
        grey = chroma < 8
        return grey & (L >= 0.15 * L0) & (L <= 1.3 * L0)
    cosang = (a * a0 + b * b0) / np.maximum(chroma * c0, 1e-6)
    lit = (cosang >= math.cos(math.radians(25))) & (chroma >= 0.5 * c0) & (L >= 0.72 * L0) & (L <= 1.3 * L0)
    shade = (cosang >= math.cos(math.radians(55))) & (chroma >= 0.4 * c0) & (chroma >= 0.4 * L) & \
        (L >= 0.15 * L0) & (L < 0.72 * L0)
    return lit | shade


class TableEdge:
    """책상 색 참조, 직사광 문턱, (drift=edge 일 때) 책상 먼 모서리 직선 y = a·x + b 를 추적한다.

    모서리는 3D 직선 → 화면 직선. 첫 적합은 RANSAC, 이후 이전 직선과 맞는 열만 써서 재적합하고 EMA 로
    평활한다. 손·소매가 가린 열은 이전 직선과 어긋나 자동으로 빠진다. 카메라가 천천히 기울어도 따라간다.
    """

    def __init__(self, track_edge: bool = True, every: int = 2, scale: float = 0.25, seed: int = 0) -> None:
        self.track_edge = track_edge
        self.every = every
        self.scale = scale
        self.line: tuple[float, float] | None = None
        self.ref: tuple[float, float, float] | None = None
        self.thr: float | None = None     # 그림자/밝은 면 밝기 문턱 (gray). None = 확산광
        self.lost = 0
        self.n = 0
        self.rng = np.random.default_rng(seed)

    def edge_y(self, x):
        if self.line is None:
            return 0.0 * np.asarray(x, np.float64)
        a, b = self.line
        return a * np.asarray(x, np.float64) + b

    def update(self, bgr: np.ndarray, pen_mask: np.ndarray | None) -> None:
        self.n += 1
        if self.n % self.every != 1 and self.every > 1 and self.ref is not None:
            return
        H, W = bgr.shape[:2]
        s = self.scale
        small = cv2.resize(bgr, (max(8, int(W * s)), max(8, int(H * s))), interpolation=cv2.INTER_AREA)
        hs, ws = small.shape[:2]
        lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        pen = None
        if pen_mask is not None:
            pen = cv2.resize(pen_mask.astype(np.uint8), (ws, hs), interpolation=cv2.INTER_NEAREST).astype(bool)
            pen = cv2.dilate(pen.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
        # 책상 색 참조: 화면 아래 1/3 에서 펜을 뺀 밝은 쪽 (기존 desk_reference 와 같은 정의)
        y3 = int(hs * 2 / 3)
        m = np.ones((hs - y3, ws), bool) if pen is None else ~pen[y3:]
        g = gray[y3:]
        if m.sum() > 50:
            sel = m & (g >= np.percentile(g[m], 70))
            if sel.sum() > 30:
                L = float(np.median(lab[y3:][..., 0][sel])) * 100 / 255
                a = float(np.median(lab[y3:][..., 1][sel])) - 128
                b = float(np.median(lab[y3:][..., 2][sel])) - 128
                self.ref = (L, a, b) if self.ref is None else tuple(
                    0.8 * p + 0.2 * q for p, q in zip(self.ref, (L, a, b), strict=True))  # type: ignore[assignment]
        if self.ref is None:
            return
        table = table_like(lab, self.ref).astype(np.uint8)
        table = cv2.morphologyEx(table, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)).astype(bool)
        if pen is not None:
            table |= pen  # 펜은 책상 위에 있다: 모서리 측정에서 구멍으로 보지 않는다
        if self.track_edge:
            self._fit_edge(table, H)
        # 직사광 판정: 책상 픽셀 밝기의 Otsu 이봉성
        rows = np.arange(hs, dtype=np.float32)[:, None]
        below = rows >= (self.edge_y((np.arange(ws) + .5) / s)[None, :] * s + 1) if self.line is not None \
            else rows >= hs * 0.5
        sel = table & below
        if pen is not None:
            sel &= ~pen
        v = gray[sel]
        self.thr = None
        if v.size >= 300:
            t, _ = cv2.threshold(v.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            lo, hi = v[v < t], v[v >= t]
            if lo.size >= 0.03 * v.size and hi.size >= 0.03 * v.size and hi.mean() >= 1.5 * max(lo.mean(), 1):
                self.thr = float(t)

    def _fit_edge(self, table: np.ndarray, H: int) -> None:
        hs, ws = table.shape
        s = self.scale
        inv = ~table[::-1]
        first = np.where(inv.any(0), inv.argmax(0), hs)       # 아래에서부터 책상이 이어진 길이
        e = (hs - first).astype(np.float32) / s
        x = (np.arange(ws, dtype=np.float32) + 0.5) / s
        valid = (first > 2) & (first < hs - 2)
        x, e = x[valid], e[valid]
        tol_wide, tol_tight = 20.0 * H / 1080, max(2.0, 4.0 * H / 1080 / (s / 0.5))
        new = None
        if self.line is not None and len(x) > 20:
            a, b = self.line
            inl = np.abs(a * x + b - e) < tol_wide
            if inl.sum() >= max(20 * s / 0.5, 0.12 * len(x)):
                a2, b2 = np.polyfit(x[inl], e[inl], 1)
                inl2 = np.abs(a2 * x + b2 - e) < tol_tight
                if inl2.sum() > 10:
                    a2, b2 = np.polyfit(x[inl2], e[inl2], 1)
                new = (float(a2), float(b2))
        if new is None:
            self.lost += 1
            if self.line is None or self.lost > 15:
                r = self._ransac(x, e, tol_tight)
                if r is not None:
                    self.line, self.lost = r, 0
        else:
            self.lost = 0
            a, b = self.line  # type: ignore[misc]
            self.line = (0.7 * a + 0.3 * new[0], 0.7 * b + 0.3 * new[1])

    def _ransac(self, x, y, tol, iters=200):
        if len(x) < 10:
            return None
        best, best_n = None, 0
        span = max(1.0, float(np.ptp(x)))
        for _ in range(iters):
            i, j = self.rng.choice(len(x), 2, replace=False)
            if abs(x[i] - x[j]) < 0.04 * span:
                continue
            a = (y[j] - y[i]) / (x[j] - x[i])
            if abs(a) > 0.3:
                continue
            b = y[i] - a * x[i]
            inl = np.abs(a * x + b - y) < tol
            if int(inl.sum()) > best_n:
                best_n, best = int(inl.sum()), inl
        if best is None or best_n < 0.12 * len(x):
            return None
        a, b = np.polyfit(x[best], y[best], 1)
        return float(a), float(b)


# ---------------------------------------------------------------- 펜 기하
@dataclass
class PenGeometry:
    tip: np.ndarray
    u: np.ndarray        # 몸통 → 펜촉 단위벡터
    w: float             # 몸통 굵기 (최대 내접원 지름, px)
    length: float        # ROI 안에서 보이는 길이 (px)
    w_ok: bool           # 몸통이 충분히 보여 굵기를 믿을 수 있음


def pen_geometry(mask: np.ndarray, tip: np.ndarray, u: np.ndarray, roi: float, width_pct: float = 100
                 ) -> PenGeometry | None:
    """펜촉 주변 ROI 의 마스크에서 몸통 굵기를 잰다. 펜촉 위치·축은 PenTracker 의 측정(경계 보정)을 쓴다."""
    H, W = mask.shape
    R = int(roi)
    x0, y0 = max(0, int(tip[0]) - R), max(0, int(tip[1]) - R)
    x1, y1 = min(W, int(tip[0]) + R + 1), min(H, int(tip[1]) + R + 1)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    sub = mask[y0:y1, x0:x1]
    ys, xs = np.nonzero(sub)
    if xs.size < 30:
        return None
    P = np.stack([xs + x0, ys + y0], 1).astype(np.float32)
    near = ((P - tip) ** 2).sum(1) < R * R
    if near.sum() < 30:
        return None
    sel = np.zeros_like(sub, np.uint8)
    sel[ys[near], xs[near]] = 1
    dt = cv2.distanceTransform(np.pad(sel, 1), cv2.DIST_L2, 5)[1:-1, 1:-1]
    proj = (P[near] - tip) @ u
    length = float(-proj.min())
    if width_pct >= 100:
        w = 2.0 * float(dt.max())
    else:
        # 축을 따라 자른 단면마다 최대 내접원 → 그 분위수. 원뿔 끝(작음)과 손가락이 붙은 곳(큼)에 덜 흔들린다.
        back = -proj
        dv = dt[ys[near], xs[near]]
        b = (back / 3.0).astype(int)
        mx = np.zeros(int(b.max()) + 1)
        np.maximum.at(mx, b, dv)
        mx = mx[mx > 0]
        w = 2.0 * float(np.percentile(mx, width_pct)) if mx.size >= 3 else 2.0 * float(dt.max())
    return PenGeometry(np.asarray(tip, float), np.asarray(u, float), w, length, length >= 1.8 * w)


def edge_width(gray: np.ndarray, tip: np.ndarray, u: np.ndarray, w0: float) -> float | None:
    """몸통 양쪽 윤곽 사이 거리 (서브픽셀). 펜촉에서 1~3 굵기 뒤의 여러 단면에서 밝기 기울기 극값 두 개를
    찾고 그 간격의 중앙값. 측정이 불안정하면 None."""
    if not math.isfinite(w0) or w0 < 4:
        return None
    v = np.array([-u[1], u[0]])
    stations = np.linspace(1.2, 3.0, 7) * w0
    half = 1.0 * w0
    ts = np.arange(-half, half + 0.25, 0.25)
    pts = tip[None, None, :] - stations[:, None, None] * u[None, None, :] + ts[None, :, None] * v[None, None, :]
    prof = cv2.remap(gray.astype(np.float32), pts[..., 0].astype(np.float32), pts[..., 1].astype(np.float32),
                     cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    prof = cv2.GaussianBlur(prof, (5, 1), 0)
    g = np.gradient(prof, axis=1)
    out = []
    mid = len(ts) // 2
    for row in g:
        left, right = row[:mid], row[mid:]
        if left.size < 3 or right.size < 3:
            continue
        # 펜과 배경 대비 방향을 모른다: 양쪽에서 크기 최대, 부호가 반대여야 한다
        il, ir = int(np.argmax(np.abs(left))), int(np.argmax(np.abs(right))) + mid
        if np.sign(row[il]) == np.sign(row[ir]) or min(abs(row[il]), abs(row[ir])) < 2.0:
            continue
        def sub(i):
            if 0 < i < len(row) - 1:
                a, b, c = abs(row[i - 1]), abs(row[i]), abs(row[i + 1])
                den = a - 2 * b + c
                return i + (0.5 * (a - c) / den if abs(den) > 1e-9 else 0.0)
            return float(i)
        out.append((sub(ir) - sub(il)) * 0.25)
    if len(out) < 3:
        return None
    wm = float(np.median(out))
    return wm if 0.6 * w0 < wm < 1.4 * w0 else None


# ---------------------------------------------------------------- 바닥 모델
class FloorModel:
    """바닥 평면: 접촉한 펜촉은 d = k·w + a·x − c 를 만족한다 (온라인 학습).

    d  = 펜촉 y (또는 책상 모서리 대비 y),  w = 펜 몸통 굵기 (∝ 1/깊이),  x = 펜촉의 좌우 위치 (프레임 폭 대비, 가운데 0)
    바닥 평면에서는 역깊이가 화면 좌표의 1차식이고 접촉한 펜의 굵기는 역깊이에 비례하므로, 접촉 점들은 (x, y, w) 공간의
    한 평면 위에 있다. k·w 항은 앞뒤(가까움-멈) 그라데이션, a·x 항은 카메라가 옆으로 기울어진(롤) 만큼의 좌우 기울기다.
    a 는 x 가 충분히 퍼져 있을 때만 맞추고, 아니면 0 (예전과 같은 직선). 손으로 찍은 접촉 표본(set_touches)은 평면을
    곧바로 정하고 이후 자동 학습의 닻 역할을 한다.
    버퍼 (w, d, weight, x).
    """

    X_SPREAD = 0.2            # x 가 이만큼(프레임 폭 비율) 퍼져야 롤 항을 맞춘다
    A_MAX = 0.5               # |a| 상한 (프레임 폭 배; 롤 약 27° 까지)
    RIDGE = 1e-3              # a 를 0 쪽으로 당기는 약한 정규화

    def __init__(self, maxlen: int = 1800, min_samples: int = 40, refit_every: int = 10, tol_frac: float = 0.12,
                 tol_px: float = 2.0, seed: int = 0, roll: bool = True) -> None:
        self.buf: deque = deque(maxlen=maxlen)
        self.anchors: list[tuple[float, float, float, float]] = []   # 손으로 찍은 접촉 (w, d, weight, x)
        self.min_samples, self.refit_every = min_samples, refit_every
        self.tol_frac, self.tol_px = tol_frac, tol_px
        self.roll = roll
        self.k: float | None = None
        self.c: float | None = None
        self.a: float = 0.0
        self.a_fixed: float | None = None   # 값이 있으면 좌우 기울기를 맞추지 않고 이 값(px)으로 고정 (깊이 모델 사전 실험)
        self.a_max_px = 0.0       # |a| 상한 (px). 프레임 폭을 알 때 FloorContact 가 정한다
        self.sigma: float | None = None
        self.n_since = 0
        self.rng = np.random.default_rng(seed)

    @property
    def ready(self) -> bool:
        return self.k is not None

    def add(self, w: float, d: float, weight: float = 1.0, x: float = 0.0) -> None:
        self.buf.append((w, d, weight, x))
        self.n_since += 1
        if len(self.buf) >= self.min_samples and (not self.ready or self.n_since >= self.refit_every):
            self.fit()
            self.n_since = 0

    def _data(self) -> np.ndarray:
        rows = list(self.buf) + self.anchors
        return np.array(rows, np.float64)

    def fit(self, iters: int = 300) -> bool:
        arr = self._data()
        if arr.ndim != 2 or len(arr) < 3:
            return False   # 표본이 아직 없다 (깊이 모델 기울기가 먼저 정해질 수 있다)
        w, d, wt, x = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]
        med = float(np.median(w))
        if np.ptp(w) < max(4.0, 0.2 * med):
            return False  # 거리(굵기)가 다양하지 않으면 기울기를 정할 수 없다
        a_off = 0.0
        if self.a_fixed is not None:        # 좌우 기울기를 이미 알면 그만큼 빼고 직선(k, c)만 맞춘다
            a_off = float(self.a_fixed)
            d = d - a_off * x
        roll = self.roll and self.a_fixed is None and np.ptp(x) >= self.X_SPREAD and self.a_max_px > 0
        tol = self.tol_frac * w + self.tol_px
        best, best_s = None, -1e18
        n = len(w)
        min_dw = max(3.0, 0.12 * med)
        for _ in range(iters):
            if roll:
                idx = self.rng.choice(n, 3, replace=False)
                M = np.stack([w[idx], x[idx], -np.ones(3)], 1)
                if abs(np.linalg.det(M)) < 1e-6 * (med * 0.1) or np.linalg.cond(M) > 1e4:
                    continue
                try:
                    k, a_, c = np.linalg.solve(M, d[idx])
                except np.linalg.LinAlgError:
                    continue
                if abs(a_) > self.a_max_px:
                    continue
            else:
                i, j = self.rng.choice(n, 2, replace=False)
                if abs(w[i] - w[j]) < min_dw:
                    continue
                k = (d[j] - d[i]) / (w[j] - w[i])
                c = k * w[i] - d[i]
                a_ = 0.0
            if not (0.5 < k < 8.0):
                continue
            res = d - (k * w + a_ * x - c)              # > 0: 책상 아래
            sc = float((wt * (np.abs(res) < tol)).sum() - (wt * (res > 2.5 * tol)).sum())
            if sc > best_s:
                best_s, best = sc, (k, c, a_)
        if best is None:
            return False
        k, c, a_ = best
        for _ in range(5):  # IRLS (Tukey biweight, 펜 지름 단위 잔차)
            r = (d - (k * w + a_ * x - c)) / w
            # 척도는 현재 내점(접촉 후보)의 MAD 로 잰다. 전체 점의 MAD 는 떠 있는 표본(버퍼의 절반 가까이)에
            # 부풀려져 직선을 떠 있는 쪽으로 끌어당긴다.
            inl = np.abs(r) < self.tol_frac + self.tol_px / np.maximum(w, 1)
            rr = r[inl] if inl.sum() >= 10 else r
            s_ = max(1.4826 * float(np.median(np.abs(rr - np.median(rr)))), 0.05)
            u_ = r / (4.685 * s_)
            bw = np.where(np.abs(u_) < 1, (1 - u_ ** 2) ** 2, 0.0) * wt
            if bw.sum() < 10:
                break
            cols = [w, -np.ones_like(w)] + ([x] if roll else [])
            A = np.stack(cols, 1)
            sw = np.sqrt(bw)
            lhs, rhs = A * sw[:, None], d * sw
            if roll:  # a 를 0 쪽으로 당기는 약한 정규화 (x 가 충분히 퍼져 있어도 표본이 적을 때 안정)
                reg = np.zeros((1, 3))
                reg[0, 2] = np.sqrt(self.RIDGE * float(bw.sum()))
                lhs, rhs = np.vstack([lhs, reg]), np.append(rhs, 0.0)
            sol = np.linalg.lstsq(lhs, rhs, rcond=None)[0]
            if not (0.5 < sol[0] < 8.0) or (roll and abs(sol[2]) > self.a_max_px):
                break
            k, c = float(sol[0]), float(sol[1])
            a_ = float(sol[2]) if roll else 0.0
        self.k, self.c, self.a = float(k), float(c), float(a_ + a_off)
        r = (d - (self.k * w + a_ * x - self.c)) / w
        r = r[np.abs(r) < 3 * self.tol_frac + 0.1]
        if r.size >= 10:
            self.sigma = float(1.4826 * np.median(np.abs(r - np.median(r))))
        return True

    def set_touches(self, touches: list[tuple[float, float, float]], weight: float = 6.0) -> bool:
        """사용자가 '지금 닿아 있음' 으로 찍은 접촉 (w, d, x). 평면을 곧바로 정하고 이후 학습의 닻으로 남긴다.

        3점 이상이고 w 와 x 가 모두 퍼져 있으면 (k, a, c) 를, 아니면 (k, c) 직선을 최소제곱으로 맞춘다
        (가까운·먼·옆 세 곳을 찍으면 평면이 정확히 정해진다)."""
        pts = [(float(w), float(d), float(x)) for w, d, x in touches if w > 1 and np.isfinite([w, d, x]).all()]
        if len(pts) < 2:
            return False
        T = np.array(pts)
        if np.ptp(T[:, 0]) < max(3.0, 0.1 * float(np.median(T[:, 0]))):
            return False                                   # 거리가 한 가지면 기울기를 알 수 없다
        a_off = 0.0 if self.a_fixed is None else float(self.a_fixed)   # 깊이 모델이 기울기를 정했으면 직선(k, c)만 맞춘다
        roll = self.roll and self.a_fixed is None and len(pts) >= 3 and np.ptp(T[:, 2]) >= 0.08 and self.a_max_px > 0
        cols = [T[:, 0], -np.ones(len(T))] + ([T[:, 2]] if roll else [])
        sol = np.linalg.lstsq(np.stack(cols, 1), T[:, 1] - a_off * T[:, 2], rcond=None)[0]
        if not (0.5 < sol[0] < 8.0) or (roll and abs(sol[2]) > self.a_max_px):
            return False
        self.k, self.c, self.a = float(sol[0]), float(sol[1]), (float(sol[2]) if roll else 0.0) + a_off
        self.anchors = [(w, d, weight, x) for w, d, x in pts]
        self.sigma = self.sigma or 0.15
        return True

    def contact_d(self, w: float, x: float = 0.0) -> float | None:
        """굵기 w, 좌우 위치 x 에서 닿았을 때의 d (펜촉 y)."""
        if not self.ready:
            return None
        return self.k * w + self.a * x - self.c           # type: ignore[operator]

    def contact_w(self, d: float, x: float = 0.0) -> float | None:
        """(x, d) 위치에 닿은 펜의 예상 굵기. 바닥 그라데이션 맵의 값 (가까울수록 크다)."""
        if not self.ready:
            return None
        return (d + self.c - self.a * x) / self.k          # type: ignore[operator]

    def hover(self, w: float, d: float, x: float = 0.0) -> float | None:
        if not self.ready or w <= 1:
            return None
        return self.k - (d + self.c - self.a * x) / w     # type: ignore[operator]


# ---------------------------------------------------------------- 상태기계
@dataclass
class FloorDecision:
    contact: bool
    holding: bool = False            # 분할 탈락 중 접촉 유지
    onset_t: float | None = None     # 접촉 진입 시: 진입 근거가 처음 나온 시각 (획 앞부분 소급용)
    offset_t: float | None = None    # 접촉 이탈 시: 이탈 근거가 처음 나온 시각 (획 끝 정리용)
    reason: str = ""
    info: dict = field(default_factory=dict)


class FloorContact:
    def __init__(self, cfg: FloorConfig | None = None) -> None:
        self.cfg = cfg or FloorConfig()
        c = self.cfg
        self.table = TableEdge(track_edge=c.drift == "edge")
        self.floor = FloorModel(min_samples=c.min_samples, roll=c.roll)
        self.w_raw: deque = deque(maxlen=8)
        self.w_hist: deque = deque(maxlen=3)
        self.h_hist: deque = deque(maxlen=c.smooth)
        self.h_s: float | None = None
        self.base: float | None = None
        self.state = False
        self.on_cnt = self.off_cnt = 0
        self.on_t: float | None = None
        self.off_t: float | None = None
        self.hold_since: float | None = None
        self.lost: tuple[float | None, np.ndarray | None, float | None] | None = None  # (base, tip, w)
        self.last_tip: np.ndarray | None = None
        self.last_w: float | None = None
        self.t_prev: float | None = None
        self.dt = 1 / 30
        self.info: dict = {}
        self._scaled = False
        self.gap_run = 0
        self.gate_run = 0
        self.last_xn = 0.0
        self._W = 0

    # ---------------- 문턱 (σ 비례)
    @property
    def sigma(self) -> float:
        return self.floor.sigma if self.floor.sigma is not None else 0.15

    @property
    def lift_delta(self) -> float:
        return max(self.cfg.lift_min, self.cfg.lift_sigmas * self.sigma)

    @property
    def impossible(self) -> float:
        return max(self.cfg.impossible_min, self.cfg.impossible_sigmas * self.sigma)

    def frames(self, seconds: float) -> int:
        return max(self.cfg.min_frames, int(round(seconds / max(self.dt, 1e-3))))

    def _tick(self, t: float) -> None:
        if self.t_prev is not None and t > self.t_prev:
            d = t - self.t_prev
            self.dt = d if self.dt is None else 0.8 * self.dt + 0.2 * min(d, 0.2)
        self.t_prev = t
        n = max(3, self.frames(self.cfg.w_window_s))
        if self.w_raw.maxlen != n:
            self.w_raw = deque(self.w_raw, maxlen=n)

    def reset_lost(self) -> None:
        self.lost = None
        self.hold_since = None

    # ---------------- 분할 탈락 (PenTracker 가 펜촉을 못 잼)
    def dropout(self, t: float) -> FloorDecision:
        self._tick(t)
        self.w_raw.clear()
        self.w_hist.clear()
        self.h_hist.clear()
        self.h_s = None
        self.on_cnt, self.on_t = 0, None
        if not self.state:
            return FloorDecision(False, reason="no pen")
        if not self.cfg.use_memory:
            return self._release(t, "dropout", remember=False)
        if self.hold_since is None:
            self.hold_since = t
            self.lost = (self.base, None if self.last_tip is None else self.last_tip.copy(), self.last_w)
        if t - self.hold_since > self.cfg.memory_s:
            return self._release(t, "dropout timeout", remember=False, offset=self.hold_since)
        return FloorDecision(True, holding=True, reason="hold (dropout)")

    def _release(self, t: float, reason: str, remember: bool, offset: float | None = None) -> FloorDecision:
        self.state = False
        self.on_cnt = self.off_cnt = 0
        self.on_t = None
        off = offset if offset is not None else (self.off_t if self.off_t is not None else t)
        self.off_t = None
        self.hold_since = None
        if not remember:
            self.lost = None
        return FloorDecision(False, offset_t=off, reason=reason)

    def probe(self, bgr: np.ndarray, gray: np.ndarray, mask: np.ndarray, tip: np.ndarray, u: np.ndarray
              ) -> tuple[float, float, float] | None:
        """상태를 바꾸지 않고 지금 프레임의 (굵기 w, d, 좌우 위치 x) 만 잰다. 안내 보정이 접촉 표본을 모을 때 쓴다.
        몸통이 충분히 보이지 않으면 None."""
        c = self.cfg
        H, W = gray.shape
        self._W = W
        geo = pen_geometry(mask, tip, u, c.roi_frac * W, c.width_pct)
        if geo is None or not geo.w_ok or geo.w < c.min_w_frac * W:
            return None
        self.table.update(bgr, mask)
        return float(geo.w), float(tip[1] - self.table.edge_y(tip[0])), float(tip[0]) / W - 0.5

    def floor_region(self, bgr: np.ndarray, pen_mask: np.ndarray | None, size: tuple[int, int]) -> np.ndarray | None:
        """size=(폭, 높이) 해상도의 바닥 영역: 같은 프레임의 책상 색과 맞는 픽셀 (펜은 뺀다). 책상 색이 없으면 None.
        바닥 평면(접촉 굵기)이 아직 학습되지 않았어도 만들 수 있다 (깊이 모델 기울기용)."""
        if self.table.ref is None:
            return None
        H, W = bgr.shape[:2]
        sw, sh = size
        small = cv2.resize(bgr, (sw, sh), interpolation=cv2.INTER_AREA)
        floor = table_like(cv2.cvtColor(small, cv2.COLOR_BGR2LAB), self.table.ref)
        if pen_mask is not None and pen_mask.shape[:2] == (H, W):
            pm = cv2.resize(pen_mask.astype(np.uint8), (sw, sh), interpolation=cv2.INTER_NEAREST)
            floor &= ~(cv2.dilate(pm, np.ones((5, 5), np.uint8)) > 0)
        # 잡티 제거: 구멍 메우고 작은 조각은 버린다
        f8 = cv2.morphologyEx(floor.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        n, lab, stats, _ = cv2.connectedComponentsWithStats(f8, connectivity=8)
        keep = np.zeros(n, bool)
        keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= 0.004 * sw * sh
        return keep[lab]

    def floor_planes(self, bgr: np.ndarray, pen_mask: np.ndarray | None, size: tuple[int, int]
                     ) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        """size=(폭, 높이) 해상도에서 (바닥 영역, 접촉 굵기 맵 wc, 유효 영역 = 바닥 ∧ wc>0). 평면·책상 색이 없으면 None."""
        fm = self.floor
        if not fm.ready:
            return None
        floor = self.floor_region(bgr, pen_mask, size)
        if floor is None:
            return None
        H, W = bgr.shape[:2]
        sw, sh = size
        yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float64)
        xs, ys = (xx + 0.5) * W / sw, (yy + 0.5) * H / sh
        d = ys - self.table.edge_y(xs)
        wc = fm.contact_w(d, xs / W - 0.5)
        valid = floor & np.isfinite(wc) & (wc > 0.0)
        return floor, wc, valid

    def render_map(self, bgr: np.ndarray, pen_mask: np.ndarray | None = None, out_w: int = 320) -> dict:
        """바닥 그라데이션 맵 (개발자용). 바닥 영역에서 '그 자리에 닿은 펜의 예상 굵기'를 흑백으로 그린다.

        가까울수록(화면 아래) 밝고 멀수록(위) 어둡다. 카메라가 옆으로 기울어졌으면 좌우로도 기울어져 보인다.
        반환: ready, 평면 계수, 맵 PNG(불투명)·오버레이 PNG(RGBA), 값 범위. 평면이 없으면 ready=False 와 이유."""
        fm = self.floor
        H, W = bgr.shape[:2]
        info = {"ready": False, "size": [W, H], "k": fm.k, "c": fm.c, "a": fm.a, "sigma": fm.sigma,
                "samples": len(fm.buf), "anchors": len(fm.anchors),
                "roll_deg": None if not fm.ready else round(float(np.degrees(np.arctan2(fm.a, W))), 2)}
        if not fm.ready:
            info["reason"] = "learning"
            return info
        if self.table.ref is None:
            info["reason"] = "no_table_color"
            return info
        sw, sh = out_w, max(8, round(H * out_w / W))
        floor, wc, valid = self.floor_planes(bgr, pen_mask, (sw, sh))  # type: ignore[misc]
        info.update(ready=True, valid_frac=round(float(valid.mean()), 3))
        if valid.sum() < 50:
            info["reason"] = "no_floor"
            info["image"] = _png(np.zeros((sh, sw), np.uint8))
            return info
        lo, hi = (float(v) for v in np.percentile(wc[valid], [2, 98]))
        hi = max(hi, lo + 1e-6)
        g = np.clip((wc - lo) / (hi - lo), 0.0, 1.0)
        gray = np.where(valid, 40 + 215 * g, 0).astype(np.uint8)
        # 등고선: 값이 8단계로 바뀌는 곳에 어두운 선 (기울기를 눈으로 보기 쉽게)
        lvl = np.where(valid, np.floor(g * 7.999), -1)
        edge = np.zeros_like(valid)
        edge[:, 1:] |= lvl[:, 1:] != lvl[:, :-1]
        edge[1:, :] |= lvl[1:, :] != lvl[:-1, :]
        panel = gray.copy()
        panel[edge & valid] = (panel[edge & valid] * 0.55).astype(np.uint8)
        over = np.zeros((sh, sw, 4), np.uint8)
        over[..., :3] = gray[..., None]
        over[..., 3] = np.where(valid, 150, 0)
        info.update(image=_png(panel), overlay=_png(over), w_range=[round(lo, 2), round(hi, 2)])
        return info

    def set_touch_plane(self, touches: list[tuple[float, float, float]]) -> bool:
        """가까운·먼·옆 접촉 표본 (w, d, x)으로 바닥 평면을 정한다. 이후 자동 학습의 닻이 된다."""
        self.floor.a_max_px = FloorModel.A_MAX * (self._W or 1280)
        return self.floor.set_touches(touches)

    # ---------------- 매 프레임 (펜촉을 잰 프레임)
    def process(self, bgr: np.ndarray, gray: np.ndarray, mask: np.ndarray, tip: np.ndarray, u: np.ndarray,
                t: float) -> FloorDecision:
        c = self.cfg
        self._tick(t)
        H, W = gray.shape
        self._W = W
        self.table.update(bgr, mask)
        geo = pen_geometry(mask, tip, u, c.roi_frac * W, c.width_pct)
        info: dict = {"edge": self.table.line, "shadow_light": self.table.thr is not None}
        self.info = info
        if geo is None:
            info["reason"] = "geometry"
            return self.dropout(t)
        w_meas = geo.w
        if c.precise_width and geo.w_ok:
            ew = edge_width(gray, geo.tip, geo.u, geo.w)
            if ew is not None:
                w_meas = ew
        # 굵기는 깊이가 변하는 속도로만 변한다. 빠르게 변하는 굵기(펜이 들어오는 중, 분할이 따라오는 중)는
        # 판정에 쓰지 않는다.
        self.w_raw.append(w_meas)
        stable = len(self.w_raw) == self.w_raw.maxlen and \
            max(self.w_raw) - min(self.w_raw) <= (c.w_stable - 1) * float(np.median(self.w_raw)) + 3.0 * W / 1920
        fit_ok = geo.w_ok
        use_ok = geo.w_ok and stable
        if use_ok:
            self.w_hist.append(w_meas)
        else:
            self.w_hist.clear()
        w = float(np.median(self.w_hist)) if self.w_hist else w_meas
        d = float(tip[1] - self.table.edge_y(tip[0]))
        xn = float(tip[0]) / W - 0.5                       # 좌우 위치 (프레임 폭 대비, 가운데 0)
        if not self._scaled:  # 바닥 모델 픽셀 허용치를 해상도에 맞춘다
            self.floor.tol_px = 2.0 * W / 1920
            self.floor.a_max_px = FloorModel.A_MAX * W
            self._scaled = True
        self.last_xn = xn
        jumped = self.last_tip is None or float(np.hypot(*(tip - self.last_tip))) > 0.6 * max(w, 1.0)
        above = self.table.line is not None and d < c.gate_frac * H
        self.gate_run = self.gate_run + 1 if above else 0
        # 확실히 위(굵기 절반 이상)면 즉시, 모서리 근처의 펜촉 떨림이면 2프레임 연속일 때만
        gate_off = above and (d < c.gate_frac * H - 0.5 * w or self.gate_run >= 2)
        hov = self.floor.hover(w, d, xn) if use_ok else None
        imp = hov is not None and hov < -self.impossible and (not self.state or jumped)
        shadow = None
        info.update(w=round(w, 2), d=round(d, 2), w_ok=geo.w_ok, stable=stable)
        if gate_off:
            info["reason"] = "G: tip above far edge"
            self.h_hist.clear()
            self.h_s = None
            self.last_tip, self.last_w = np.asarray(tip, float).copy(), w
            self.reset_lost()
            if self.state:
                return self._release(t, "gate", remember=False, offset=t)
            self.on_cnt, self.on_t = 0, None
            return FloorDecision(False, reason="gate", info=info)
        if w < c.min_w_frac * W or imp:
            info["reason"] = "invalid: " + ("pen too small" if not imp else "below table")
            return self.dropout(t)
        if c.use_shadow and self.table.thr is not None and self.table.ref is not None:
            sn, sf = self._shadow_ring(bgr, gray, mask, geo, w)
            info.update(s_near=None if sn is None else round(sn, 3), s_far=None if sf is None else round(sf, 3))
            if sn is not None and sf is not None:
                if sn < 0.08 and sf < 0.5:
                    shadow = "gap"
                elif sn > 0.30 and sf < 0.20:
                    shadow = "attached"
        info["shadow"] = shadow
        if fit_ok:
            old = (self.floor.k, self.floor.c, self.floor.a)
            h_old = self.floor.hover(w, d, xn)
            self.floor.add(geo.w if not c.precise_width else w_meas, d,
                           {"attached": 3.0, "gap": 0.3}.get(shadow or "", 1.0), xn)
            h_new = self.floor.hover(w, d, xn)
            if (self.floor.k, self.floor.c, self.floor.a) != old and h_old is not None and h_new is not None:
                # 모델이 다시 맞춰지면 같은 (w, d) 의 높이가 바뀐다. 접촉 baseline·평활값을 새 모델 단위로 옮겨
                # 재적합 자체가 '들어 올림' 으로 읽히지 않게 한다.
                delta = h_new - h_old
                if self.base is not None:
                    self.base += delta
                if self.h_s is not None:
                    self.h_s += delta
                self.h_hist = deque((v + delta for v in self.h_hist), maxlen=self.h_hist.maxlen)
        if use_ok:
            hov = self.floor.hover(w, d, xn)
        if not c.use_floor:
            hov = None
        if hov is not None:
            self.h_hist.append(hov)
            h_med = float(np.median(self.h_hist))
            self.h_s = h_med if self.h_s is None else (1 - c.ema) * self.h_s + c.ema * h_med
        else:
            self.h_hist.clear()
            self.h_s = None
        info.update(hover=None if hov is None else round(hov, 3), h_s=None if self.h_s is None else round(self.h_s, 3),
                    base=None if self.base is None else round(self.base, 3), sigma=round(self.sigma, 3),
                    lift_delta=round(self.lift_delta, 3), k=self.floor.k, c=self.floor.c, a=self.floor.a)
        dec = self._step(t, tip, shadow)
        self.last_tip, self.last_w = np.asarray(tip, float).copy(), w
        dec.info = info
        info["reason"] = dec.reason
        return dec

    def _step(self, t: float, tip: np.ndarray, shadow: str | None) -> FloorDecision:
        c = self.cfg
        h = self.h_s
        if self.state and self.hold_since is not None:
            # 탈락 뒤 다시 보임: 사라진 곳 근처에서, 들어 올린 증거 없이 나타나면 같은 접촉을 잇는다
            b0, t0, w0 = self.lost or (None, None, None)
            near = t0 is not None and w0 is not None and float(np.hypot(*(tip - t0))) < 1.0 * w0
            h_ok = h is None or b0 is None or h < b0 + c.reacquire_tol
            self.hold_since, self.lost = None, None
            if not (near and h_ok):
                return self._release(t, "reappeared elsewhere/lifted", remember=False)
            return FloorDecision(True, reason="resumed")
        # 그림자 'gap' 은 한 프레임씩 깜빡인다 (펜촉 그림자가 펜 몸통 뒤로 숨는 각도). 연속일 때만 믿는다.
        self.gap_run = self.gap_run + 1 if shadow == "gap" else 0
        gap = self.gap_run >= 2
        if not self.state:
            by_floor = h is not None and not gap and -3.0 * self.sigma < h < c.enter_h
            by_shadow = shadow == "attached" and (h is None or h < c.enter_h + self.lift_delta)
            if by_floor:
                need = self.frames(c.on_s)
            elif by_shadow:
                need = self.frames(c.on_shadow_s)
            else:
                need = None
            if need is None:
                self.on_cnt, self.on_t = 0, None
                return FloorDecision(False, reason=f"air{'' if h is None else f' F:{h:+.2f}D'}"
                                     f"{'' if not shadow else ' S:' + shadow}")
            if self.on_cnt == 0:
                self.on_t = t
            self.on_cnt += 1
            if self.on_cnt >= need:
                onset = self.on_t
                self.state, self.on_cnt, self.off_cnt, self.on_t, self.off_t = True, 0, 0, None, None
                self.base = h if h is not None else c.enter_h
                return FloorDecision(True, onset_t=onset, reason="down " + ("F" if by_floor else "S"))
            return FloorDecision(False, reason="arming")
        rise = None if h is None or self.base is None else h - self.base
        lift = rise is not None and rise > self.lift_delta and shadow != "attached"
        # gap 단독으로는 끊지 않는다: 바닥 기하도 상승을 보이거나(문턱의 절반) 높이를 모를 때만 이탈 근거
        gap_lift = c.shadow_release and gap and (rise is None or rise > 0.5 * self.lift_delta)
        want_off = gap_lift or lift
        if want_off:
            if self.off_cnt == 0:
                self.off_t = t
            self.off_cnt += 1
            need = self.frames(c.off_s)
            if len(self.h_hist) < (self.h_hist.maxlen or 1):
                need = max(need, 2)  # 평활이 막 다시 시작됐다: 한 표본의 잡음으로 끊지 않는다
            if self.off_cnt >= need:
                return self._release(t, "lift" if lift else "S:gap+rise", remember=False)
            return FloorDecision(True, reason="releasing")
        self.off_cnt, self.off_t = 0, None
        if h is not None and self.base is not None:
            alpha = 1 - math.exp(-max(self.dt, 1e-3) / max(c.baseline_tau_s, 1e-3))
            self.base = (1 - alpha) * self.base + alpha * h
        return FloorDecision(True, reason="contact")

    # ---------------- S: 펜 끝 그림자 링
    def _shadow_ring(self, bgr: np.ndarray, gray: np.ndarray, mask: np.ndarray, geo: PenGeometry, w: float
                     ) -> tuple[float | None, float | None]:
        c = self.cfg
        tip, u = geo.tip, geo.u
        R = int(c.ring_far * w) + 4
        H, W = gray.shape
        X0, X1 = max(int(tip[0]) - R, 0), min(int(tip[0]) + R + 1, W)
        Y0, Y1 = max(int(tip[1]) - R, 0), min(int(tip[1]) + R + 1, H)
        if X1 - X0 < 4 or Y1 - Y0 < 4:
            return None, None
        g = gray[Y0:Y1, X0:X1]
        m = mask[Y0:Y1, X0:X1].astype(bool)
        yy, xx = np.mgrid[Y0:Y1, X0:X1].astype(np.float32)
        proj = (xx - tip[0]) * u[0] + (yy - tip[1]) * u[1]
        cap = (m & (proj >= -0.6 * w)).astype(np.uint8)
        if cap.sum() == 0:
            return None, None
        dist = cv2.distanceTransform((1 - cap).astype(np.uint8), cv2.DIST_L2, 5)
        lab = cv2.cvtColor(bgr[Y0:Y1, X0:X1], cv2.COLOR_BGR2LAB)
        on_table = ~m & table_like(lab, self.table.ref)  # type: ignore[arg-type]
        if self.table.line is not None:
            on_table &= yy >= self.table.edge_y(xx) + 1
        rn = max(c.ring_near * w, 3.0)
        near = on_table & (dist > 0.5) & (dist <= rn)
        far = on_table & (dist > rn) & (dist <= c.ring_far * w)
        if near.sum() < 5 or far.sum() < 20:
            return None, None
        sh = g < self.table.thr
        return float(sh[near].mean()), float(sh[far].mean())

    # ---------------- 사용자 보정
    def mark_touching(self, w: float, d: float, xn: float = 0.0, n: int = 15) -> None:
        """사용자가 '지금 닿아 있음' 을 알려 준 표본: 바닥 모델에 무겁게 넣는다."""
        for _ in range(n):
            self.floor.buf.append((w, d, 3.0, xn))
        if len(self.floor.buf) >= self.floor.min_samples:
            self.floor.fit()

    def horizon_y(self, x: float) -> float | None:
        """바닥 모델이 함의하는 책상 소실선 y (= 기준선 − c). 굵기·펜촉 정의 편향이 c 에 섞일 수 있다(실험)."""
        if not self.floor.ready:
            return None
        return float(self.table.edge_y(x)) - float(self.floor.c) + float(self.floor.a) * (x / self._W - 0.5 if self._W else 0.0)  # type: ignore[arg-type]


def _png(img: np.ndarray) -> str:
    import base64
    ok, buf = cv2.imencode(".png", img)
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode() if ok else ""
