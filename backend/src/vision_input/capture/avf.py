"""네이티브 AVFoundation 캡처 (macOS).

OpenCV 백엔드 대비 장점
- activeFormat 과 프레임 간격을 직접 지정 → 연속성 카메라 60fps 를 실제로 받는다
- 샘플 버퍼 PTS 로 실제 캡처 시각을 구한다 (지연 보상에 필요)
- Center Stage(자동 프레이밍)를 끈다. 켜져 있으면 물체가 가만히 있어도 화면이 움직인다
- alwaysDiscardsLateVideoFrames 로 캡처 큐 적체를 막는다
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import cv2
import numpy as np

from .sources import FrameSource
from .devices import discover_devices

log = logging.getLogger(__name__)

try:  # pragma: no cover - macOS 전용
    import AVFoundation as AVF
    import CoreMedia as CM
    import libdispatch
    import objc
    import Quartz
    from Foundation import NSObject

    AVAILABLE = True
except ImportError:  # pragma: no cover
    AVAILABLE = False


def _devices() -> list[Any]:
    return discover_devices()


def _pick_format(device: Any, width: int, height: int, fps: float) -> tuple[Any, float]:
    """요청 해상도에 가장 가깝고 fps 를 만족하는 포맷. 없으면 fps 를 최대한 맞춘다."""
    best, best_key, best_fps = None, None, 0.0
    for f in device.formats():
        dims = CM.CMVideoFormatDescriptionGetDimensions(f.formatDescription())
        max_fps = max((r.maxFrameRate() for r in f.videoSupportedFrameRateRanges()), default=0.0)
        size_err = abs(dims.width - width) + abs(dims.height - height)
        key = (0 if max_fps >= fps - 0.5 else 1, size_err, -max_fps)
        if best_key is None or key < best_key:
            best, best_key, best_fps = f, key, max_fps
    return best, min(fps, best_fps)


if AVAILABLE:  # pragma: no cover
    SampleBufferDelegate = objc.protocolNamed("AVCaptureVideoDataOutputSampleBufferDelegate")

    class _Delegate(NSObject, protocols=[SampleBufferDelegate]):
        def initWithOwner_(self, owner):  # noqa: N802 - ObjC 이름 규칙
            self = objc.super(_Delegate, self).init()
            if self is None:
                return None
            self.owner = owner
            return self

        def captureOutput_didOutputSampleBuffer_fromConnection_(self, output, sbuf, conn):  # noqa: N802
            try:
                self.owner._on_sample(sbuf)
            except Exception:
                log.exception("sample handling failed")

        def captureOutput_didDropSampleBuffer_fromConnection_(self, output, sbuf, conn):  # noqa: N802
            self.owner.late_drops += 1


class AVFCameraSource(FrameSource):
    kind = "camera"

    def __init__(self, index: int = 0, width: int = 1280, height: int = 720, fps: int = 60,
                 mirror: bool = False, device_id: str | None = None, desk_view: bool = False,
                 parent_id: str | None = None, paused: bool = False, enabled: bool = True) -> None:
        if not AVAILABLE:
            raise RuntimeError("AVFoundation (pyobjc) not available")
        super().__init__()
        self.index, self.width, self.height, self.fps, self.mirror = index, width, height, fps, mirror
        self.device_id, self.desk_view, self.parent_id = device_id, desk_view, parent_id
        self.paused, self.enabled = paused, enabled
        self.late_drops = 0
        self.device_name: str | None = None
        self.active_fps: float | None = None
        self.center_stage: bool | None = None
        self._pts_lag_ms: list[float] = []
        self._lag_lock = threading.Lock()
        self._clock = None

    # 캡처 콜백 (디스패치 큐 스레드)
    def _on_sample(self, sbuf: Any) -> None:
        if not self.enabled or (self.paused and self._last_image is not None):
            return
        now_m, now_w = time.monotonic(), time.time()
        pts = CM.CMSampleBufferGetPresentationTimeStamp(sbuf)
        lag = 0.0
        if self._clock is not None and pts.timescale:
            now = CM.CMClockGetTime(self._clock)
            if now.timescale:
                lag = max(0.0, now.value / now.timescale - pts.value / pts.timescale)
                if lag > 1.0:  # 시계가 다르면 무시
                    lag = 0.0
        pb = CM.CMSampleBufferGetImageBuffer(sbuf)
        if pb is None:
            return
        Quartz.CVPixelBufferLockBaseAddress(pb, 1)  # read-only
        try:
            h, w = Quartz.CVPixelBufferGetHeight(pb), Quartz.CVPixelBufferGetWidth(pb)
            bpr = Quartz.CVPixelBufferGetBytesPerRow(pb)
            base = Quartz.CVPixelBufferGetBaseAddress(pb)
            raw = np.frombuffer(base.as_buffer(bpr * h), dtype=np.uint8).reshape(h, bpr)
            bgra = raw[:, : w * 4].reshape(h, w, 4)
            img = cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR)  # 복사 → 잠금 해제 후에도 안전
        finally:
            Quartz.CVPixelBufferUnlockBaseAddress(pb, 1)
        with self._lag_lock:
            self._pts_lag_ms.append(lag * 1000.0)
            del self._pts_lag_ms[:-120]
        self._emit(img, t_capture=now_m - lag, t_wall=now_w - lag)

    def _run(self) -> None:
        while not self.enabled and not self._stop.is_set():
            self.status = "off"
            self._stop.wait(.1)
        if self._stop.is_set():
            return
        devs = _devices()
        device = next((d for d in devs if str(d.uniqueID()) == self.device_id), None) if self.device_id else (
            devs[self.index] if 0 <= self.index < len(devs) else None)
        if device is None:
            self.status, self.error = "error", f"camera index {self.index} not found ({len(devs)} devices)"
            return
        self.device_id = str(device.uniqueID())
        self.desk_view = 'DeskView' in str(device.deviceType())
        self.device_name = str(device.localizedName())

        # Center Stage 끄기 (앱이 제어)
        try:
            if hasattr(AVF.AVCaptureDevice, "setCenterStageControlMode_"):
                AVF.AVCaptureDevice.setCenterStageControlMode_(1)  # .app
                AVF.AVCaptureDevice.setCenterStageEnabled_(False)
            self.center_stage = bool(device.isCenterStageActive()) if hasattr(device, "isCenterStageActive") else None
        except Exception:
            log.debug("center stage control unavailable", exc_info=True)

        inp, err = AVF.AVCaptureDeviceInput.deviceInputWithDevice_error_(device, None)
        if inp is None:
            self.status, self.error = "error", f"cannot open device: {err}"
            return
        session = AVF.AVCaptureSession.alloc().init()
        output = AVF.AVCaptureVideoDataOutput.alloc().init()
        output.setVideoSettings_({Quartz.kCVPixelBufferPixelFormatTypeKey: Quartz.kCVPixelFormatType_32BGRA})
        output.setAlwaysDiscardsLateVideoFrames_(True)
        delegate = _Delegate.alloc().initWithOwner_(self)
        queue = libdispatch.dispatch_queue_create(b"vision_input.capture", None)
        output.setSampleBufferDelegate_queue_(delegate, queue)

        session.beginConfiguration()
        # 프리셋이 activeFormat 을 덮어쓰지 않게 한다 (연속성 카메라는 기본 프리셋에서 30fps 포맷으로 바뀜)
        if session.canSetSessionPreset_(AVF.AVCaptureSessionPresetInputPriority):
            session.setSessionPreset_(AVF.AVCaptureSessionPresetInputPriority)
        if not session.canAddInput_(inp) or not session.canAddOutput_(output):
            self.status, self.error = "error", "session rejected input/output"
            return
        session.addInput_(inp)
        session.addOutput_(output)
        session.commitConfiguration()

        fmt, fps = _pick_format(device, self.width, self.height, self.fps)
        ok, err = device.lockForConfiguration_(None)
        if ok and fmt is not None:
            device.setActiveFormat_(fmt)
            dur = CM.CMTimeMake(1000, int(round(fps * 1000)))
            device.setActiveVideoMinFrameDuration_(dur)
            device.setActiveVideoMaxFrameDuration_(dur)
        else:
            log.warning("could not configure format: %s", err)

        clock = session.synchronizationClock() if hasattr(session, "synchronizationClock") else None
        self._clock = clock or CM.CMClockGetHostTimeClock()

        # startRunning 이 세션 프리셋으로 포맷을 덮어쓰지 않도록 잠금을 유지한 채 시작한다 (Apple 권장)
        session.startRunning()
        if ok:
            device.unlockForConfiguration()
        dims = CM.CMVideoFormatDescriptionGetDimensions(device.activeFormat().formatDescription())
        d = device.activeVideoMinFrameDuration()
        self.active_fps = round(d.timescale / d.value, 2) if d.value else None
        log.info("camera %s active %dx%d @ %s fps", self.device_name, dims.width, dims.height, self.active_fps)
        self.status, self.error = "running", None
        self._session, self._delegate, self._queue = session, delegate, queue  # 참조 유지
        last_seq, last_change = self._seq, time.monotonic()
        running = True
        while not self._stop.wait(.1):
            if self.enabled != running:
                if self.enabled:
                    session.startRunning()
                    self.status, self.error = "running", None
                else:
                    session.stopRunning()
                    self.status = "off"
                running = self.enabled
                last_change = time.monotonic()
            if self.paused or not self.enabled:
                self._emit_frozen()
                last_seq, last_change = self._seq, time.monotonic()
                continue
            if self._seq != last_seq:
                last_seq, last_change = self._seq, time.monotonic()
                if self.status != "running":
                    self.status, self.error = "running", None
            elif time.monotonic() - last_change > 2.0:
                self.status, self.error = "error", "camera stopped delivering frames (연결 확인)"
        session.stopRunning()
        output.setSampleBufferDelegate_queue_(None, None)

    def info(self) -> dict[str, Any]:
        d = super().info()
        with self._lag_lock:
            lags = list(self._pts_lag_ms)
        d.update(index=self.index, name=self.device_name, backend="avfoundation",
                 device_id=self.device_id, desk_view=self.desk_view, parent_id=self.parent_id,
                 requested={"width": self.width, "height": self.height, "fps": self.fps},
                 active_fps=self.active_fps, late_drops=self.late_drops, mirror=self.mirror,
                 center_stage=self.center_stage,
                 pts_lag_ms=None if not lags else round(float(np.median(lags)), 2))
        return d
