"""등록용 분할기 (박스·점 프롬프트 → 마스크).

- ModelSegmenter: EfficientTAM-Ti 이미지 predictor (MPS). 기본.
- GrabCutSegmenter: ML 의존성이 없을 때의 폴백 (박스 전용, 느리고 부정확).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import cv2
import numpy as np

from . import gpu

log = logging.getLogger(__name__)


@dataclass
class SegResult:
    masks: list[np.ndarray]   # 후보 마스크 (bool, 프레임 크기)
    scores: list[float]       # 모델이 예측한 품질 (IoU 추정), 0..1


class Segmenter(Protocol):
    name: str

    def segment(self, frame_bgr: np.ndarray, box: tuple[float, float, float, float] | None = None,
                points: list[tuple[float, float, int]] | None = None) -> SegResult: ...


class ModelSegmenter:
    name = "efficienttam_ti_512"
    CONFIG = "configs/efficienttam/efficienttam_ti_512x512.yaml"
    CKPT = "efficienttam_ti_512x512.pt"

    def __init__(self) -> None:
        self._pred = None

    def _load(self):  # GPU 스레드에서만
        if self._pred is None:
            from efficient_track_anything.build_efficienttam import build_efficienttam
            from efficient_track_anything.efficienttam_image_predictor import EfficientTAMImagePredictor

            model = build_efficienttam(self.CONFIG, str(gpu.MODELS_DIR / self.CKPT), device=gpu.device())
            self._pred = EfficientTAMImagePredictor(model)
        return self._pred

    def warmup(self) -> None:
        gpu.run(self._load)

    def segment(self, frame_bgr, box=None, points=None) -> SegResult:
        return gpu.run(self._segment, frame_bgr, box, points)

    def _segment(self, frame_bgr, box, points) -> SegResult:
        import torch

        pred = self._load()
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        kw: dict = {"multimask_output": True}
        if box is not None:
            kw["box"] = np.asarray(box, np.float32)
        if points:
            kw["point_coords"] = np.asarray([[p[0], p[1]] for p in points], np.float32)
            kw["point_labels"] = np.asarray([p[2] for p in points], np.int32)
        with torch.inference_mode(), torch.autocast(gpu.device().type, dtype=torch.float16):
            pred.set_image(rgb)
            masks, scores, _ = pred.predict(**kw)
        return SegResult([m.astype(bool) for m in masks], [float(s) for s in scores])


class GrabCutSegmenter:
    name = "grabcut"

    def segment(self, frame_bgr, box=None, points=None) -> SegResult:
        h, w = frame_bgr.shape[:2]
        if box is None:
            if not points:
                raise ValueError("box or points required")
            x, y = points[0][0], points[0][1]
            r = 0.08 * max(w, h)
            box = (x - r, y - r, x + r, y + r)
        x1, y1 = max(0, int(box[0])), max(0, int(box[1]))
        x2, y2 = min(w, int(box[2])), min(h, int(box[3]))
        if x2 - x1 < 4 or y2 - y1 < 4:
            return SegResult([np.zeros((h, w), bool)], [0.0])
        mask = np.zeros((h, w), np.uint8)
        bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
        cv2.grabCut(frame_bgr, mask, (x1, y1, x2 - x1, y2 - y1), bgd, fgd, 4, cv2.GC_INIT_WITH_RECT)
        fg = (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)
        return SegResult([fg], [0.5])


_default: Segmenter | None = None


def default_segmenter() -> Segmenter:
    global _default
    if _default is None:
        _default = ModelSegmenter() if gpu.ml_available() else GrabCutSegmenter()
        log.info("segmenter: %s", _default.name)
    return _default
