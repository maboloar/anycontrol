"""사람 접근 감지 (시연 화면 자동 복귀용): Depth Anything 깊이를 배경 깊이와 비교해 '가까워진' 영역 비율을 잰다.

깊이 모델 값은 상대적(클수록 가까움)이고 프레임마다 스케일·이동이 달라서, 매번 배경에 아핀(a·d + b)으로 맞춘 뒤
남은 차이가 배경 범위의 thr 배 넘게 가까워진 픽셀만 센다. 맞춤은 두 번 돌려 두 번째는 크게 어긋난 픽셀(사람)을 뺀다.
배경은 reset() 뒤 첫 깊이로 잡고, 사람이 없을 때만 천천히 따라간다 (조명·카메라 미세 변화).
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

SIZE = (64, 48)


@dataclass
class PresenceConfig:
    thr: float = 0.12        # 배경 범위(5~95%) 대비 이만큼 가까워지면 '가까운 픽셀'
    min_frac: float = 0.06   # 가까운 픽셀이 화면의 이 비율을 넘으면 사람이 다가온 것
    learn: float = 0.05      # 사람이 없을 때 배경 갱신 비율


class PresenceWatch:
    def __init__(self, cfg: PresenceConfig | None = None) -> None:
        self.cfg = cfg or PresenceConfig()
        self.bg: np.ndarray | None = None
        self.near = 0.0
        self.present = False

    def reset(self) -> None:
        self.bg, self.near, self.present = None, 0.0, False

    def update(self, depth: np.ndarray) -> dict[str, float | bool]:
        d = cv2.resize(np.asarray(depth, np.float32), SIZE, interpolation=cv2.INTER_AREA)
        if self.bg is None or not np.isfinite(d).all():
            if np.isfinite(d).all():
                self.bg = d
            self.near, self.present = 0.0, False
            return self.state()
        bg = self.bg
        lo, hi = np.percentile(bg, [5, 95])
        span = max(float(hi - lo), 1e-6)
        keep = np.ones(d.shape, bool)
        for _ in range(2):  # 배경에 맞추기: 1차 전체, 2차는 크게 어긋난 곳(사람) 빼고
            A = np.stack([d[keep], np.ones(int(keep.sum()), np.float32)], 1)
            coef, *_ = np.linalg.lstsq(A, bg[keep], rcond=None)
            aligned = d * coef[0] + coef[1]
            keep = np.abs(aligned - bg) < self.cfg.thr * span
            if keep.mean() < 0.3:  # 화면 대부분이 바뀜 (카메라 이동 등): 판단 보류
                break
        diff = (aligned - bg) / span
        self.near = float((diff > self.cfg.thr).mean())
        self.present = bool(self.near >= self.cfg.min_frac and coef[0] > 0)
        if not self.present:
            self.bg = (1 - self.cfg.learn) * bg + self.cfg.learn * aligned
        return self.state()

    def state(self) -> dict[str, float | bool]:
        return {"ready": self.bg is not None, "near": round(self.near, 3), "present": self.present}
