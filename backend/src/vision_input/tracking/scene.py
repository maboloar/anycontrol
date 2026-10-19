"""정지 배경 모델 (색 + 깊이): '배경은 움직이지 않고 물체·손·팔만 움직인다' 를 추적 신호로 쓴다.

책상 위 작업 공간은 대부분 그대로이고 바뀌는 것은 물체와 손뿐이다. 그래서 배경을 픽셀마다 기억해 두면
'지금 배경과 달라진 곳 = 전경(물체 또는 손)' 을 색 히스토그램보다 훨씬 날카롭게 가를 수 있다.

색 배경
- 픽셀마다 Lab 평균·분산. 전역 밝기(L 배율·a/b 이동)와 카메라 미세 이동(위상 상관 평행이동)을 매 프레임 보정한다.
- 그림자(어두워지기만 하고 색은 그대로)는 약한 전경으로만 본다. 깊이가 '가까워지지 않았다' 고 하면 배경으로 돌린다.
- 선택적 학습: 추적 중인 물체(amodal + 여유)와 손 영역은 배경으로 배우지 않는다 → 멈춰 있는 물체가 배경에 흡수되지 않는다.
  추적하지 않는 새 물건은 몇 초에 걸쳐 천천히 배경이 된다.
- 등록 때 물체 밑은 '모름' 으로 둔다(물체가 원래 거기 있었으면 배경이 물체로 학습돼 있다). 물체가 떠나면 그 자리를 채운다.

깊이 배경 (Depth Anything V2, 선택)
- 출력은 프레임마다 스케일·이동이 다른 상대 역깊이다. 배경으로 보이는 픽셀에서 d ≈ a·배경 + b 를 강건하게 맞춰 정렬한다.
- '배경보다 가까워짐' 만 전경 근거다. 반사·그림자·조명 변화는 깊이를 바꾸지 않고, 물체가 떠난 자리(멀어짐)는 유령이 되지 않는다.
- 깊이는 몇 프레임 늦게 도착한다(비동기). 그 나이(age)를 같이 돌려줘서 쓰는 쪽이 움직임에 맞춰 가중치를 줄인다.

안전장치
- 배경으로 알던 영역의 넓은 부분이 한꺼번에 바뀌면(카메라를 움직임·조명 급변) 그 프레임은 '무효' 이고 아무 신호도 내지 않는다.
  무효가 이어지면 배경을 처음부터 다시 배운다. 손에 든 카메라에서는 사실상 꺼진 것과 같다 → 기존 추적과 동일.

출력은 로그 오즈(+ = 전경, − = 배경, 0 = 모름). 내부 해상도는 폭 320.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class SceneConfig:
    enabled: bool = True
    width: int = 320                 # 내부 해상도 (폭)
    learn_s: float = 2.0             # 아는 배경을 따라가는 시간 상수 (조명 서서히 변화)
    fill_s: float = 0.25             # 모르는 곳(물체가 떠난 자리)을 채우는 시간
    absorb_s: float = 10.0           # 추적하지 않는 전경이 멈춰 있으면 배경으로 흡수되는 시간
    min_sigma: float = 4.0           # Lab 잡음 하한
    thr: float = 3.0                 # 이 표준편차 이상 다르면 전경 쪽
    # 무효 판정은 격자 칸 단위: 카메라 이동·조명 급변은 화면 전체에 고르게 퍼지고, 뒤쪽에서 오가는 사람은 몇 칸에 몰린다.
    # 픽셀 비율로 판정하면 사람 몇 명이 지나갈 때마다 꺼지고(그동안 사람까지 배경으로 다시 배움) 이득이 사라진다.
    grid: tuple[int, int] = (8, 6)   # (가로, 세로) 칸 수
    cell_changed: float = 0.15       # 칸 안 배경 픽셀 중 이 비율 이상이 바뀌면 '바뀐 칸'
    unstable_frac: float = 0.5       # 배경을 아는 칸 중 이 비율 이상이 바뀐 칸이면 이번 프레임 무효
    relearn_s: float = 0.6           # 무효가 이만큼 이어지면 배경을 다시 배운다
    settle_frames: int = 3           # 처음/다시 배운 뒤 이 프레임 수 동안은 신호를 내지 않는다
    # 깊이
    depth: bool = True
    depth_hz: float = 6.0
    depth_thr: float = 3.0           # 정렬 잔차 잡음(σ)의 몇 배 가까워지면 전경
    depth_min_sigma: float = 0.012   # 정렬 잔차 σ 하한 (배경 범위 대비)
    depth_max_age: float = 0.5       # 이보다 오래된 깊이는 쓰지 않는다 (초)


class SceneModel:
    """작업 해상도 프레임을 받아 전경 로그 오즈를 만든다. 스레드: update/forget/query 는 추적 스레드에서만,
    push_depth 는 아무 스레드에서나 (다음 update 가 가져간다)."""

    def __init__(self, cfg: SceneConfig | None = None) -> None:
        self.cfg = cfg or SceneConfig()
        self.mean: np.ndarray | None = None      # (h, w, 3) Lab float32
        self.var: np.ndarray | None = None       # (h, w) 결합 잔차 분산
        self.known: np.ndarray | None = None     # (h, w) 0..1
        self.size: tuple[int, int] | None = None  # 내부 (w, h)
        self.work: tuple[int, int] | None = None  # 작업 해상도 (w, h)
        self.t: float | None = None
        self.frames = 0
        self.valid = False
        self.invalid_since: float | None = None
        self.changed_frac = 0.0
        self.cells: tuple[np.ndarray, np.ndarray] | None = None
        self.shift = (0.0, 0.0)
        self.gain = (1.0, 0.0, 0.0)
        self.color_logit: np.ndarray | None = None
        self.shadow: np.ndarray | None = None
        # 깊이
        self.dmean: np.ndarray | None = None
        self.dknown: np.ndarray | None = None
        self.depth_logit: np.ndarray | None = None
        self.depth_t: float | None = None
        self._depth_in: tuple[np.ndarray, float] | None = None
        self._depth_lock = threading.Lock()
        self.depth_next = 0.0
        self.stats = {"relearn": 0, "invalid": 0, "depth": 0, "depth_skip": 0}
        self._cache: dict = {}

    # ------------------------------------------------------------ 입력
    def push_depth(self, depth: np.ndarray, t: float) -> None:
        """깊이 모델 결과 (아무 해상도, 클수록 가깝다)와 그 깊이를 계산한 프레임의 시각."""
        with self._depth_lock:
            self._depth_in = (depth, t)

    def depth_due(self, t: float) -> bool:
        if not (self.cfg.enabled and self.cfg.depth) or t < self.depth_next:
            return False
        self.depth_next = t + 1.0 / max(self.cfg.depth_hz, 0.1)
        return True

    def reset(self) -> None:
        self.mean = None
        self.frames = 0
        self.valid = False
        self.dmean = None
        self.depth_logit = None
        self._cache = {}

    def _small(self, bgr: np.ndarray) -> np.ndarray:
        h, w = bgr.shape[:2]
        sw = min(self.cfg.width, w)
        sh = max(1, round(h * sw / w))
        small = bgr if sw == w else cv2.resize(bgr, (sw, sh), interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(small.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)

    def _down(self, m: np.ndarray | None) -> np.ndarray | None:
        if m is None or self.size is None:
            return None
        if m.shape[::-1] == self.size:
            return m.astype(bool)
        return cv2.resize(m.astype(np.uint8), self.size, interpolation=cv2.INTER_AREA) > 0

    def forget(self, mask: np.ndarray) -> None:
        """새로 등록한 물체 밑을 '모름' 으로. 단, 지금 배경과 뚜렷이 다른 곳(물체를 방금 올려놓음)은 배경을 그대로 둔다."""
        if self.mean is None:
            return
        m = self._down(mask)
        if m is None:
            return
        m = cv2.dilate(m.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
        if self.color_logit is not None and self.valid:
            self.known[m & (self.color_logit < 1.0)] = 0.0
        else:
            self.known[m] = 0.0
        if self.dknown is not None:
            self.dknown[m] = 0.0
        self._cache = {}

    def update(self, bgr: np.ndarray, t: float, exclude: np.ndarray | None = None) -> None:
        """한 프레임 (작업 해상도 BGR). exclude = 배경으로 배우면 안 되는 곳 (추적 물체 + 손), 작업 해상도 bool."""
        if not self.cfg.enabled:
            return
        cfg = self.cfg
        lab = self._small(bgr)
        h, w = lab.shape[:2]
        self.work = (bgr.shape[1], bgr.shape[0])
        self._cache = {}
        if self.mean is None or self.mean.shape[:2] != (h, w):
            self.size = (w, h)
            self._init(lab, self._down(exclude))
            self.t = t
            return
        dt = 1 / 30 if self.t is None else min(0.5, max(1e-3, t - self.t))
        self.t = t
        ex = self._down(exclude)
        self._align(lab, ex)
        known = self.known > 0.5
        # 전역 밝기 보정: 배경으로 알고 이번에 제외되지 않은 곳에서 L 배율, a/b 이동의 중앙값
        ref = known if ex is None else known & ~ex
        sub = ref[::3, ::3]   # 중앙값은 솎은 표본으로 충분하다
        if sub.sum() > 60:
            ms, cs = self.mean[::3, ::3][sub], lab[::3, ::3][sub]
            ok = ms[:, 0] > 5
            g = float(np.median(cs[ok, 0] / ms[ok, 0])) if ok.sum() > 30 else 1.0
            da, db = (float(v) for v in np.median(cs[:, 1:] - ms[:, 1:], axis=0))
            self.gain = (float(np.clip(g, 0.3, 3.0)), da, db)
        gL, da, db = (np.float32(v) for v in self.gain)
        bL = self.mean[..., 0] * gL
        dL = lab[..., 0] - bL
        dA = lab[..., 1] - self.mean[..., 1] - da
        dB = lab[..., 2] - self.mean[..., 2] - db
        sq = dL * dL + np.float32(1.5) * (dA * dA + dB * dB)
        sig2 = self.var + np.float32(cfg.min_sigma ** 2)
        D = np.sqrt(sq / sig2)
        logit = np.clip(np.float32(1.5) * (D - np.float32(cfg.thr)), -3.0, 4.0)
        # 그림자: 어두워지기만 하고 색은 거의 그대로 → 약한 전경
        ratio = lab[..., 0] / np.maximum(bL, 1.0)
        chroma = np.sqrt(dA * dA + dB * dB)
        shadow = (ratio > 0.4) & (ratio < 0.95) & (chroma < 6.0 + 0.1 * np.abs(dL)) & (logit > 0)
        logit = np.where(shadow, np.minimum(logit, 0.5), logit)
        logit = np.where(known, logit, 0.0).astype(np.float32)
        self.shadow = shadow & known

        # 유효성: 배경으로 알던 곳(제외 영역 밖)이 넓게 바뀌었나
        n = int(ref.sum())
        self.changed_frac = self._changed_cells(logit > 1.0, ref) if n > 200 else 1.0
        self.frames += 1
        if self.changed_frac > cfg.unstable_frac:
            self.valid = False
            self.stats["invalid"] += 1
            if self.invalid_since is None:
                self.invalid_since = t
            elif t - self.invalid_since > cfg.relearn_s:
                self.stats["relearn"] += 1
                self._init(lab, ex)
                return
        else:
            self.invalid_since = None
            self.valid = self.frames >= cfg.settle_frames
        self.color_logit = logit

        # 학습 (선택적)
        learnable = np.ones((h, w), bool) if ex is None else ~ex
        bgl = learnable & (logit < 1.0)
        a_known = np.float32(dt / cfg.learn_s)
        a_fill = np.float32(min(1.0, dt / cfg.fill_s))
        if self.valid or self.frames < cfg.settle_frames:
            rate = np.where(known, a_known, a_fill) * bgl
            # 흡수: 추적하지 않는 전경이 오래 멈춰 있으면 배경이 된다
            rate += (learnable & ~bgl & known) * np.float32(dt / cfg.absorb_s)
            target = lab - np.array([0, da, db], np.float32)
            target[..., 0] = lab[..., 0] / max(gL, 1e-3)
            self.mean += rate[..., None] * (target - self.mean)
            self.var += rate * (np.minimum(sq, 400.0) - self.var)
            # '앎' 은 평균이 지금 값에 수렴했을 때만 올린다 (물체가 떠난 자리를 물체 색으로 굳히지 않게)
            up = bgl & (D < cfg.thr)
            self.known[up] = np.minimum(1.0, self.known[up] + 2 * a_fill)
        self._take_depth(ex)

    def _changed_cells(self, changed: np.ndarray, ref: np.ndarray) -> float:
        """배경을 아는 칸 중 '바뀐 칸' 비율. 칸 안 배경 픽셀이 10% 미만인 칸(물체·손이 덮은 칸)은 세지 않는다."""
        g = self.cfg.grid
        r = cv2.resize(ref.astype(np.float32), g, interpolation=cv2.INTER_AREA)
        c = cv2.resize((changed & ref).astype(np.float32), g, interpolation=cv2.INTER_AREA)
        ok = r > 0.1
        frac = np.where(ok, c / np.maximum(r, 1e-6), 0.0)
        self.cells = (frac.astype(np.float32), ok)   # 개발자 보기용: 칸마다 바뀐 비율, 배경을 아는 칸
        if not ok.any():
            return 1.0
        return float((frac[ok] > self.cfg.cell_changed).mean())

    def _init(self, lab: np.ndarray, ex: np.ndarray | None) -> None:
        h, w = lab.shape[:2]
        self.mean = lab.copy()
        self.var = np.full((h, w), self.cfg.min_sigma ** 2, np.float32)
        self.known = np.ones((h, w), np.float32)
        if ex is not None:
            self.known[ex] = 0.0
        self.frames = 0
        self.valid = False
        self.invalid_since = None
        self.color_logit = None
        self.shift = (0.0, 0.0)
        self.gain = (1.0, 0.0, 0.0)
        self._gray_ref = lab[..., 0].copy()
        self.dmean = None
        self.dknown = None
        self.depth_logit = None

    def _align(self, lab: np.ndarray, ex: np.ndarray | None) -> None:
        """카메라 미세 이동: 배경 L 과 현재 L 의 위상 상관으로 평행이동을 구해 배경을 옮긴다.
        움직이는 물체(무늬가 강하면 상관 봉우리를 만든다)는 가리고, 옮겼을 때 배경 차이가 실제로 줄 때만 받아들인다."""
        ref = self.mean[..., 0]
        cur = lab[..., 0]
        hide = self.known < 0.5
        if ex is not None:
            hide = hide | ex
        if hide.any():
            cur = np.where(hide, ref, cur)
        # 절반 해상도에서 상관 (카메라 흔들림은 넓은 영역의 움직임이라 충분하다)
        r2 = cv2.resize(ref, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        c2 = cv2.resize(cur.astype(np.float32), None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        win = getattr(self, "_win", None)
        if win is None or win.shape != r2.shape:
            win = cv2.createHanningWindow(r2.shape[::-1], cv2.CV_32F)
            self._win = win
        (sx, sy), resp = cv2.phaseCorrelate(r2, c2, win)
        sx, sy = 2 * sx, 2 * sy
        self.shift = (float(sx), float(sy))
        if resp < 0.05 or (abs(sx) < 0.35 and abs(sy) < 0.35) or abs(sx) > 0.15 * cur.shape[1] or abs(sy) > 0.15 * cur.shape[0]:
            return
        M = np.float32([[1, 0, sx], [0, 1, sy]])
        size = cur.shape[::-1]
        moved = cv2.warpAffine(ref, M, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        keep = ~hide
        keep[:4], keep[-4:], keep[:, :4], keep[:, -4:] = False, False, False, False
        if keep.sum() < 200:
            return
        before = float(np.median(np.abs(cur[keep] - ref[keep])))
        after = float(np.median(np.abs(cur[keep] - moved[keep])))
        if after > 0.8 * before:
            return
        self.mean = cv2.warpAffine(self.mean, M, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        self.var = cv2.warpAffine(self.var, M, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        self.known = cv2.warpAffine(self.known, M, size, flags=cv2.INTER_LINEAR, borderValue=0)
        if self.dmean is not None:
            self.dmean = cv2.warpAffine(self.dmean, M, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            self.dknown = cv2.warpAffine(self.dknown, M, size, flags=cv2.INTER_LINEAR, borderValue=0)
        if self.depth_logit is not None:
            self.depth_logit = cv2.warpAffine(self.depth_logit, M, size, flags=cv2.INTER_LINEAR, borderValue=0)

    # ------------------------------------------------------------ 깊이
    def _take_depth(self, ex: np.ndarray | None) -> None:
        with self._depth_lock:
            item, self._depth_in = self._depth_in, None
        if item is None or self.size is None:
            return
        depth, t = item
        d = cv2.resize(depth.astype(np.float32), self.size, interpolation=cv2.INTER_AREA)
        cfg = self.cfg
        if self.dmean is None or self.dmean.shape != d.shape:
            self.dmean = d.copy()
            self.dknown = np.ones_like(d) if self.known is None else (self.known > 0.5).astype(np.float32)
            self.depth_logit = None
            self.depth_t = t
            return
        # 정렬: 색으로 배경이고 깊이 배경도 아는 곳에서 d ≈ a·dmean + b (잔차 큰 점을 버리며 두 번)
        sel = (self.dknown > 0.5)
        if self.color_logit is not None:
            sel &= self.color_logit < 0.0
        if ex is not None:
            sel &= ~ex
        x, y = self.dmean[sel], d[sel]
        if x.size < 300 or float(np.ptp(x)) < 1e-3:
            self.stats["depth_skip"] += 1
            return
        a, b = 1.0, 0.0
        keep = np.ones(x.size, bool)
        for _ in range(3):
            A = np.stack([x[keep], np.ones(int(keep.sum()))], 1)
            sol, *_ = np.linalg.lstsq(A, y[keep], rcond=None)
            a, b = float(sol[0]), float(sol[1])
            r = y - (a * x + b)
            s = 1.4826 * float(np.median(np.abs(r[keep]))) + 1e-6
            keep = np.abs(r) < 2.5 * s
        if a <= 0.05:
            self.stats["depth_skip"] += 1
            return
        aligned = (d - b) / a
        rng = float(np.percentile(self.dmean[sel], 98) - np.percentile(self.dmean[sel], 2)) + 1e-6
        sigma = max(s / a, cfg.depth_min_sigma * rng)
        near = (aligned - self.dmean) / sigma
        dl = np.clip(1.2 * (near - cfg.depth_thr), -2.0, 3.0)
        # 멀어진 곳(물체가 떠난 자리)과 잡음 수준은 '배경' 근거 (단, 깊이 배경을 아는 곳만)
        self.depth_logit = np.where(self.dknown > 0.5, dl, 0.0).astype(np.float32)
        self.depth_t = t
        self.stats["depth"] += 1
        # 깊이 배경 학습: 색도 깊이도 배경인 곳, 모르는 곳은 빨리 채운다.
        # 색이 확실히 그대로인 곳은 깊이가 달라 보여도 배경으로 배운다 (정렬이 안 맞는 화면 끝·모델 잡음이 굳지 않게).
        learn = (np.abs(near) < cfg.depth_thr)
        if self.color_logit is not None:
            learn &= self.color_logit < 1.0
            learn |= self.color_logit < -1.5
        if ex is not None:
            learn &= ~ex
        rate = np.where(self.dknown > 0.5, 0.2, 1.0) * learn
        self.dmean += rate * (aligned - self.dmean)
        self.dknown = np.where(learn, 1.0, self.dknown).astype(np.float32)

    # ------------------------------------------------------------ 출력
    def logit(self, t: float | None = None, depth_weight: float = 1.0) -> np.ndarray | None:
        """작업 해상도 전경 로그 오즈 (색 + 깊이). 무효면 None. depth_weight 는 쓰는 쪽이 움직임에 맞춰 준다."""
        if not self.cfg.enabled or not self.valid or self.color_logit is None or self.work is None:
            return None
        key = ("logit", round(depth_weight, 2))
        if key in self._cache:
            return self._cache[key]
        lg = self.color_logit
        dl = self.depth_logit
        age = None if self.depth_t is None or t is None else t - self.depth_t
        if dl is not None and depth_weight > 0 and age is not None and age <= self.cfg.depth_max_age:
            w = np.float32(depth_weight)
            # 깊이는 '가까워짐' 만 더한다. 납작한 물체(종이·카드)는 깊이로 안 보이므로 '배경 그대로' 를 근거로 쓰면
            # 색으로 분명히 보이는 물체까지 지운다. 대신 그림자·약한 색 변화(반사·조명)는 깊이가 그대로면 배경으로 돌린다.
            # 색이 이미 분명한 전경(≥ 1.5)은 색만 쓴다: 깊이가 6Hz 로 도착할 때마다 경계가 흔들리지 않게.
            # 색이 '배경' 이라고 해도 깊이가 솟았다고 하면 더한다 (책상과 같은 색의 물체)
            # (그때는 색의 '배경' 근거를 버리고 깊이로 판단한다: 같은 색이면 색 차이는 아무것도 말해 주지 않는다)
            near = (dl > 0) & (lg < 1.5)
            fused = np.where(near, np.maximum(lg, 0) + w * dl, lg)
            weak = (self.shadow | ((lg > 0) & (lg < 2.0))) & (dl < -1.0)
            fused = np.where(weak, np.minimum(fused, -0.5 * w), fused)
            lg = np.clip(fused, -4.0, 5.0).astype(np.float32)
        out = cv2.resize(lg, self.work, interpolation=cv2.INTER_LINEAR)
        self._cache[key] = out
        return out

    def depth_age(self, t: float) -> float | None:
        return None if self.depth_t is None else t - self.depth_t

    def info(self) -> dict:
        return {"valid": self.valid, "changed": round(self.changed_frac, 3), "shift": [round(v, 2) for v in self.shift],
                "gain": round(self.gain[0], 3), "depth": self.depth_logit is not None, **self.stats}
