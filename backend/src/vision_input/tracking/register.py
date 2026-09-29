"""물체 등록: 후보 마스크 선택, 품질 검사, 신호 가중치.

물체 종류별 규칙은 없다. 모든 판정은 프레임·물체 크기에 대한 상대값이다.
질감이 없거나 대비가 낮아도 거부하지 않고, 대신 어떤 신호를 믿을지(가중치)를 정한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from ..tracking.api import Box, box_iou, mask_to_box
from .measure import MaskMeasure, largest_component, measure_mask
from .segment import SegResult, Segmenter

MIN_AREA_FRAC = 0.0008   # 1280x720 에서 약 740px² (27px 정사각형)
MAX_AREA_FRAC = 0.5


class RegistrationError(ValueError):
    """등록 거부. message 는 사용자에게 그대로 보여 준다."""


@dataclass
class Registration:
    mask: np.ndarray
    measure: MaskMeasure
    score: float                     # 모델 품질 점수
    candidates: list[np.ndarray]     # 다른 후보 (UI 에서 바꿔 고를 수 있게)
    candidate_index: int
    texture: float                   # 0..1, 마스크 안 코너·기울기 밀도 → 점 추적 가중치
    contrast: float                  # 0..1, 물체 vs 주변 색 분포 차이 → 영역 모델 가중치
    warnings: list[str] = field(default_factory=list)


def texture_score(gray: np.ndarray, mask: np.ndarray) -> float:
    """물체 크기에 무관한 질감 지표: 마스크 내부(경계 제외)의 코너 밀도와 기울기 에너지."""
    m = mask.astype(np.uint8)
    size = np.sqrt(max(m.sum(), 1))
    k = max(3, int(size * 0.06)) | 1
    inner = cv2.erode(m, np.ones((k, k), np.uint8))
    if inner.sum() < 30:
        return 0.0
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(gx * gx + gy * gy)[inner > 0]
    grad = float(np.clip(np.percentile(mag, 75) / 60.0, 0, 1))
    min_dist = max(3, int(size / 25))
    pts = cv2.goodFeaturesToTrack(gray, 400, 0.01, min_dist, mask=inner)
    n = 0 if pts is None else len(pts)
    corners = float(np.clip(n / 40.0, 0, 1))  # 물체당 40개면 충분
    return round(0.6 * corners + 0.4 * grad, 3)


def contrast_score(bgr: np.ndarray, mask: np.ndarray) -> float:
    """물체 색 분포와 주변 고리(물체 크기의 약 30% 폭)의 Bhattacharyya 거리, 0..1."""
    m = mask.astype(np.uint8)
    size = np.sqrt(max(m.sum(), 1))
    k = max(5, int(size * 0.3)) | 1
    ring = cv2.dilate(m, np.ones((k, k), np.uint8)) & (1 - m)
    if ring.sum() < 30 or m.sum() < 30:
        return 0.0
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    hist = lambda mm: cv2.normalize(cv2.calcHist([lab], [0, 1, 2], mm, [12, 8, 8], [0, 256, 0, 256, 0, 256]),
                                    None, 1, 0, cv2.NORM_L1)
    d = cv2.compareHist(hist(m), hist(ring), cv2.HISTCMP_BHATTACHARYYA)
    return round(float(np.clip(d, 0, 1)), 3)


def choose_candidate(seg: SegResult, prompt_box: Box | None) -> list[int]:
    """후보 순서. 박스 프롬프트면 '박스를 잘 채우는' 마스크를, 아니면 모델 점수를 우선한다."""
    order = []
    for i, (m, s) in enumerate(zip(seg.masks, seg.scores, strict=True)):
        b = mask_to_box(m)
        if b is None:
            continue
        fit = box_iou(b, prompt_box) if prompt_box is not None else 1.0
        order.append((s * (0.3 + 0.7 * fit), i))
    order.sort(reverse=True)
    return [i for _, i in order]


def register_line(frame: np.ndarray, segmenter: Segmenter, tip: tuple[float, float],
                  tail: tuple[float, float]) -> Registration:
    """펜처럼 가는 물체: 펜촉·반대쪽 끝 두 점. 선 위 점들을 프롬프트로 주고 '선을 따라 가늘게 덮는' 후보를 고른다."""
    from ..pen import line_box, line_prompts, pen_mask_from_line

    h, w = frame.shape[:2]
    L = float(np.hypot(tail[0] - tip[0], tail[1] - tip[1]))
    if L < 0.04 * max(w, h):
        raise RegistrationError("두 점이 너무 가깝습니다. 펜촉과 펜의 반대쪽 끝을 찍어 주세요.")
    seg = segmenter.segment(frame, box=line_box(tip, tail, (w, h)), points=line_prompts(tip, tail, 5))
    best = pen_mask_from_line(seg.masks, tip, tail)
    if best is None or best.sum() < 20:
        raise RegistrationError("펜을 찾지 못했습니다. 펜 위를 정확히 찍었는지 확인하세요.")
    mask, _ = largest_component(best)
    meas = measure_mask(mask)
    assert meas is not None
    warnings = []
    if meas.elongation < 3.0:
        warnings.append("선택한 물체가 충분히 길쭉하지 않습니다. 손가락까지 잡혔을 수 있습니다.")
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    idx = next((i for i, m in enumerate(seg.masks) if m is best), 0)
    return Registration(mask, meas, seg.scores[idx], [mask], 0, texture_score(gray, mask),
                        contrast_score(frame, mask), warnings)


def register(frame: np.ndarray, segmenter: Segmenter, box: Box | None = None,
             point: tuple[float, float] | None = None, candidate: int | None = None) -> Registration:
    h, w = frame.shape[:2]
    if box is not None:
        box = (max(0.0, box[0]), max(0.0, box[1]), min(float(w), box[2]), min(float(h), box[3]))
        if box[2] - box[0] < 6 or box[3] - box[1] < 6:
            raise RegistrationError("선택한 영역이 너무 작습니다. 물체를 조금 더 크게 드래그하세요.")
    pts = [(point[0], point[1], 1)] if point is not None else None
    seg = segmenter.segment(frame, box=box, points=pts)
    order = choose_candidate(seg, box)
    if not order:
        raise RegistrationError("물체를 찾지 못했습니다. 물체 위를 다시 클릭하거나 드래그하세요.")
    idx = order[0] if candidate is None else order[candidate % len(order)]
    raw = seg.masks[idx]
    mask, frac_main = largest_component(raw)
    warnings: list[str] = []
    if frac_main < 0.85:
        warnings.append("마스크가 여러 조각이라 가장 큰 조각만 씁니다.")
    area_frac = mask.sum() / (w * h)
    if area_frac < MIN_AREA_FRAC:
        raise RegistrationError("물체가 너무 작게 보입니다. 카메라에 더 가까이 두세요.")
    if area_frac > MAX_AREA_FRAC:
        raise RegistrationError("선택 영역이 화면의 절반을 넘습니다. 배경까지 잡혔을 수 있으니 물체만 다시 선택하세요.")
    meas = measure_mask(mask)
    assert meas is not None
    # 화면 가장자리에 걸린 정도
    edge = np.concatenate([mask[0], mask[-1], mask[:, 0], mask[:, -1]]).sum()
    perim = max(1.0, cv2.arcLength(max(cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL,
                                                           cv2.CHAIN_APPROX_NONE)[0], key=len), True))
    if edge / perim > 0.1:
        warnings.append("물체가 화면 가장자리에 걸려 있습니다. 중앙 쪽으로 옮기면 더 안정적입니다.")
    score = seg.scores[idx]
    if score < 0.6:
        warnings.append("분할 신뢰도가 낮습니다. 경계를 확인하고 필요하면 다른 후보를 고르세요.")
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    tex, con = texture_score(gray, mask), contrast_score(frame, mask)
    if tex < 0.15 and con < 0.2:
        warnings.append("무늬도 적고 배경과 색도 비슷합니다. 손으로 가리면 추적이 약해질 수 있습니다.")
    return Registration(mask, meas, score, [seg.masks[i] for i in order], order.index(idx), tex, con, warnings)
