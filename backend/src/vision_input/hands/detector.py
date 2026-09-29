"""손 랜드마크 (MediaPipe Hand Landmarker 0.10.35, CPU).

필요할 때만 켠다. 별도 스레드에서 최신 프레임만 처리하므로 추적 hot loop 를 막지 않는다.
1.0.x 는 macOS 에서 GPU 서비스 오류로 abort 되므로 0.10.35 에 고정했다.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from ..tracking import gpu

log = logging.getLogger(__name__)
MODEL = "hand_landmarker.task"

# 랜드마크 번호 (MediaPipe)
WRIST, THUMB_TIP, INDEX_MCP, INDEX_PIP, INDEX_TIP = 0, 4, 5, 6, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP = 9, 10, 12
RING_MCP, RING_PIP, RING_TIP, PINKY_MCP, PINKY_PIP, PINKY_TIP = 13, 14, 16, 17, 18, 20
CONNECTIONS = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11),
               (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (0, 17), (17, 18), (18, 19), (19, 20)]


@dataclass
class Hand:
    points: np.ndarray        # (21, 2) 이미지 정규화 좌표 0..1
    depth: np.ndarray         # (21,) 손목 기준 상대 깊이 (MediaPipe z)
    handedness: str           # "Left" | "Right" (카메라 기준)
    score: float


@dataclass
class HandFrame:
    t: float                  # 입력 프레임 캡처 시각 (monotonic)
    hands: list[Hand] = field(default_factory=list)
    ms: float = 0.0


def mediapipe_available() -> bool:
    try:
        import mediapipe  # noqa: F401
    except ImportError:
        return False
    return (gpu.MODELS_DIR / MODEL).is_file()



def available_backends() -> list[str]:
    """지금 쓸 수 있는 손 인식 엔진."""
    from . import vision

    return [b for b, ok in (("mediapipe", mediapipe_available()), ("vision", vision.available())) if ok]


def available() -> bool:
    return bool(available_backends())


def default_backend() -> str:
    """환경변수 VI_HAND_BACKEND (mediapipe|vision) 가 쓸 수 있으면 그것, 아니면 vision(기본), 없으면 mediapipe."""
    import os

    av = available_backends()
    want = os.environ.get("VI_HAND_BACKEND", "vision")
    return want if want in av else ("vision" if "vision" in av else ("mediapipe" if "mediapipe" in av else (av[0] if av else "vision")))


def make_detector(backend: str):  # type: ignore[no-untyped-def]
    """엔진 이름 → 검출기 (HandWorker 스레드 안에서 만든다)."""
    if backend == "mediapipe":
        return HandDetector()
    if backend == "vision":
        from .vision import AppleVisionDetector

        return AppleVisionDetector()
    raise ValueError(f"unknown hand backend: {backend}")

class HandDetector:
    """스레드 안전하지 않다. HandWorker 스레드 하나에서만 쓴다."""

    def __init__(self, max_hands: int = 2, min_conf: float = 0.5, width: int = 640) -> None:
        import mediapipe as mp

        opts = mp.tasks.vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(gpu.MODELS_DIR / MODEL)),
            running_mode=mp.tasks.vision.RunningMode.VIDEO, num_hands=max_hands,
            min_hand_detection_confidence=min_conf, min_hand_presence_confidence=min_conf,
            min_tracking_confidence=min_conf)
        self._mp = mp
        self._lm = mp.tasks.vision.HandLandmarker.create_from_options(opts)
        self.width = width
        self._last_ts = -1

    def detect(self, bgr: np.ndarray, t: float) -> HandFrame:
        s = time.perf_counter()
        h, w = bgr.shape[:2]
        if w > self.width:
            bgr = cv2.resize(bgr, (self.width, round(h * self.width / w)), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        ts = max(self._last_ts + 1, int(t * 1000))  # VIDEO 모드는 단조 증가 타임스탬프가 필요
        self._last_ts = ts
        r = self._lm.detect_for_video(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb), ts)
        hands = []
        for lms, hd in zip(r.hand_landmarks, r.handedness, strict=False):
            pts = np.array([[p.x, p.y] for p in lms], np.float32)
            z = np.array([p.z for p in lms], np.float32)
            hands.append(Hand(pts, z, hd[0].category_name, float(hd[0].score)))
        return HandFrame(t, hands, (time.perf_counter() - s) * 1000)

    def close(self) -> None:
        self._lm.close()


class HandWorker:
    """최신 프레임만 받아 손을 찾는 스레드. start()/stop() 으로 켜고 끈다."""

    def __init__(self, backend: str = "vision") -> None:
        self.backend = backend  # vision (Apple Vision, 기본) | mediapipe
        self._cond = threading.Condition()
        self._frame: tuple[np.ndarray, float] | None = None
        self._result: HandFrame | None = None
        self._thread: threading.Thread | None = None
        self._stop = False
        self.error: str | None = None
        self.rate_ms: list[float] = []
        self._retry_at = 0.0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._cond:
            if self.running or time.monotonic() < self._retry_at:
                return  # 종료 대기 중인 이전 스레드와 새 모델이 겹치지 않게 한다.
            self._stop, self.error, self._result, self._frame = False, None, None, None
            self._thread = threading.Thread(target=self._run, name="hands", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        with self._cond:
            self._stop = True
            self._frame = self._result = None
            thread = self._thread
            self._cond.notify_all()
        if thread is not None:
            thread.join(timeout)
        # 타임아웃이면 참조와 stop 플래그를 유지한다. 추론/초기화가 끝나면 스스로 닫힌다.
        with self._cond:
            if thread is self._thread and thread is not None and not thread.is_alive():
                self._thread = None

    def set_backend(self, backend: str) -> None:
        """엔진을 바꾼다. 돌고 있으면 멈추고 새 엔진으로 다시 시작한다 (이전 엔진의 결과는 버린다).
        이전 스레드가 늦게 끝나면 다음 프레임의 start() 에서 새 엔진으로 시작된다."""
        if backend not in available_backends():
            raise ValueError(f"손 인식 엔진 '{backend}' 를 쓸 수 없습니다 (사용 가능: {available_backends()})")
        if backend == self.backend:
            return
        was = self.running
        if was:
            self.stop()
        self.backend = backend
        self.error = None
        self._retry_at = 0.0
        if was:
            self.start()

    def offer(self, bgr: np.ndarray, t: float) -> None:
        if not self.running:
            return
        with self._cond:
            if self._stop:
                return
            self._frame = (bgr, t)
            self._cond.notify()

    def latest(self) -> HandFrame | None:
        return self._result

    def _run(self) -> None:
        try:
            det = make_detector(self.backend)
        except Exception as exc:  # 모델 파일·패키지 문제
            log.exception("hand detector init failed")
            self._retry_at = time.monotonic() + 2.0
            self.error = str(exc)
            return
        try:
            while True:
                with self._cond:
                    self._cond.wait_for(lambda: self._stop or self._frame is not None)
                    if self._stop:
                        return
                    bgr, t = self._frame  # type: ignore[misc]
                    self._frame = None
                res = det.detect(bgr, t)
                with self._cond:
                    if self._stop:
                        return
                    self._result = res
                    self.rate_ms.append(res.ms)
                    del self.rate_ms[:-60]
        except Exception as exc:
            log.exception("hand detection failed")
            self._retry_at = time.monotonic() + 2.0
            self.error = str(exc)
            self._result = None
        finally:
            try:
                det.close()
            except Exception as exc:
                log.exception("hand detector close failed")
                self.error = str(exc)
