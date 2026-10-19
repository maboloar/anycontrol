"""펜 뼈대: 펜은 곧은 막대라는 사실로 가려진 부분을 채운다.

손이 펜의 가운데를 쥐면 마스크가 둘로 갈라지고, 펜촉이나 반대쪽 끝을 가리면 마스크가 짧아져 '보이는 끝'이 진짜 끝이 아니게 된다.
이 모듈은 마스크에서 직선(뼈대)을 다시 맞추고, 길이를 기억해 둔 값으로 보이지 않는 부분을 채워 양 끝(펜촉·반대쪽 끝)과
보이는/가려진 구간을 돌려준다.

1. 직선 맞추기: 마스크 픽셀의 주축(PCA)을 잡고, 축에서 멀리 떨어진 덩어리(손가락 조각)는 버리고 한 번 더 맞춘다.
2. 축 방향 단면: 축을 따라 1px 칸마다 마스크가 있는 곳을 구해 '보이는 구간'을 만든다. 구간 사이의 틈이 펜 굵기보다 크면 가려진 구간이다.
3. 끝 정하기: 기억한 길이(강체)와 비교한다.
   - 보이는 길이가 충분하면 양 끝이 다 보이는 것 (가운데만 가려졌을 수 있다).
   - 짧으면 어느 쪽 끝이 가려졌는지 가린 물체(손)의 위치 → 포즈로 예측한 끝 위치 → 끝 색 기억 → 직전 뼈대 순으로 정한다.
4. 끝 색 기억: 가려지지 않은 온전한 모습에서 펜촉 쪽·반대쪽 끝의 색을 기억해, 다시 나타났을 때 방향이 뒤집혔는지 확인한다.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Any
import cv2
import numpy as np

END_FRAC = 0.12          # 끝 색을 재는 구간 (보이는 길이 대비)
MIN_SIG_DIST = 14.0      # 두 끝 색이 이만큼(Lab) 달라야 방향 판정에 쓴다
FLIP_MARGIN = 10.0       # 뒤집힌 쪽이 이만큼 더 잘 맞아야 뒤집는다
MAX_PTS = 4000


@dataclass
class Skeleton:
    tip: np.ndarray                      # (2,) 펜촉 (px)
    tail: np.ndarray                     # (2,) 반대쪽 끝
    visible: list[tuple[np.ndarray, np.ndarray]] = field(default_factory=list)   # 보이는 구간의 양 끝점
    hidden: list[tuple[np.ndarray, np.ndarray]] = field(default_factory=list)    # 가려져 채운 구간
    state: str = "seen"                  # seen | middle_hidden | tip_hidden | tail_hidden
    length: float = 0.0                  # 뼈대 길이 (px)
    evidence: str = ""                   # 어느 끝이 가려졌다고 판단한 근거: occluder | pose | color | previous | default

    @property
    def tip_hidden(self) -> bool:
        return self.state == "tip_hidden"

    def to_json(self) -> dict[str, Any]:
        r = lambda p: [round(float(p[0]), 1), round(float(p[1]), 1)]  # noqa: E731
        return {"tip": r(self.tip), "tail": r(self.tail), "state": self.state, "evidence": self.evidence,
                "visible": [[r(a), r(b)] for a, b in self.visible], "hidden": [[r(a), r(b)] for a, b in self.hidden]}


def _points(mask: np.ndarray) -> np.ndarray | None:
    rows = np.flatnonzero(mask.any(1))
    if rows.size == 0:
        return None
    cols = np.flatnonzero(mask[rows[0]:rows[-1] + 1].any(0))
    ys, xs = np.nonzero(mask[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1])
    if xs.size < 20:
        return None
    P = np.stack([xs + cols[0], ys + rows[0]], 1).astype(np.float64)
    if len(P) > MAX_PTS:
        P = P[np.random.default_rng(0).choice(len(P), MAX_PTS, replace=False)]
    return P


def fit_axis(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, float] | None:
    """(중심 c, 단위 축 u, 축 근처 점 P, 굵기 w). 길쭉하지 않으면 None. 축에서 먼 덩어리(손가락 조각)는 버린다."""
    P = _points(mask)
    if P is None:
        return None
    keep = P
    for _ in range(2):
        c = keep.mean(0)
        evals, evecs = np.linalg.eigh(np.cov((keep - c).T))
        u = evecs[:, 1]
        if evals[0] > 0 and evals[1] / max(evals[0], 1e-9) < 4.0:
            return None
        v = np.array([-u[1], u[0]])
        lat = np.abs((P - c) @ v)
        w_med = float(np.median(np.abs((keep - c) @ v)))
        keep = P[lat <= max(3.0, 3.0 * w_med)]
        if len(keep) < 20:
            return None
    c = keep.mean(0)
    evals, evecs = np.linalg.eigh(np.cov((keep - c).T))
    u = evecs[:, 1]
    v = np.array([-u[1], u[0]])
    width = 2.0 * float(np.median(np.abs((keep - c) @ v))) * 1.35   # 중앙값 반폭 → 대략의 전체 굵기
    return c, u, keep, max(width, 2.0)


def visible_runs(s: np.ndarray, width: float) -> list[tuple[float, float]]:
    """축 좌표 s 의 점들에서 끊긴 곳(틈 > 굵기)을 기준으로 보이는 구간들을 만든다."""
    lo = math.floor(float(s.min()))
    n = int(math.ceil(float(s.max()) - lo)) + 1
    cnt = np.bincount((s - lo).astype(int), minlength=n)
    occ = cnt >= max(1.0, 0.35 * float(np.median(cnt[cnt > 0])))
    runs: list[list[float]] = []
    i = 0
    while i < n:
        if occ[i]:
            j = i
            while j + 1 < n and occ[j + 1]:
                j += 1
            runs.append([lo + i, lo + j + 1])
            i = j + 1
        else:
            i += 1
    gap = max(3.0, 0.8 * width)
    merged: list[list[float]] = []
    for r in runs:
        if merged and r[0] - merged[-1][1] <= gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [(a, b) for a, b in merged if b - a >= max(2.0, 0.5 * width) or len(merged) == 1]


def _end_color(bgr: np.ndarray, mask: np.ndarray, p0: np.ndarray, p1: np.ndarray, width: float) -> np.ndarray | None:
    """p0→p1 구간(펜 끝 쪽) 마스크 픽셀의 평균 Lab."""
    h, w = mask.shape
    n = max(int(np.linalg.norm(p1 - p0)), 2)
    pts = p0[None, :] + (p1 - p0)[None, :] * np.linspace(0, 1, n)[:, None]
    seg = np.zeros((h, w), np.uint8)
    cv2.polylines(seg, [np.round(pts).astype(np.int32).reshape(-1, 1, 2)], False, 1, thickness=max(1, int(width * 0.8)))
    sel = (seg > 0) & mask.astype(bool)
    if sel.sum() < 12:
        return None
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    return lab[sel].mean(0)


class PenSkeleton:
    """한 자루 펜의 뼈대 기억. 길이는 PenTracker 가 가진 강체 길이를 받아 쓰고, 여기서는 끝 색을 기억한다."""

    def __init__(self) -> None:
        self.tip_lab: np.ndarray | None = None
        self.tail_lab: np.ndarray | None = None
        self.last: Skeleton | None = None

    def reset(self) -> None:
        self.last = None

    # ------------------------------------------------------------ 끝 색 기억
    def learn_ends(self, bgr: np.ndarray, mask: np.ndarray, sk: Skeleton, width: float) -> None:
        """온전히 보이는 모습에서 양 끝의 색을 기억한다."""
        if sk.state != "seen":
            return
        v = sk.tip - sk.tail
        L = float(np.linalg.norm(v))
        if L < 8 * width:
            return
        tip = _end_color(bgr, mask, sk.tip - v * END_FRAC * 1.5, sk.tip - v * 0.02, width)
        tail = _end_color(bgr, mask, sk.tail + v * 0.02, sk.tail + v * END_FRAC * 1.5, width)
        if tip is not None and tail is not None:
            self.tip_lab, self.tail_lab = tip, tail

    def _has_signature(self) -> bool:
        return (self.tip_lab is not None and self.tail_lab is not None
                and float(np.linalg.norm(self.tip_lab - self.tail_lab)) >= MIN_SIG_DIST)

    def orientation_vote(self, bgr: np.ndarray, mask: np.ndarray, sk: Skeleton, width: float) -> float | None:
        """+ 이면 지금 뼈대의 펜촉/반대쪽 방향이 기억한 색과 맞고, - 이면 뒤집혀 있다 (절댓값 = 확신). 판단 못 하면 None.
        가려진 끝은 색을 못 재므로 보이는 끝만 쓴다."""
        if not self._has_signature():
            return None
        v = sk.tip - sk.tail
        L = float(np.linalg.norm(v))
        if L < 6 * width:
            return None
        votes: list[float] = []
        if sk.state != "tip_hidden":
            c = _end_color(bgr, mask, sk.tip - v * END_FRAC * 1.5, sk.tip - v * 0.02, width)
            if c is not None:
                votes.append(float(np.linalg.norm(c - self.tail_lab)) - float(np.linalg.norm(c - self.tip_lab)))
        if sk.state != "tail_hidden":
            c = _end_color(bgr, mask, sk.tail + v * 0.02, sk.tail + v * END_FRAC * 1.5, width)
            if c is not None:
                votes.append(float(np.linalg.norm(c - self.tip_lab)) - float(np.linalg.norm(c - self.tail_lab)))
        return float(np.mean(votes)) if votes else None

    def should_flip(self, bgr: np.ndarray, mask: np.ndarray, sk: Skeleton, width: float) -> bool:
        vote = self.orientation_vote(bgr, mask, sk, width)
        return vote is not None and vote < -FLIP_MARGIN

    # ------------------------------------------------------------ 뼈대 구하기
    def observe(self, mask: np.ndarray, expected_dir: np.ndarray, length: float | None,
                pred_tip: np.ndarray | None = None, pred_tail: np.ndarray | None = None,
                occluder: np.ndarray | None = None, bgr: np.ndarray | None = None) -> Skeleton | None:
        """mask: 보이는 펜. expected_dir: 반대쪽 끝→펜촉 예상 방향(단위). length: 기억한 현재 펜 길이(px) 예상, 없으면 None.
        pred_tip/pred_tail: 포즈로 예측한 양 끝. occluder: 손 등 가리는 물체 마스크(없으면 None). bgr: 있으면 occluder 가 없을 때 피부색으로 손가락을 찾는다."""
        fit = fit_axis(mask)
        if fit is None:
            return None
        c, u, P, width = fit
        if float(u @ expected_dir) < 0:
            u = -u
        s = (P - c) @ u
        runs = visible_runs(s, width)
        if not runs:
            return None
        s_lo, s_hi = runs[0][0], runs[-1][1]
        vis_len = s_hi - s_lo
        pt = lambda x: c + x * u  # noqa: E731
        evidence = ""
        tip_s, tail_s = s_hi, s_lo
        state = "seen"
        if length is not None and vis_len < 0.85 * length:
            # 근거 없이 늘리지 않는다: 펜을 카메라 쪽으로 기울이면 길이가 줄어 보일 뿐일 수 있다 (3D 단축).
            hide_tip, evidence = self._which_hidden(c, u, s_lo, s_hi, length, width, pred_tip, pred_tail, occluder, bgr)
            if hide_tip is True:
                tip_s, state = s_lo + length, "tip_hidden"
            elif hide_tip is False:
                tail_s, state = s_hi - length, "tail_hidden"
            elif len(runs) > 1:
                state = "middle_hidden"
        elif len(runs) > 1:
            state = "middle_hidden"
        visible = [(pt(a), pt(b)) for a, b in runs]
        hidden = [(pt(runs[i][1]), pt(runs[i + 1][0])) for i in range(len(runs) - 1)]
        if state == "tip_hidden":
            hidden.append((pt(s_hi), pt(tip_s)))
        elif state == "tail_hidden":
            hidden.append((pt(tail_s), pt(s_lo)))
        sk = Skeleton(pt(tip_s), pt(tail_s), visible, hidden, state, float(abs(tip_s - tail_s)), evidence)
        self.last = sk
        return sk

    def _which_hidden(self, c, u, s_lo, s_hi, length, width, pred_tip, pred_tail, occluder, bgr):  # type: ignore[no-untyped-def]
        """(펜촉이 가려졌나 True | 반대쪽 끝이 가려졌나 False | 모르겠다 None, 근거).
        보이는 끝 바로 너머에 손(가리는 물체 마스크 또는 피부색)이 있는 쪽을 가려진 끝으로 본다. 그런 증거가 없으면 모른다(None)."""
        cov = None
        if occluder is not None:
            cov, name = (lambda p: self._in_mask(occluder, p)), "occluder"
        elif bgr is not None:
            cov, name = (lambda p: self._is_skin(bgr, p)), "skin"
        if cov is not None:
            hi = self._covered(cov, c + s_hi * u, u, width)
            lo = self._covered(cov, c + s_lo * u, -u, width)
            if hi != lo:
                if name == "skin" and hi:
                    return (None, "")   # 펜촉은 보통 책상(피부색과 비슷한 베이지)에 닿아 있다: 피부색만으로 펜촉이 가려졌다고 하지 않는다
                return (hi, name)
        # 포즈 예측만으로는 늘리지 않는다: 실제 영상에서 3D 단축을 가림으로 착각해 펜촉을 책상 위로 늘렸다.
        return (None, "")

    @staticmethod
    def _in_mask(m: np.ndarray, p: np.ndarray) -> bool:
        x, y = int(round(p[0])), int(round(p[1]))
        return 0 <= x < m.shape[1] and 0 <= y < m.shape[0] and bool(m[y, x])

    @staticmethod
    def _is_skin(bgr: np.ndarray, p: np.ndarray) -> bool:
        """한 점 주변 5x5 평균색이 피부색(YCrCb)인가. 전체 영상을 바꾸지 않고 몇 점만 본다."""
        h, w = bgr.shape[:2]
        x, y = int(round(p[0])), int(round(p[1]))
        if not (2 <= x < w - 2 and 2 <= y < h - 2):
            return False
        patch = bgr[y - 2:y + 3, x - 2:x + 3].reshape(-1, 3).mean(0).astype(np.uint8).reshape(1, 1, 3)
        yy, cr, cb = (int(v) for v in cv2.cvtColor(patch, cv2.COLOR_BGR2YCrCb)[0, 0])
        return yy > 50 and 135 <= cr <= 180 and 80 <= cb <= 130

    @staticmethod
    def _covered(cov, end: np.ndarray, direction: np.ndarray, width: float) -> bool:  # type: ignore[no-untyped-def]
        """보이는 끝 너머 0.6~1.4 굵기 거리의 점들 중 가리는 물체인 것의 비율."""
        v = np.array([-direction[1], direction[0]])
        hit = tot = 0
        for d in (0.6, 1.0, 1.4):
            for l in (-0.5, 0.0, 0.5):
                tot += 1
                hit += bool(cov(end + direction * d * width + v * l * width))
        return hit / max(tot, 1) >= 0.4
