"""모양 기억과 모양 기반 재획득 (놓친 물체를 화면 전체에서 다시 찾기).

등록할 때 물체의 모양(정규화 마스크 템플릿, Hu 모멘트, 기준 면적)과 색(Lab 색 인덱스 히스토그램)을 기억한다.
물체를 놓치면(LOST/OCCLUDED) 화면 전체의 물체 색 확률 지도에서
    1) 색 덩어리 + 2) 기억한 모양의 템플릿 매칭
으로 후보 박스를 찾고, 이미지 분할기(EfficientTAM)로 후보 마스크를 얻어 기억한 모양과 비교한다.

모든 함수는 순수 함수라 GPU 스레드(프레임 처리 스레드 밖)에서 그대로 돌릴 수 있다.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np

CANVAS = 64  # 정렬 IoU 를 재는 정규화 캔버스 한 변 (px)
_FILL = 0.35  # 캔버스에서 물체가 차지하는 면적 비율 (회전해도 캔버스 밖으로 안 나가게)


@dataclass
class ShapeMemory:
    """등록 시 기억한 모양. 추적 중에는 바꾸지 않는다 (다시 선택할 때만 새로 만든다)."""

    template: np.ndarray      # 정규화 캔버스 위 마스크 (CANVAS×CANVAS bool, 중심·면적·주축 정렬)
    hu: np.ndarray            # log Hu 모멘트 7개
    area: float               # 기준 면적 (작업 해상도 px)
    color: np.ndarray         # 물체 색 히스토그램 (Lab 색 인덱스 빈도, 합 1)
    elongation: float         # 주축 길이비 (≥ 1)
    bbox_wh: tuple[int, int]  # 등록 마스크 박스 크기 (템플릿 매칭용)
    crop: np.ndarray          # 등록 마스크 박스 자른 것 (bool, 템플릿 매칭용)


@dataclass
class ReacquireConfig:
    enabled: bool = True
    period_s: float = 0.3         # 물체 하나당 탐색 주기
    max_candidates: int = 3       # 분할할 후보 박스 수 (분할 1회 약 30~40ms, GPU 스레드)
    sim_ms: float = 90.0          # sim 모드 지연 모델 (결정적 평가)
    # 합격 임계값 (모두 통과해야 한다)
    min_iou: float = 0.72         # 정렬 IoU
    max_hu: float = 0.5           # log Hu 거리
    area_lo: float = 0.4          # 면적비 (후보 / 마지막 예상 면적). 멀어지고 가까워진 것까지 허용
    area_hi: float = 2.5
    min_color: float = 0.6        # 색 히스토그램 유사도 (Bhattacharyya 계수)
    min_model: float = 0.7        # 분할 모델 품질 점수
    exclude_iou: float = 0.5      # 다른 추적 중인 물체와 이만큼 겹치면 후보에서 뺀다
    ambiguity: float = 0.04       # 합격 후보 둘의 점수 차가 이보다 작으면 (닮은 물체) 고르지 않는다
    confirm: int = 2              # 같은 곳에서 연속 몇 번 합격해야 복구하나 (닮은 물체로 튀는 것 방지)


@dataclass
class ShapeScore:
    iou: float
    hu: float
    area_ratio: float
    color: float
    model: float = 1.0

    def passes(self, cfg: ReacquireConfig) -> bool:
        return (self.iou >= cfg.min_iou and self.hu <= cfg.max_hu and cfg.area_lo <= self.area_ratio <= cfg.area_hi
                and self.color >= cfg.min_color and self.model >= cfg.min_model)

    @property
    def total(self) -> float:
        """여러 후보 중 고를 때 쓰는 하나의 점수 (높을수록 비슷함)."""
        return self.iou * self.color * math.exp(-self.hu) * min(self.model, 1.0)


# ---------------------------------------------------------------- 모양 기술자
def _moments(mask: np.ndarray) -> dict | None:
    m = cv2.moments(np.ascontiguousarray(mask, dtype=np.uint8), binaryImage=True)
    return m if m["m00"] >= 1 else None


def log_hu(m: dict) -> np.ndarray:
    hu = cv2.HuMoments(m).ravel()
    return -np.sign(hu) * np.log10(np.abs(hu) + 1e-30)


def hu_distance(a: np.ndarray, b: np.ndarray) -> float:
    """앞 2개 log Hu 차이 평균. 0 = 같음.

    h1(퍼짐)·h2(길쭉함)만 쓴다: h3 이후는 거의 대칭인 모양에서 값이 0 에 가까워 log 가 크게 흔들린다
    (합성 펜 실측: 같은 물체인데 앞 4개 평균 1.4)."""
    return float(np.mean(np.abs(a[:2] - b[:2])))


def _principal(m: dict) -> tuple[float, float]:
    """주축 각도(라디안)와 길이비."""
    mu20, mu02, mu11 = m["mu20"] / m["m00"], m["mu02"] / m["m00"], m["mu11"] / m["m00"]
    ang = 0.5 * math.atan2(2 * mu11, mu20 - mu02)
    d = math.sqrt(max(0.0, 4 * mu11 ** 2 + (mu20 - mu02) ** 2))
    l1, l2 = (mu20 + mu02 + d) / 2, (mu20 + mu02 - d) / 2
    return ang, math.sqrt(l1 / max(l2, 1e-9))


def normalize(mask: np.ndarray, flip: bool = False) -> np.ndarray | None:
    """마스크를 정규화 캔버스에 놓는다: 중심 → 캔버스 가운데, 면적 → 캔버스의 _FILL, 주축 → 가로.

    평행 이동·크기·회전에 불변 (주축 방향의 180° 모호성은 flip 으로 둘 다 본다)."""
    m = _moments(mask)
    if m is None:
        return None
    cx, cy = m["m10"] / m["m00"], m["m01"] / m["m00"]
    ang, elong = _principal(m)
    s = math.sqrt(_FILL * CANVAS * CANVAS / m["m00"])
    rot = -ang + (math.pi if flip else 0.0) if elong > 1.15 else 0.0  # 둥근 물체는 주축이 불안정하므로 회전하지 않음
    c, sn = math.cos(rot) * s, math.sin(rot) * s
    M = np.array([[c, -sn, CANVAS / 2 - (c * cx - sn * cy)],
                  [sn, c, CANVAS / 2 - (sn * cx + c * cy)]], np.float64)
    out = cv2.warpAffine(np.ascontiguousarray(mask, dtype=np.uint8), M, (CANVAS, CANVAS), flags=cv2.INTER_LINEAR)
    return out > 0


def aligned_iou(template: np.ndarray, mask: np.ndarray) -> float:
    """기억한 템플릿과 마스크를 정규화 캔버스에서 겹친 IoU (주축 180° 두 방향 중 큰 쪽)."""
    best = 0.0
    for flip in (False, True):
        n = normalize(mask, flip)
        if n is None:
            return 0.0
        inter = np.logical_and(template, n).sum()
        union = np.logical_or(template, n).sum()
        best = max(best, inter / union if union else 0.0)
    return float(best)


def color_hist(idx: np.ndarray, mask: np.ndarray, nbins: int) -> np.ndarray:
    h = np.bincount(idx[mask].ravel(), minlength=nbins).astype(np.float64)
    return h / max(h.sum(), 1.0)


def color_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Bhattacharyya 계수 (1 = 같은 분포)."""
    return float(np.sqrt(a * b).sum())


