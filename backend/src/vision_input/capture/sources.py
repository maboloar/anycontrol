"""프레임 소스: 카메라, 동영상 파일, 합성 패턴.

모든 소스는 자기 스레드에서 프레임을 만들어 LatestSlot 에 넣는다.
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..stats import RateMeter
from .slot import Frame, LatestSlot

log = logging.getLogger(__name__)


class FrameSource(ABC):
    kind: str = "base"

    def __init__(self) -> None:
        self.slot = LatestSlot()
        self.rate = RateMeter()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._seq = 0
        self.status = "idle"      # idle | running | error | ended
        self.error: str | None = None
        self.actual_size: tuple[int, int] | None = None
        self.paused = False
        self.enabled = True
        self._last_image: np.ndarray | None = None

    # -- 수명 주기 --
    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_guarded, name=f"src-{self.kind}", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
        self.slot.close()
        if self.status == "running":
            self.status = "idle"

    def _run_guarded(self) -> None:
        try:
            self._run()
        except Exception as exc:  # 스레드가 조용히 죽지 않게
            log.exception("frame source crashed")
            self.status, self.error = "error", str(exc)

    def _emit(self, image: np.ndarray, t_capture: float | None = None, t_wall: float | None = None,
              *, frozen: bool = False) -> None:
        frozen = frozen or self.paused or not self.enabled
        if frozen and self._last_image is not None:
            image = self._last_image
        else:
            self._last_image = image
        now_m = time.monotonic() if t_capture is None else t_capture
        now_w = time.time() if t_wall is None else t_wall
        self._seq += 1
        self.rate.tick(now_m)
        h, w = image.shape[:2]
        self.actual_size = (w, h)
        self.slot.put(Frame(self._seq, image, now_m, now_w, frozen))

    def _emit_frozen(self) -> None:
        if self._last_image is not None:
            self._emit(self._last_image, frozen=True)

    @abstractmethod
    def _run(self) -> None: ...

    def info(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "status": self.status,
            "error": self.error,
            "size": self.actual_size,
            "rate": self.rate.snapshot(),
            "dropped": self.slot.dropped,
            "paused": self.paused,
            "enabled": self.enabled,
        }


class CameraSource(FrameSource):
    """OpenCV AVFoundation 백엔드 카메라. 연결이 끊기면 백오프로 다시 연다."""

    kind = "camera"

    def __init__(self, index: int = 0, width: int = 1280, height: int = 720,
                 fps: int = 30, mirror: bool = False, paused: bool = False, enabled: bool = True) -> None:
        super().__init__()
        self.index, self.width, self.height, self.fps, self.mirror = index, width, height, fps, mirror
        self.paused, self.enabled = paused, enabled

    def _open(self) -> cv2.VideoCapture | None:
        backend = cv2.CAP_AVFOUNDATION if hasattr(cv2, "CAP_AVFOUNDATION") else cv2.CAP_ANY
        cap = cv2.VideoCapture(self.index, backend)
        if not cap.isOpened():
            cap.release()
            return None
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 지원 안 하면 무시됨
        return cap

    def _run(self) -> None:
        backoff = 0.5
        while not self._stop.is_set():
            if not self.enabled:
                self.status = "off"
                self._emit_frozen()
                self._stop.wait(.1)
                continue
            cap = self._open()
            if cap is None:
                self.status = "error"
                self.error = f"camera {self.index} could not be opened (권한 또는 장치 확인)"
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 5.0)
                continue
            self.status, self.error, backoff = "running", None, 0.5
            fails = 0
            while not self._stop.is_set():
                if not self.enabled:
                    break  # 실제 장치를 해제한다. 다시 켜도 소스·등록 상태는 유지한다.
                if self.paused and self._last_image is not None:
                    self._emit_frozen()
                    self._stop.wait(.1)
                    continue
                ok, img = cap.read()
                if not ok or img is None:
                    fails += 1
                    if fails > 30:  # 약 1초 연속 실패 → 재연결
                        self.status, self.error = "error", "camera stopped delivering frames"
                        break
                    time.sleep(0.03)
                    continue
                fails = 0
                self._emit(img)
            cap.release()

    def info(self) -> dict[str, Any]:
        d = super().info()
        d.update(index=self.index, requested={"width": self.width, "height": self.height, "fps": self.fps},
                 mirror=self.mirror)
        return d


class VideoFileSource(FrameSource):
    """녹화 재생. realtime=True 면 파일 fps 에 맞춰 흘리고, False 면 소비자 속도에 맞춘다."""

    kind = "file"

    def __init__(self, path: str | Path, loop: bool = True, realtime: bool = True,
                 max_width: int | None = None, paused: bool = False) -> None:
        super().__init__()
        self.path, self.loop, self.realtime, self.max_width = Path(path), loop, realtime, max_width
        self.paused = paused

    def _run(self) -> None:
        cap = cv2.VideoCapture(str(self.path))
        if not cap.isOpened():
            cap.release()
            self.status, self.error = "error", f"cannot open {self.path}"
            return
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        period = 1.0 / fps
        self.status = "running"
        next_t = time.monotonic()
        still: np.ndarray | None = None
        rewound = False
        try:
            while not self._stop.is_set():
                if self.paused and still is not None:
                    # 선택 중에도 새 상태/오버레이를 전송하되 영상 위치는 그대로 유지한다.
                    self._emit(still)
                    self._stop.wait(.1)
                    next_t = time.monotonic()
                    continue
                ok, img = cap.read()
                if not ok or img is None:
                    if self.loop:
                        if rewound or not cap.set(cv2.CAP_PROP_POS_FRAMES, 0):
                            self.status, self.error = "error", "video contains no decodable frames or cannot rewind"
                            break
                        rewound = True
                        continue
                    self.status = "ended"
                    break
                rewound = False
                if self.realtime:
                    next_t += period
                    delay = next_t - time.monotonic()
                    if delay > 0:
                        self._stop.wait(delay)
                    else:
                        next_t = time.monotonic()
                elif self._seq > 0:
                    # 소비자가 이전 프레임을 가져갈 때까지 기다린다 (오프라인 평가: 프레임 손실 없음)
                    while not self._stop.is_set() and not self.slot.wait_consumed(self._seq, 0.1):
                        pass
                if self.max_width and img.shape[1] > self.max_width:  # 카메라 설정(1280)과 맞춘다
                    k = self.max_width / img.shape[1]
                    img = cv2.resize(img, (self.max_width, round(img.shape[0] * k)), interpolation=cv2.INTER_AREA)
                self._emit(img)
                still = img
        finally:
            cap.release()

    def info(self) -> dict[str, Any]:
        d = super().info()
        d.update(path=self.path.name, loop=self.loop, realtime=self.realtime, paused=self.paused)
        return d


class SyntheticSource(FrameSource):
    """카메라 없이 돌려 보는 합성 장면: 무늬 있는 카드와 단색 펜이 움직인다."""

    kind = "synthetic"

    def __init__(self, width: int = 1280, height: int = 720, fps: float = 30.0, paused: bool = False) -> None:
        super().__init__()
        self.width, self.height, self.fps = width, height, fps
        self.paused = paused
        rng = np.random.default_rng(7)
        self._bg = (rng.integers(150, 190, (height, width, 3), dtype=np.uint8))
        self._bg = cv2.GaussianBlur(self._bg, (0, 0), 3)

    def render(self, t: float) -> np.ndarray:
        img = self._bg.copy()
        w, h = self.width, self.height
        # 카드: 좌우 이동 + 회전
        cx, cy = w * (0.35 + 0.15 * np.sin(t * 0.9)), h * 0.5
        ang = 25 * np.sin(t * 0.6)
        box = cv2.boxPoints(((cx, cy), (w * 0.16, w * 0.11), ang)).astype(np.int32)
        cv2.fillConvexPoly(img, box, (40, 90, 200))
        cv2.putText(img, "VI", (int(cx - 30), int(cy + 15)), cv2.FONT_HERSHEY_SIMPLEX, 1.4,
                    (250, 250, 250), 3, cv2.LINE_AA)
        # 펜: 무늬 없는 막대, 깊이(크기) 변화
        s = 1.0 + 0.3 * np.sin(t * 0.7)
        px, py = w * 0.72, h * (0.5 + 0.1 * np.cos(t * 0.8))
        pen = cv2.boxPoints(((px, py), (w * 0.02 * s, h * 0.35 * s), 15 * np.cos(t * 0.5)))
        cv2.fillConvexPoly(img, pen.astype(np.int32), (30, 30, 30))
        return img

    def _run(self) -> None:
        self.status = "running"
        period = 1.0 / self.fps
        previous = next_t = time.monotonic()
        elapsed = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if not self.paused:
                elapsed += now - previous
            previous = now
            if self.paused and self._last_image is not None:
                self._emit_frozen()
            else:
                self._emit(self.render(elapsed))
            if self.paused:
                self._stop.wait(.1)
                previous = next_t = time.monotonic()
                continue
            next_t += period
            delay = next_t - time.monotonic()
            if delay > 0:
                self._stop.wait(delay)
            else:
                next_t = time.monotonic()

    def info(self) -> dict[str, Any]:
        d = super().info()
        d.update(requested={"width": self.width, "height": self.height, "fps": self.fps})
        return d
