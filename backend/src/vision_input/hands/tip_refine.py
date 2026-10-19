"""EfficientTAM 으로 손끝 주변 원 안의 '손가락 살색 부분'만 분할해 추적점을 바로잡는다 (가끔, 비동기).

점 추적(tip_track)은 프레임마다 빠르게 돌지만 오래 쓰면 손가락 사이·배경으로 조금씩 어긋난다.
여기서는 0.3초 정도마다 두 손끝 주변 원을 원본 해상도로 잘라 EfficientTAM 에 점 프롬프트로 분할시키고
1) 마스크 밖으로 나간 점은 마스크 안쪽으로 당겨 놓거나 (너무 멀면 버리고),
2) 마스크 안 픽셀로 살색 모델(Lab a,b)을 다시 만든다 → 프레임마다 하는 살색 확인이 정확해진다.
분할이 가끔 늦거나 실패해도 점 추적은 그대로 돈다 (결과는 다음 프레임에 반영).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import cv2
import numpy as np

from .tip_track import TipFrame, TipTracker

log = logging.getLogger(__name__)


@dataclass
class _Result:
    name_pts: dict[str, np.ndarray]       # 작업 해상도 기준, 마스크 안 최근접점 (밖이면 당겨 맞출 위치)
    inside: dict[str, bool]
    dist: dict[str, float]                # 마스크까지 거리 (작업 해상도 px)
    ab: np.ndarray                        # 마스크 안 (a, b) 샘플


class TipRefiner:
    def __init__(self, segmenter, period_s: float = 0.3) -> None:  # type: ignore[no-untyped-def]
        self.segmenter = segmenter
        self.period_s = period_s
        self._lock = threading.Lock()
        self._pending = False
        self._result: _Result | None = None
        self._last = -1e9
        self.stats = {"jobs": 0, "applied": 0, "snapped": 0, "dropped": 0, "errors": 0}

    def reset(self) -> None:
        with self._lock:
            self._result = None

    # ------------------------------------------------------------------
    def maybe_submit(self, frame_bgr: np.ndarray, t: float, tf: TipFrame) -> None:
        """tf: 이번 프레임의 추적 결과. 두 점 중 하나 이상이 있고 간격이 지났으면 분할 작업을 제출한다."""
        if self.segmenter is None or t - self._last < self.period_s:
            return
        valid = {n: tip for n, tip in tf.tips.items() if tip.valid}
        if not valid:
            return
        with self._lock:
            if self._pending:
                return
            self._pending = True
        self._last = t
        H, W = frame_bgr.shape[:2]
        k = W / tf.size[0]                                   # 작업 → 원본 배율
        pts = np.array([tip.xy for tip in valid.values()])
        center = pts.mean(0)
        hs = tf.hand_size if tf.hand_size > 0 else 80.0
        spread = float(np.max(np.linalg.norm(pts - center, axis=1))) if len(pts) > 1 else 0.0
        r = float(np.clip(max(0.9 * hs, 1.8 * spread), 24.0, 0.5 * tf.size[0]))   # 손끝 주변 '넓은 원'의 반지름
        x0, y0 = int(max(0, (center[0] - r) * k)), int(max(0, (center[1] - r) * k))
        x1, y1 = int(min(W, (center[0] + r) * k)), int(min(H, (center[1] + r) * k))
        if x1 - x0 < 16 or y1 - y0 < 16:
            with self._lock:
                self._pending = False
            return
        crop = frame_bgr[y0:y1, x0:x1].copy()
        prompts = [((tip.xy[0] * k - x0), (tip.xy[1] * k - y0), 1) for tip in valid.values()]
        names = list(valid)
        work_pts = {n: tip.xy.copy() for n, tip in valid.items()}
        self.stats["jobs"] += 1
        try:
            from ..tracking import gpu
            gpu.submit(self._job, crop, prompts, names, work_pts, (x0, y0, k), r)
        except Exception:  # GPU 스레드를 못 쓰면 이번엔 건너뜀
            log.exception("tip refine submit failed")
            self.stats["errors"] += 1
            with self._lock:
                self._pending = False

    def _job(self, crop, prompts, names, work_pts, geom, radius) -> None:  # type: ignore[no-untyped-def]
        x0, y0, k = geom
        try:
            res = self.segmenter.segment(crop, points=prompts)
            mask = self._pick(res, prompts, crop.shape[:2], radius * k)
            if mask is None:
                return
            inv = (~mask).astype(np.uint8)
            dist, labels = cv2.distanceTransformWithLabels(inv, cv2.DIST_L2, 3, labelType=cv2.DIST_LABEL_PIXEL)
            ys, xs = np.nonzero(mask)
            lut = np.zeros((int(labels.max()) + 1, 2), np.int32)      # 라벨 → 그 마스크 픽셀의 좌표
            lut[labels[ys, xs]] = np.stack([xs, ys], axis=1)
            near, inside, dd = {}, {}, {}
            for name, (px, py, _) in zip(names, prompts):
                ix, iy = int(np.clip(round(px), 0, mask.shape[1] - 1)), int(np.clip(round(py), 0, mask.shape[0] - 1))
                inside[name] = bool(mask[iy, ix])
                dd[name] = float(dist[iy, ix]) / k
                lab = int(labels[iy, ix])
                nx, ny = (ix, iy) if inside[name] else (int(lut[lab][0]), int(lut[lab][1]))
                near[name] = np.array([(nx + x0) / k, (ny + y0) / k])
            sel = np.random.default_rng(0).choice(len(ys), size=min(600, len(ys)), replace=False)
            lab_img = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)
            ab = lab_img[ys[sel], xs[sel]][:, 1:].astype(np.float32)
            with self._lock:
                self._result = _Result(near, inside, dd, ab)
        except Exception:
            log.exception("tip refine failed")
            self.stats["errors"] += 1
        finally:
            with self._lock:
                self._pending = False

    @staticmethod
    def _pick(res, prompts, shape, radius_px):  # type: ignore[no-untyped-def]
        """프롬프트(두 손끝)를 모두 덮고 너무 크지 않은 마스크 중 모델 점수가 가장 높은 것."""
        h, w = shape
        best, best_s = None, -1.0
        for m, sc in zip(res.masks, res.scores):
            m = np.asarray(m, bool)
            area = float(m.sum())
            if area < 40 or area > 0.85 * h * w:
                continue
            ok = all(m[int(np.clip(round(p[1]), 0, h - 1)), int(np.clip(round(p[0]), 0, w - 1))] for p in prompts)
            if ok and sc > best_s:
                best, best_s = m, float(sc)
        if best is None and res.masks:   # 일부만 덮어도 가장 점수 높은 것은 쓴다 (점 하나가 어긋난 경우를 잡아내기 위해)
            i = int(np.argmax(res.scores))
            m = np.asarray(res.masks[i], bool)
            if 40 <= m.sum() <= 0.85 * h * w:
                best = m
        return best

    # ------------------------------------------------------------------
    def apply(self, tracker: TipTracker) -> None:
        """끝난 분할 결과가 있으면 추적기에 반영한다 (메인 스레드에서 프레임마다 호출)."""
        with self._lock:
            r, self._result = self._result, None
        if r is None:
            return
        tracker.set_skin(r.ab)
        hs = tracker.hand_size if tracker.hand_size > 0 else 80.0
        for name, tip in tracker.tips.items():
            if name not in r.inside or not tip.valid:
                continue
            if r.inside[name]:
                tip.off_mask = 0
                continue
            if r.dist[name] <= tracker.cfg.snap_dist * hs:
                tip.xy = 0.3 * tip.xy + 0.7 * r.name_pts[name]    # 마스크 안쪽 가장 가까운 곳으로 당김
                tip.off_mask = 0
                self.stats["snapped"] += 1
            else:
                tip.off_mask += 1
                if tip.off_mask >= 2:
                    tip.valid = False
                    self.stats["dropped"] += 1
        self.stats["applied"] += 1
