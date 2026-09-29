"""영상 메모리와 별개로 새 프레임을 분할하고 등록 외형으로 검증한다."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time

import cv2
import numpy as np

from .measure import measure_mask
from .segment import Segmenter


@dataclass
class RefreshAnchor:
    prior: np.ndarray
    forbidden: np.ndarray
    template: np.ndarray
    color_table: np.ndarray
    base_probability: float


def choose_mask(masks: list[np.ndarray], scores: list[float], anchor: RefreshAnchor,
                idx: np.ndarray) -> tuple[np.ndarray, float] | None:
    """갑작스러운 확장, 다른 물체 침범, 등록 색·모양과 다른 후보를 버린다."""
    reference = measure_mask(anchor.template)
    if reference is None:
        return None
    prior_area = int(anchor.prior.sum())
    best = None
    best_score = -1.
    contours0, _ = cv2.findContours(anchor.template.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contour0 = max(contours0, key=cv2.contourArea)
    for candidate, confidence in zip(masks, scores, strict=False):
        if not math.isfinite(confidence) or confidence < .45 or candidate.shape != idx.shape:
            continue
        mask = candidate.astype(bool)
        if (mask & anchor.forbidden).sum() > .08 * max(mask.sum(), 1):
            continue
        mask = mask & ~anchor.forbidden
        # 모델이 별도 덩어리도 반환하면 사전 영역에 닿은 하나만 택한다.
        n, labels, _, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
        if n <= 1:
            continue
        # 픽셀을 덩어리마다 다시 훑지 않고 한 번에 겹침을 센다 (배경 라벨 0 제외).
        overlaps = np.bincount(labels[anchor.prior], minlength=n)
        label = int(np.argmax(overlaps[1:])) + 1
        overlap = int(overlaps[label])
        mask = labels == label
        area = int(mask.sum())
        if area < 20 or overlap < .12 * min(area, prior_area):
            continue
        ratio = area / max(prior_area, 1)
        if not .18 < ratio < 2.5:
            continue
        appearance = float(anchor.color_table[idx[mask]].mean())
        if appearance < max(.27, anchor.base_probability * .75 - .05):
            continue
        meas = measure_mask(mask)
        if meas is None or not .55 < meas.elongation / max(reference.elongation, 1e-4) < 1.8:
            continue
        contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contour = max(contours, key=cv2.contourArea)
        shape_error = cv2.matchShapes(contour0, contour, cv2.CONTOURS_MATCH_I1, 0)
        if not math.isfinite(shape_error) or shape_error > .5:
            continue
        quality = confidence * .45 + appearance * .35 + min(1., overlap / max(area, 1)) * .2
        if quality > best_score:
            best, best_score = (mask, confidence), quality
    return best


def resegment(segmenter: Segmenter, image: np.ndarray, idx: np.ndarray,
              anchors: dict[int, RefreshAnchor], tam=None, t: float = 0.) -> tuple[dict, float, str]:
    start = time.perf_counter()
    results = {}
    h, w = idx.shape
    for oid, anchor in anchors.items():
        ys, xs = np.nonzero(anchor.prior)
        if not xs.size:
            continue
        margin = max(4, round(math.sqrt(len(xs)) * .2))
        box = (max(0, int(xs.min()) - margin), max(0, int(ys.min()) - margin),
               min(w, int(xs.max()) + margin + 1), min(h, int(ys.max()) + margin + 1))
        safe = anchor.prior & ~anchor.forbidden & (anchor.color_table[idx] > .3)
        if not safe.any():
            results[oid] = None
            continue
        distance = cv2.distanceTransform(safe.astype(np.uint8), cv2.DIST_L2, 3)
        y, x = np.unravel_index(np.argmax(distance), distance.shape)
        points = [(float(x), float(y), 1)]
        n, labels, _, centers = cv2.connectedComponentsWithStats(anchor.forbidden.astype(np.uint8), 8)
        points += [(float(cx), float(cy), 0) for cx, cy in centers[1:n]]
        seg = segmenter.segment(image, box=box, points=points)
        accepted = choose_mask(seg.masks, seg.scores, anchor, idx)
        results[oid] = accepted
        # 위치 보정 후보만 반환한다. 비동기 검증 전에 TAM 기억을 변경하지 않는다.
    return results, (time.perf_counter() - start) * 1000, segmenter.name
