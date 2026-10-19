"""물체 커서 기준점(anchor): 분할 영역이 흔들려도 커서가 흔들리지 않게 하는 점 하나.

문제: 물체를 손으로 쥐면 분할(segmentation) 영역이 손 때문에 늘었다 줄었다 하고, 그 영역의 중심·크기로 정한 커서가 같이 떤다.
해결: 물체마다 '바닥에 가까운 가장 가운데 아랫부분' 한 점을 기준점으로 잡고, 영상에서 직접 따라간다.
- 아랫부분은 손이 덜 닿고(장애물이 적고) 실제 바닥 위 위치를 반영한다.
- 시작: 마스크의 아래쪽 띠(높이의 일부)에서 x 의 중앙값, y 는 맨 아랫행에서 조금 안쪽.
- 추적: 기준점 둘레(물체 아래 가운데)의 모서리 특징점 여럿을 Lucas-Kanade 광학 흐름으로 따라가고 (앞뒤 오차 검사), 그 점들의 움직임에서
  이동·확대·회전(유사변환)을 구해 기준점을 옮긴다. 점이 하나뿐이면 곧은 아랫 모서리를 따라 미끄러지지만(조리개 문제) 여러 모서리 점이
  있으면 모서리 방향의 움직임도 정해진다. 분할 영역은 따라가는 데 쓰지 않는다.
- 보정: 손이 마스크를 거의 가리지 않을 때(신뢰)만, 마스크의 아래-가운데 측정이 추적점 가까이에 있으면 천천히 당겨 드리프트를 지운다.
  손이 쥐는 동안에는 당기지 않고 광학 흐름만 믿는다. 흐름을 오래 못 믿거나 크게 어긋난 채 이어지면 마스크에서 다시 찍는다.
순수 로직(OpenCV·NumPy). 작업 해상도에서 계산하고 원본 좌표로 돌려준다.
"""
from __future__ import annotations
from dataclasses import dataclass
import cv2
import numpy as np


SCALE_ALPHA = 0.3   # 프레임당 크기 출력 필터 (30fps 에서 시상수 약 0.1초)


@dataclass
class AnchorConfig:
    work_width: int = 800
    band: float = 0.20          # 마스크 높이 대비, 맨 아래에서 위로 이 비율의 띠에서 x 중앙값을 구한다
    inset: float = 0.10         # 맨 아랫행에서 안쪽(위)으로 이 비율 (물체 높이 대비)
    min_h: float = 8.0          # 이보다 작은 마스크(작업 해상도 px)는 측정하지 않는다
    roi_w: float = 0.40         # 특징점 영역: 기준점 둘레 x 범위 (물체 너비 대비, 한쪽 반지름)
    roi_up: float = 0.90        # 기준점 위로 (물체 높이 대비). 아래쪽은 마스크 안만
    max_pts: int = 40
    min_pts: int = 8            # 이보다 적으면 다시 찾는다
    redetect_every: int = 20    # 점이 충분해도 이 간격(프레임)마다 부족하면 보충
    win: int = 21               # LK 창
    fb_err: float = 1.0         # 앞뒤 흐름 오차 한도 (px)
    min_inliers: int = 5
    resid_tol: float = 1.5      # 유사변환 잔차 한도 (px)
    max_step: float = 0.5       # 한 프레임 이동 한도 (물체 높이 대비)
    miss_frames: int = 6        # 흐름을 못 믿는 프레임이 이만큼 이어지면 마스크에서 다시 찍는다
    pull: float = 0.05          # 마스크 측정으로 당기는 비율 (신뢰할 때만, 프레임당)
    gate: float = 0.30          # 측정이 추적점에서 이 이상(높이 대비) 떨어지면 당기지 않는다
    far_frames: int = 45        # 신뢰 구간에서 이만큼 계속 크게 어긋나 있으면 마스크에서 다시 찍는다


