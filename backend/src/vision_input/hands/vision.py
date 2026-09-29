"""Apple Vision 손 자세 엔진 (VNDetectHumanHandPoseRequest, macOS 전용).

랜드마크 21개를 MediaPipe와 같은 번호로 반환한다. 깊이(z)는 0으로 채우며
앱의 깊이 신호는 2D 손 크기로 추정한다. 좌우는 Vision의 chirality를 쓴다.
엄지가 가려지면 높은 신뢰도의 잘못된 엄지 위치가 나올 수 있어 집기 판정에 한계가 있다.
"""

from __future__ import annotations

import logging
import time

import cv2
import numpy as np

from .detector import Hand, HandFrame

log = logging.getLogger(__name__)

# MediaPipe 21 점 번호 순서 (손목, 엄지 4, 검지 4, 중지 4, 약지 4, 새끼 4)
JOINTS = ["VNHLKWRI", "VNHLKTCMC", "VNHLKTMP", "VNHLKTIP", "VNHLKTTIP",
          "VNHLKIMCP", "VNHLKIPIP", "VNHLKIDIP", "VNHLKITIP",
          "VNHLKMMCP", "VNHLKMPIP", "VNHLKMDIP", "VNHLKMTIP",
          "VNHLKRMCP", "VNHLKRPIP", "VNHLKRDIP", "VNHLKRTIP",
          "VNHLKPMCP", "VNHLKPPIP", "VNHLKPDIP", "VNHLKPTIP"]
# 제스처가 쓰는 점: 손목, 엄지 끝, 네 손가락의 뿌리·PIP·끝. 이게 모두 있어야 손으로 인정한다.
NEEDED = (0, 4, 5, 6, 8, 9, 10, 12, 13, 14, 16, 17, 18, 20)
_CHAINS = ((1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20))
_CHIRALITY = {-1: "Left", 1: "Right"}


def available() -> bool:
    import sys

    if sys.platform != "darwin":
        return False
    try:
        import Vision  # noqa: F401
    except ImportError:
        return False
    return True


def hand_from_joints(joints: dict[int, tuple[float, float, float]], chirality: int = 0, min_conf: float = 0.05,
                     min_score: float = 0.3) -> Hand | None:
    """{관절 번호: (x, y, 신뢰도)} (좌상단 원점 0..1) → Hand. 제스처에 필요한 점이 빠지면 None.

    신뢰도가 min_conf 미만인 점은 없는 것으로 본다. 필요하지 않은 점이 빠지면 같은 손가락의 앞 관절 위치로 채운다.
    score = 필요한 점들의 평균 신뢰도 (min_score 미만이면 버린다)."""
    ok = {k: v for k, v in joints.items() if v[2] >= min_conf}
    if any(k not in ok for k in NEEDED):
        return None
    score = float(np.mean([ok[k][2] for k in NEEDED]))
    if score < min_score:
        return None
    pts = np.zeros((21, 2), np.float32)
    pts[0] = ok[0][:2]
    for chain in _CHAINS:
        prev = 0
        for k in chain:
            pts[k] = ok[k][:2] if k in ok else pts[prev]
            prev = k
    return Hand(pts, np.zeros(21, np.float32), _CHIRALITY.get(int(chirality), "Unknown"), score)


class AppleVisionDetector:
    """HandDetector 와 같은 사용법: detect(bgr, t) → HandFrame. 스레드 하나에서만 쓴다."""

    def __init__(self, max_hands: int = 2, width: int = 640, min_conf: float = 0.05, min_score: float = 0.3) -> None:
        import Quartz
        import Vision

        self._Q, self._V = Quartz, Vision
        self.width, self.min_conf, self.min_score = width, min_conf, min_score
        self._req = Vision.VNDetectHumanHandPoseRequest.alloc().init()
        self._req.setMaximumHandCount_(max_hands)
        self._cs = Quartz.CGColorSpaceCreateDeviceRGB()

    def detect(self, bgr: np.ndarray, t: float) -> HandFrame:
        s = time.perf_counter()
        h, w = bgr.shape[:2]
        if w > self.width:
            bgr = cv2.resize(bgr, (self.width, round(h * self.width / w)), interpolation=cv2.INTER_AREA)
        rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        hh, ww = rgb.shape[:2]
        data = rgb.tobytes()
        prov = self._Q.CGDataProviderCreateWithData(None, data, len(data), None)
        img = self._Q.CGImageCreate(ww, hh, 8, 24, ww * 3, self._cs, self._Q.kCGBitmapByteOrderDefault, prov, None,
                                    False, self._Q.kCGRenderingIntentDefault)
        handler = self._V.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None)
        ok, err = handler.performRequests_error_([self._req], None)
        hands: list[Hand] = []
        if ok:
            for obs in self._req.results() or []:
                pts, _ = obs.recognizedPointsForGroupKey_error_(self._V.VNRecognizedPointGroupKeyAll, None)
                joints = {}
                for k, name in enumerate(JOINTS):
                    p = pts.get(name)
                    if p is not None:
                        loc = p.location()
                        joints[k] = (float(loc.x), 1.0 - float(loc.y), float(p.confidence()))
                hand = hand_from_joints(joints, int(obs.chirality()), self.min_conf, self.min_score)
                if hand is not None:
                    hands.append(hand)
        elif err is not None:
            log.warning("vision hand pose failed: %s", err)
        return HandFrame(t, hands, (time.perf_counter() - s) * 1000)

    def close(self) -> None:
        pass
