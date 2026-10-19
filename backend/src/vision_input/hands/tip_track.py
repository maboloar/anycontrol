"""검지·중지 끝점(손끝) 추적: 손 랜드마크로 점을 찍고, 그 뒤에는 점 주변 몇 픽셀만 직접 따라간다. 순수 로직.

물체를 쥐고 손가락을 내리면(손을 오므리면) 손 랜드마크 엔진은 손가락 위치를 놓친다. 그래서 펜촉 추적처럼
'점 하나와 그 주변'만 영상에서 직접 추적한다 (분할이 필요 없다).

- 시작·보정(anchor): 손가락이 곧게 들려 랜드마크를 믿을 수 있을 때만 점을 찍거나 천천히 당겨 맞춘다.
  손가락이 내려가 랜드마크가 틀리기 시작하면 더는 믿지 않는다.
- 추적: 점 주변 3×3 격자를 Lucas-Kanade 광학 흐름으로 따라가고(앞뒤 오차 검사), 점 주변 패치를 템플릿(NCC)으로
  확인·미세 보정한다. 둘 다 못 믿으면 '못 찾음'으로 표시한다 (점을 지어내지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .detector import Hand

# (이름: 뿌리, 끝)
TIPS = {"index": (5, 8), "middle": (9, 12)}


@dataclass
class TipConfig:
    work_width: int = 800
    patch_r: int = 9               # 템플릿 반지름 (작업 해상도 px)
    search_r: int = 6              # 템플릿 탐색 반지름
    anchor_h: float = 0.40         # 이 이상 곧게 들려야 랜드마크를 믿는다 (손바닥 축 방향 길이 / 손 크기)
    anchor_pull: float = 0.35      # 믿을 수 있는 랜드마크로 끌어당기는 비율 (드리프트 제거)
    reinit_dist: float = 0.35      # 추적점과 랜드마크가 이 이상(손 크기) 떨어지면 새로 찍는다
    fb_err: float = 1.2            # LK 앞뒤 오차 한도 (px)
    min_inliers: int = 4
    ncc_ok: float = 0.6
    ncc_floor: float = 0.25        # 이보다 낮은 모양 일치가 이어지면 (배경에 남은 것으로 보고) 잃은 것으로 처리
    low_frames: int = 8
    miss_frames: int = 4           # 연속 이만큼 못 믿으면 '못 찾음'
    max_jump: float = 0.6          # 한 프레임 이동 한도 (손 크기)
    template_blend: float = 0.08   # 확실할 때 템플릿을 서서히 갱신
    skin_tol: float = 14.0         # 살색(Lab a,b) 모델에서 이만큼 벗어난 점이 이어지면 손에서 벗어난 것
    skin_frames: int = 6
    snap_dist: float = 0.35        # 분할 마스크 밖의 점을 마스크 쪽으로 당겨 맞출 수 있는 최대 거리 (손 크기)


@dataclass
class Tip:
    valid: bool = False
    xy: np.ndarray = field(default_factory=lambda: np.zeros(2))   # 작업 해상도 px
    conf: float = 0.0
    anchored_t: float = -1e9       # 마지막으로 랜드마크를 믿고 보정한 시각
    template: np.ndarray | None = None
    miss: int = 0
    low: int = 0                   # 모양(NCC)이 연속으로 크게 달라진 프레임 수
    offskin: int = 0               # 살색이 아닌 곳에 있는 연속 프레임 수
    off_mask: int = 0              # 분할 마스크 밖에 있다고 확인된 연속 횟수


@dataclass
class TipFrame:
    t: float
    size: tuple[int, int]          # 작업 해상도 (w, h)
    tips: dict[str, Tip]
    hand_size: float               # 마지막으로 본 손 크기 (px, 작업 해상도). 0 이면 모름
    axis: np.ndarray               # 손목→가운뎃손가락 뿌리 방향 단위벡터 (px 좌표)
    landmark_fresh: bool           # 이번 프레임에 새 랜드마크 관측이 있었다


class TipTracker:
    def __init__(self, cfg: TipConfig | None = None) -> None:
        self.cfg = cfg or TipConfig()
        self.reset()

    def reset(self) -> None:
        self.tips = {n: Tip() for n in TIPS}
        self.prev: np.ndarray | None = None
        self.hand_size = 0.0
        self.axis = np.array([0.0, -1.0])
        self.last_obs: float | None = None
        self.small: np.ndarray | None = None      # 작업 해상도 BGR (살색 확인용)
        self.skin: np.ndarray | None = None        # 살색 모델 Lab (a, b) 평균
        self.skin_std = 6.0

    # ------------------------------------------------------------------
    def update(self, bgr: np.ndarray, t: float, hand: Hand | None, hand_t: float | None = None) -> TipFrame:
        """bgr: 원본 프레임. hand: 지금 쓸 손 (없으면 None). hand_t: 그 관측 시각 (같은 관측을 두 번 쓰지 않으려고)."""
        c = self.cfg
        h0, w0 = bgr.shape[:2]
        scale = c.work_width / w0 if w0 > c.work_width else 1.0
        w, h = (int(round(w0 * scale)), int(round(h0 * scale))) if scale < 1.0 else (w0, h0)
        small = cv2.resize(bgr, (w, h), interpolation=cv2.INTER_AREA) if scale < 1.0 else bgr
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        if self.prev is not None and self.prev.shape != gray.shape:
            self.reset()
        self.small = small
        if self.prev is not None:
            for tip in self.tips.values():
                if tip.valid:
                    self._track(tip, self.prev, gray)
                    if tip.valid:
                        self._check_skin(tip)
        fresh = False
        if hand is not None and (hand_t is None or hand_t != self.last_obs):
            self.last_obs = hand_t
            fresh = self._anchor(hand, gray, t, w, h)
        self.prev = gray
        return TipFrame(t, (w, h), self.tips, self.hand_size, self.axis.copy(), fresh)

    # ------------------------------------------------------------------
    def _radius(self) -> float:
        return float(np.clip(0.16 * self.hand_size, 6, 18)) if self.hand_size > 0 else 10.0

    def _patch(self, gray: np.ndarray, p: np.ndarray) -> np.ndarray | None:
        r = self.cfg.patch_r
        x, y = int(round(p[0])), int(round(p[1]))
        if x - r < 0 or y - r < 0 or x + r >= gray.shape[1] or y + r >= gray.shape[0]:
            return None
        return gray[y - r:y + r + 1, x - r:x + r + 1]

    def _chroma(self, p: np.ndarray, r: int = 4) -> np.ndarray | None:
        """점 주변의 평균 색 (Lab 의 a, b). 밝기를 빼서 그림자·조명에 덜 민감하다."""
        if self.small is None:
            return None
        x, y = int(round(p[0])), int(round(p[1]))
        h, w = self.small.shape[:2]
        if x - r < 0 or y - r < 0 or x + r >= w or y + r >= h:
            return None
        lab = cv2.cvtColor(self.small[y - r:y + r + 1, x - r:x + r + 1], cv2.COLOR_BGR2LAB)
        return lab.reshape(-1, 3)[:, 1:].astype(np.float32).mean(0)

    def set_skin(self, ab_pixels: np.ndarray) -> None:
        """분할 마스크 안 픽셀의 (a, b) 로 살색 모델을 새로 만든다 (중앙값 + 퍼짐)."""
        if len(ab_pixels) < 30:
            return
        med = np.median(ab_pixels, axis=0)
        mad = float(np.median(np.linalg.norm(ab_pixels - med, axis=1)))
        self.skin, self.skin_std = med, max(3.0, 1.4826 * mad)

    def _check_skin(self, tip: Tip) -> None:
        if self.skin is None:
            return
        ch = self._chroma(tip.xy)
        if ch is None:
            return
        tol = max(self.cfg.skin_tol, 3.0 * self.skin_std)
        if float(np.linalg.norm(ch - self.skin)) > tol:
            tip.offskin += 1
            if tip.offskin >= self.cfg.skin_frames:   # 배경·허공으로 벗어난 점은 버린다
                tip.valid = False
        else:
            tip.offskin = 0

    def _track(self, tip: Tip, prev: np.ndarray, gray: np.ndarray) -> None:
        c = self.cfg
        step = self._radius() / 1.6
        offs = np.array([(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)], np.float32) * step
        p0 = (tip.xy.astype(np.float32) + offs).reshape(-1, 1, 2)
        lk = dict(winSize=(15, 15), maxLevel=3, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 20, 0.03))
        p1, st, _ = cv2.calcOpticalFlowPyrLK(prev, gray, p0, None, **lk)
        p0r, st2, _ = cv2.calcOpticalFlowPyrLK(gray, prev, p1, None, **lk)
        ok = (st.ravel() == 1) & (st2.ravel() == 1) & (np.linalg.norm((p0r - p0).reshape(-1, 2), axis=1) < c.fb_err)
        new = None
        lk_conf = 0.0
        if int(ok.sum()) >= c.min_inliers:
            flow = (p1 - p0).reshape(-1, 2)[ok]
            new = tip.xy + np.median(flow, axis=0)
            lk_conf = float(ok.sum()) / len(ok)
        score = 0.0
        if tip.template is not None and float(tip.template.std()) > 3.0:
            guess = new if new is not None else tip.xy
            r, s = c.patch_r, c.search_r
            x, y = int(round(guess[0])), int(round(guess[1]))
            x0, y0, x1, y1 = x - r - s, y - r - s, x + r + s + 1, y + r + s + 1
            if x0 >= 0 and y0 >= 0 and x1 <= gray.shape[1] and y1 <= gray.shape[0]:
                res = cv2.matchTemplate(gray[y0:y1, x0:x1], tip.template, cv2.TM_CCOEFF_NORMED)
                _, score, _, loc = cv2.minMaxLoc(res)
                score = float(score)
                ncc_p = np.array([x - s + loc[0], y - s + loc[1]], float)
                if score >= c.ncc_ok:
                    new = ncc_p if new is None else 0.4 * new + 0.6 * ncc_p
        if new is None or (score < c.ncc_ok and lk_conf == 0.0):
            tip.miss += 1
            if tip.miss >= c.miss_frames:
                tip.valid = False
            return
        if self.hand_size > 0 and float(np.linalg.norm(new - tip.xy)) > c.max_jump * self.hand_size:
            tip.miss += 1
            if tip.miss >= c.miss_frames:
                tip.valid = False
            return
        if tip.template is not None and float(tip.template.std()) > 3.0 and score < c.ncc_floor:
            tip.low += 1
            if tip.low >= c.low_frames:   # LK 는 배경의 질감도 따라가므로, 점 주변 모양이 사라졌는지는 템플릿으로 확인한다
                tip.valid = False
                return
        else:
            tip.low = 0
        tip.miss = 0
        tip.xy = new
        tip.conf = float(np.clip(0.5 * lk_conf + 0.5 * max(score, 0.0), 0.0, 1.0))
        patch = self._patch(gray, new)
        if patch is None:
            tip.valid = False
        elif tip.conf > 0.7 and tip.template is not None:
            tip.template = ((1 - c.template_blend) * tip.template + c.template_blend * patch).astype(np.uint8)

    def _anchor(self, hand: Hand, gray: np.ndarray, t: float, w: int, h: int) -> bool:
        """믿을 수 있는 랜드마크로 점을 찍거나 당겨 맞춘다. 손가락이 곧게 들린 손가락만."""
        c = self.cfg
        if hand.score < 0.5:
            return False
        p = hand.points.astype(np.float64) * [w, h]
        axis = p[9] - p[0]
        size = float(np.linalg.norm(axis))
        if size < 8:
            return False
        axis /= size
        self.hand_size = size if self.hand_size <= 0 else 0.7 * self.hand_size + 0.3 * size
        self.axis = axis
        for name, (mcp, tip_i) in TIPS.items():
            vec = p[tip_i] - p[mcp]
            raised = float(vec @ axis) / size >= c.anchor_h and float(np.linalg.norm(vec)) / size <= 1.6
            if not raised:
                continue
            tip = self.tips[name]
            L = p[tip_i]
            far = tip.valid and float(np.linalg.norm(tip.xy - L)) > c.reinit_dist * size
            if far and tip.conf >= 0.4:
                continue  # 믿을 만한 추적을 틀릴 수 있는 랜드마크(오므린 손의 환각)로 옮기지 않는다
            if not tip.valid or far:
                patch = self._patch(gray, L)
                if patch is None:
                    continue
                tip.xy, tip.template, tip.valid, tip.miss, tip.conf, tip.low = L.copy(), patch.copy(), True, 0, 0.6, 0
            else:
                tip.xy = tip.xy + c.anchor_pull * (L - tip.xy)
                patch = self._patch(gray, tip.xy)
                if patch is not None and tip.template is not None:
                    tip.template = (0.8 * tip.template + 0.2 * patch).astype(np.uint8)
            tip.anchored_t = t
            tip.offskin = 0
            ch = self._chroma(tip.xy)
            if ch is not None and self.skin is None:   # 분할 결과가 없을 때의 임시 모델: 믿을 수 있는 손끝 색
                self.skin, self.skin_std = ch, 5.0
        return True