@dataclass
class AnchorState:
    valid: bool = False
    xy: tuple[float, float] | None = None        # 원본 해상도 px
    source: str = ""                             # init | flow | held | reinit
    scale: float | None = None                   # 광학 흐름으로 추정한 크기 (등록 대비, 분할과 무관)
    n: int = 0                                   # 이번 프레임에 쓴 특징점 수
    trusted: bool = False                        # 이번 프레임에 마스크 측정으로 보정했는가


def bottom_center(mask: np.ndarray, band: float, inset: float, min_h: float) -> tuple[float, float, float, float] | None:
    """마스크의 아래-가운데 점 (x, y, 물체 높이, 물체 너비). 작업 해상도 마스크. 너무 작으면 None."""
    rows = np.flatnonzero(mask.sum(1) >= 2)
    if rows.size == 0:
        return None
    y_top, y_bot = float(rows[0]), float(rows[-1])
    h = y_bot - y_top
    if h < min_h:
        return None
    lo = int(max(y_top, y_bot - band * h))
    ys, xs = np.nonzero(mask[lo:int(y_bot) + 1])
    if xs.size < 4:
        return None
    cols = np.flatnonzero(mask.any(0))
    return float(np.median(xs)), y_bot - inset * h, h, float(cols[-1] - cols[0])