def make_memory(mask: np.ndarray, idx: np.ndarray, nbins: int) -> ShapeMemory:
    m = _moments(mask)
    if m is None:
        raise ValueError("empty mask")
    tpl = normalize(mask)
    assert tpl is not None
    _, elong = _principal(m)
    ys, xs = np.nonzero(mask)
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1].copy()
    return ShapeMemory(tpl, log_hu(m), float(m["m00"]), color_hist(idx, mask, nbins), elong,
                       (int(crop.shape[1]), int(crop.shape[0])), crop)


def shape_score(mem: ShapeMemory, mask: np.ndarray, idx: np.ndarray, expected_area: float,
                model: float = 1.0) -> ShapeScore | None:
    m = _moments(mask)
    if m is None:
        return None
    return ShapeScore(aligned_iou(mem.template, mask), hu_distance(mem.hu, log_hu(m)),
                      float(m["m00"]) / max(expected_area, 1.0),
                      color_similarity(mem.color, color_hist(idx, mask, len(mem.color))), model)


# ---------------------------------------------------------------- 후보 찾기
Box = tuple[float, float, float, float]


def _iou_box(a: Box, b: Box) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def candidate_boxes(prob: np.ndarray, mem: ShapeMemory, scale: float, thr: float,
                    max_n: int, step: int = 2) -> list[tuple[Box, float]]:
    """물체 색 확률 지도(작업 해상도)에서 후보 박스와 근거 점수.

    - 색 덩어리: 확률 > thr 인 연결 성분 중 면적이 예상(기억 면적 × scale²)의 0.3~3배
    - 템플릿 매칭: 기억한 마스크 모양(여러 크기)을 확률 지도에 맞춘 상관 최댓값
    박스는 겹치면 하나로 합친다 (점수가 높은 쪽)."""
    H, W = prob.shape
    p = cv2.GaussianBlur(np.ascontiguousarray(prob[::step, ::step], dtype=np.float32), (5, 5), 0)
    out: list[tuple[Box, float]] = []
    expected = mem.area * scale * scale / (step * step)
    fg = (p > thr).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    for i in range(1, n):
        a = stats[i, cv2.CC_STAT_AREA]
        if not 0.3 * expected <= a <= 3.0 * expected:
            continue
        x, y, w, h = stats[i, :4]
        out.append(((float(x * step), float(y * step), float((x + w) * step), float((y + h) * step)),
                    float(min(a / expected, expected / a))))
    for s in (0.7, 1.0, 1.4):
        tw, th = mem.bbox_wh
        tw, th = int(round(tw * scale * s / step)), int(round(th * scale * s / step))
        if tw < 4 or th < 4 or tw >= p.shape[1] or th >= p.shape[0]:
            continue
        tpl = cv2.resize(mem.crop.astype(np.float32), (tw, th), interpolation=cv2.INTER_AREA) * 2 - 1
        r = cv2.matchTemplate(p, tpl, cv2.TM_CCOEFF_NORMED)
        for _ in range(2):  # 크기마다 상위 2개 (비최대 억제)
            _, v, _, (x, y) = cv2.minMaxLoc(r)
            if v < 0.4:
                break
            out.append(((float(x * step), float(y * step), float((x + tw) * step), float((y + th) * step)), float(v)))
            r[max(0, y - th // 2):y + th // 2 + 1, max(0, x - tw // 2):x + tw // 2 + 1] = -1
    out.sort(key=lambda c: -c[1])
    merged: list[tuple[Box, float]] = []
    for b, v in out:
        if all(_iou_box(b, m[0]) < 0.4 for m in merged):
            merged.append((b, v))
    clipped = []
    for (x1, y1, x2, y2), v in merged[:max_n]:
        # 분할 프롬프트로 쓰도록 조금 넓힌다
        mx, my = 0.1 * (x2 - x1), 0.1 * (y2 - y1)
        clipped.append(((max(0.0, x1 - mx), max(0.0, y1 - my), min(W - 1.0, x2 + mx), min(H - 1.0, y2 + my)), v))
    return clipped


@dataclass
class ReacquireResult:
    mask: np.ndarray
    score: ShapeScore
    ambiguous: bool   # 다른 합격 후보가 거의 같은 점수 (닮은 물체): 고르지 않는다


def search(frame: np.ndarray, idx: np.ndarray, prob: np.ndarray, mem: ShapeMemory, scale: float, thr: float,
           cfg: ReacquireConfig, segment: Callable[[np.ndarray, Box], tuple[list[np.ndarray], list[float]]],
           exclude: list[np.ndarray]) -> ReacquireResult | None:
    """후보 찾기 → 분할 → 모양 점수 → 가장 높은 합격 후보. GPU 스레드에서 돈다.

    segment(frame, box) → (masks, scores). exclude: 다른 추적 중인 물체들의 마스크 (작업 해상도)."""
    expected = mem.area * scale * scale
    passed: list[tuple[np.ndarray, ShapeScore]] = []
    for box, _ in candidate_boxes(prob, mem, scale, thr, cfg.max_candidates):
        masks, scores = segment(frame, box)
        best: tuple[np.ndarray, ShapeScore] | None = None
        for m, sc in zip(masks, scores, strict=False):
            if m.shape != idx.shape or m.sum() < 16:
                continue
            if any(_mask_iou(m, e) >= cfg.exclude_iou for e in exclude):
                continue
            s = shape_score(mem, m, idx, expected, sc)
            if s is not None and s.passes(cfg) and (best is None or s.total > best[1].total):
                best = (m, s)
        if best is not None and all(_mask_iou(best[0], p[0]) < 0.5 for p in passed):
            passed.append(best)
    if not passed:
        return None
    passed.sort(key=lambda p: -p[1].total)
    ambiguous = len(passed) > 1 and passed[0][1].total - passed[1][1].total < cfg.ambiguity
    return ReacquireResult(passed[0][0], passed[0][1], ambiguous)


def _mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        return 0.0
    u = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / u) if u else 0.0