class ObjectAnchor:
    def __init__(self, cfg: AnchorConfig | None = None) -> None:
        self.cfg = cfg or AnchorConfig()
        self.reset()

    def reset(self) -> None:
        self.p: np.ndarray | None = None            # 작업 해상도
        self.h = 0.0                                # 물체 높이·너비 (작업 해상도 px): 처음 잰 값 × 흐름으로 잰 크기 변화 (분할 영역 크기를 따라가지 않는다)
        self.w = 0.0
        self.h0 = self.w0 = 0.0
        self.lrel = 0.0                             # 처음 이후 흐름으로 잰 log 크기 변화
        self.consistent = 0                         # 마스크 크기가 기대와 맞는 연속 프레임 수
        self.pts = np.zeros((0, 2), np.float32)
        self.prev: np.ndarray | None = None
        self.miss = 0
        self.far = 0
        self.age = 0
        self.ls_s: float | None = None              # ls 를 한 번 거른 값 (출력용: 프레임마다의 흐름 크기 잡음을 누른다)
        self.ls: float | None = None                # 광학 흐름으로 추정한 log 크기 (분할과 무관, 느리게 포즈 크기로 보정)
        self.generation = 0                         # 점을 새로 찍을 때마다 +1 (커서 기준을 새로 시작해 점프를 막는다)
        self.state = AnchorState()

    def rebase(self, mask: np.ndarray | None, tol: float = 0.12) -> bool:
        """가만히 놓인 물체: 기준점이 마스크의 바닥 아래-가운데에서 물체 높이의 tol 배 넘게 벗어나 있으면 다음 update 에서
        그 자리로 다시 찍게 한다 (흔들거나 뒤집는 동안 밀려난 점을 바닥으로 되돌림). 세대는 이어서 올려 커서 기준도 새로 시작한다.
        mask 는 작업 해상도 bool. 다시 찍기로 했으면 True."""
        if self.p is None or mask is None:
            return False
        meas = bottom_center(mask, self.cfg.band, self.cfg.inset, self.cfg.min_h)
        if meas is None or np.hypot(self.p[0] - meas[0], self.p[1] - meas[1]) <= tol * max(meas[2], 1.0):
            return False
        gen, ls = self.generation, self.ls
        self.reset()
        self.generation, self.ls = gen, ls
        return True

    # ------------------------------------------------------------------
    def update(self, gray: np.ndarray, mask: np.ndarray | None, visible: bool, trust_mask: bool,
               full_size: tuple[int, int], pose_scale: float | None = None) -> AnchorState:
        """gray: 작업 해상도 그레이, mask: 작업 해상도 bool 또는 None, full_size: 원본 (w, h).
        pose_scale: 트래커가 낸 크기(등록 대비). 크기 추정의 시작값이고, 마스크를 믿을 때 천천히 맞춘다."""
        cfg = self.cfg
        sx = full_size[0] / gray.shape[1]
        meas = bottom_center(mask, cfg.band, cfg.inset, cfg.min_h) if (visible and mask is not None) else None
        src, trusted = "held", False
        if self.p is None:
            if meas is None:
                self.prev = gray
                return self.state
            self._init(gray, mask, meas, pose_scale)
            src = "init"
        elif visible:
            ok = self._flow(gray)
            if ok:
                src, self.miss = "flow", 0
                self.h, self.w = self.h0 * float(np.exp(self.lrel)), self.w0 * float(np.exp(self.lrel))
            else:
                self.miss += 1
                if self.miss >= cfg.miss_frames and meas is not None:
                    self._init(gray, mask, meas, pose_scale)
                    src = "reinit"
            if src == "flow" and meas is not None:
                trusted = self._fuse(meas, trust_mask and self._mask_consistent(meas))
                if self.far >= cfg.far_frames:
                    self._init(gray, mask, meas, pose_scale)
                    src = "reinit"
            if src == "flow" and trust_mask and pose_scale and self.ls is not None:
                self.ls += 0.03 * (float(np.log(pose_scale)) - self.ls)      # 마스크를 믿을 때만 천천히 포즈 크기로
            if src != "reinit":
                self._refill(gray, mask)
        if self.ls is not None:
            self.ls_s = self.ls if self.ls_s is None or src in ("init", "reinit") else self.ls_s + SCALE_ALPHA * (self.ls - self.ls_s)
        self.prev = gray
        if self.p is None:
            return self.state
        self.state = AnchorState(True, (float(self.p[0] * sx), float(self.p[1] * sx)), src,
                                 None if self.ls_s is None else float(np.exp(self.ls_s)), len(self.pts), trusted)
        return self.state

    # ------------------------------------------------------------------
    def _init(self, gray: np.ndarray, mask: np.ndarray | None, meas: tuple[float, float, float, float],
              pose_scale: float | None = None) -> None:
        self.generation += 1
        if pose_scale:
            self.ls = float(np.log(pose_scale))
        self.p = np.array([meas[0], meas[1]], np.float64)
        self.h, self.w = self.h0, self.w0 = meas[2], meas[3]
        self.lrel = 0.0
        self.consistent = 0
        self.pts = np.zeros((0, 2), np.float32)
        self.miss = self.far = self.age = 0
        self._refill(gray, mask, force=True)

    def _roi(self, mask: np.ndarray | None, shape: tuple[int, int]) -> np.ndarray:
        """특징점을 찾을 영역: 기준점 둘레 (아래 가운데). 마스크가 있으면 마스크 안쪽만."""
        cfg = self.cfg
        H, W = shape
        assert self.p is not None
        half = max(cfg.roi_w * self.w, 6.0)
        x0, x1 = int(max(self.p[0] - half, 0)), int(min(self.p[0] + half, W))
        y0, y1 = int(max(self.p[1] - cfg.roi_up * self.h, 0)), int(min(self.p[1] + 0.05 * self.h + 2, H))
        roi = np.zeros(shape, np.uint8)
        roi[y0:y1, x0:x1] = 1
        if mask is not None:
            inner = cv2.erode(mask.astype(np.uint8), np.ones((3, 3), np.uint8))
            roi &= inner if inner.any() else mask.astype(np.uint8)
        return roi

    def _refill(self, gray: np.ndarray, mask: np.ndarray | None, force: bool = False) -> None:
        cfg = self.cfg
        self.age += 1
        if not force and len(self.pts) >= cfg.min_pts and self.age % cfg.redetect_every:
            return
        if self.p is None or len(self.pts) >= cfg.max_pts:
            return
        roi = self._roi(mask, gray.shape)
        if int(roi.sum()) < 20:
            return
        new = cv2.goodFeaturesToTrack(gray, cfg.max_pts - len(self.pts), 0.01, 4, mask=roi, blockSize=5)
        if new is None:
            return
        new = new.reshape(-1, 2).astype(np.float32)
        if len(self.pts):
            keep = np.array([np.min(np.linalg.norm(self.pts - q, axis=1)) > 4 for q in new])
            new = new[keep]
        self.pts = np.vstack([self.pts, new]) if len(new) else self.pts

    def _flow(self, gray: np.ndarray) -> bool:
        """점들을 따라가 유사변환(이동·확대·회전)을 구하고 기준점을 옮긴다. 믿을 수 없으면 False (아무것도 바꾸지 않는다)."""
        cfg = self.cfg
        if self.prev is None or self.prev.shape != gray.shape or self.p is None or len(self.pts) < cfg.min_inliers:
            return False
        p0 = self.pts.reshape(-1, 1, 2)
        crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 20, 0.01)
        p1, st, _ = cv2.calcOpticalFlowPyrLK(self.prev, gray, p0, None, winSize=(cfg.win, cfg.win), maxLevel=3, criteria=crit)
        if p1 is None:
            return False
        pb, stb, _ = cv2.calcOpticalFlowPyrLK(gray, self.prev, p1, None, winSize=(cfg.win, cfg.win), maxLevel=3, criteria=crit)
        if pb is None:
            return False
        fb = np.linalg.norm((pb - p0).reshape(-1, 2), axis=1)
        ok = (st.ravel() == 1) & (stb.ravel() == 1) & (fb < cfg.fb_err)
        if int(ok.sum()) < cfg.min_inliers:
            self.pts = np.zeros((0, 2), np.float32)
            return False
        a, b = self.pts[ok].astype(np.float64), p1.reshape(-1, 2)[ok].astype(np.float64)
        # 유사변환 b ≈ s·R(a - ca) + cb 를 최소제곱으로 구하고 잔차가 큰 점을 한 번 버린 뒤 다시 구한다
        for _ in range(2):
            ca, cb = a.mean(0), b.mean(0)
            A, B = a - ca, b - cb
            den = float((A * A).sum())
            if den < 1e-6:
                return False
            c = float((A[:, 0] * B[:, 0] + A[:, 1] * B[:, 1]).sum()) / den     # s·cosθ
            s_ = float((A[:, 0] * B[:, 1] - A[:, 1] * B[:, 0]).sum()) / den    # s·sinθ
            R = np.array([[c, -s_], [s_, c]])
            resid = np.linalg.norm(B - A @ R.T, axis=1)
            good = resid < max(cfg.resid_tol, 2.5 * float(np.median(resid)))
            if good.all() or good.sum() < cfg.min_inliers:
                break
            a, b = a[good], b[good]
        scale = float(np.hypot(c, s_))
        if not 0.8 < scale < 1.25:
            return False
        newp = cb + R @ (self.p - ca)
        if float(np.linalg.norm(newp - self.p)) > cfg.max_step * max(self.h, 1.0):
            return False                 # 한 프레임에 너무 멀리: 믿지 않는다
        self.p = newp
        self.pts = b.astype(np.float32)
        self.lrel += float(np.log(scale))
        if self.ls is not None:
            self.ls += float(np.log(scale))
        return True

    def _mask_consistent(self, meas: tuple[float, float, float, float]) -> bool:
        """분할 영역의 높이·너비가 기대(처음 크기 × 흐름으로 잰 크기 변화)와 맞는가. 손이 쥐어 영역이 늘거나 잘리면 맞지 않는다 —
        손 인식(가림 처리)이 꺼져 있어도 영역 크기로 '지금 영역을 믿으면 안 된다'는 것을 알 수 있다. 3프레임 연속 맞아야 믿는다."""
        ok = abs(meas[2] / max(self.h, 1.0) - 1.0) < 0.15 and abs(meas[3] / max(self.w, 1.0) - 1.0) < 0.25
        self.consistent = self.consistent + 1 if ok else 0
        return self.consistent >= 3

    def _fuse(self, meas: tuple[float, float, float, float], trust: bool) -> bool:
        cfg = self.cfg
        if not trust:
            self.far = 0
            return False                 # 손이 쥐는 동안: 분할 영역으로는 움직이지 않는다
        err = np.array([meas[0], meas[1]]) - self.p
        if float(np.linalg.norm(err)) <= cfg.gate * max(self.h, 1.0):
            self.p = self.p + cfg.pull * err
            self.far = 0
            return True
        self.far += 1
        return False
