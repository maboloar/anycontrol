"""엔진: 소스 → 프로세서(추적·매핑) → 브라우저.

스레드 배치
- 소스 스레드: 프레임을 LatestSlot 에 덮어쓴다.
- 엔진 스레드(hot loop): 최신 프레임만 처리. 추적 상태는 이 스레드에만 있다.
  외부 명령(물체 등록 등)은 submit() 으로 이 스레드에서 실행해 잠금이 필요 없다.
- 미리보기 인코더 스레드: JPEG 인코딩을 hot loop 밖으로 뺀다.
"""

from __future__ import annotations

import concurrent.futures as cf
import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

import cv2

from .capture import Frame, FrameSource
from .config import PreviewSettings
from .server.hub import Hub
from .server.protocol import PreviewHeader, encode_msg, pack_preview
from .stats import RateMeter, Rolling

log = logging.getLogger(__name__)


class Processor(Protocol):
    def process(self, frame: Frame) -> dict[str, Any] | None:
        """프레임 하나를 처리하고 브라우저로 보낼 상태(JSON 가능)를 돌려준다."""

    def reset(self) -> None: ...


class NullProcessor:
    def process(self, frame: Frame) -> dict[str, Any] | None:
        return None

    def reset(self) -> None:
        pass


class PreviewEncoder:
    """최신 프레임만 JPEG 로 인코딩해 hub 로 보낸다. 밀리면 오래된 것을 버린다."""

    def __init__(self, hub: Hub, settings: PreviewSettings) -> None:
        self.hub, self.settings = hub, settings
        self._slot: tuple[Frame, int] | None = None
        self._cond = threading.Condition()
        self._stop = False
        self.encode_ms = Rolling(120)
        self.rate = RateMeter()
        self.bytes_per_frame = Rolling(60)
        self._last_sent = 0.0
        self._thread = threading.Thread(target=self._run, name="preview-enc", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        self._thread.join(1.0)

    def offer(self, frame: Frame, flags: int = 0) -> None:
        now = time.monotonic()
        if now - self._last_sent < 1.0 / self.settings.max_fps * 0.9:
            return
        self._last_sent = now
        with self._cond:
            self._slot = (frame, flags)
            self._cond.notify()

    def _run(self) -> None:
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._stop or self._slot is not None)
                if self._stop:
                    return
                frame, flags = self._slot  # type: ignore[misc]
                self._slot = None
            t0 = time.perf_counter()
            img = frame.image
            if flags & 1:
                img = cv2.flip(img, 1)  # 반전은 표시만 바꾼다. 추적은 항상 같은 좌표계다.
            h, w = img.shape[:2]
            if w > self.settings.max_width:
                scale = self.settings.max_width / w
                img = cv2.resize(img, (self.settings.max_width, round(h * scale)), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, self.settings.jpeg_quality])
            if not ok:
                continue
            ph, pw = img.shape[:2]
            payload = pack_preview(PreviewHeader(frame.seq, frame.t_wall * 1000.0, pw, ph, flags), buf.tobytes())
            self.encode_ms.add((time.perf_counter() - t0) * 1000.0)
            self.bytes_per_frame.add(len(payload))
            self.rate.tick(time.monotonic())
            self.hub.publish_frame(payload)


class Engine:
    def __init__(self, hub: Hub, preview: PreviewSettings, processor: Processor | None = None,
                 telemetry_hz: float = 4.0) -> None:
        self.hub = hub
        self.processor: Processor = processor or NullProcessor()
        self.encoder = PreviewEncoder(hub, preview)
        self.telemetry_period = 1.0 / telemetry_hz
        self._source: FrameSource | None = None
        self._source_lock = threading.Lock()
        self._command_lock = threading.Lock()
        self._cmds: queue.SimpleQueue[tuple[Callable[[], Any], cf.Future[Any]]] = queue.SimpleQueue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # 계측
        self.proc_ms = Rolling(240)
        self.age_ms = Rolling(240)       # 캡처 → 처리 완료
        self.loop_rate = RateMeter()
        self.frames_processed = 0

    # -- 수명 주기 --
    def start(self) -> None:
        self.encoder.start()
        self._thread = threading.Thread(target=self._run, name="engine", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(2.0)
        self.encoder.stop()
        with self._source_lock:
            if self._source:
                self._source.stop()

    @property
    def source(self) -> FrameSource | None:
        return self._source

    def set_source(self, src: FrameSource) -> None:
        with self._source_lock:
            old, self._source = self._source, src
            src.start()
        if old is not None:
            old.stop()  # 엔진이 old.slot 에서 기다리는 중이면 close 로 즉시 깨어난다

    def submit(self, fn: Callable[[], Any]) -> cf.Future[Any]:
        """fn 을 엔진 스레드에서 프레임 사이에 실행한다."""
        fut: cf.Future[Any] = cf.Future()
        with self._command_lock:
            if self._stop.is_set():
                fut.cancel()
                return fut
            self._cmds.put((fn, fut))
        return fut

    # -- hot loop --
    def _drain_commands(self) -> None:
        while True:
            try:
                fn, fut = self._cmds.get_nowait()
            except queue.Empty:
                return
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                fut.set_result(fn())
            except Exception as exc:
                fut.set_exception(exc)

    def _run(self) -> None:
        try:
            self._run_loop()
        finally:
            with self._command_lock:
                self._stop.set()
            try:
                close = getattr(self.processor, "close", None)
                if close is not None:
                    close()
            finally:
                while True:
                    try:
                        _, fut = self._cmds.get_nowait()
                    except queue.Empty:
                        break
                    fut.cancel()

    def _run_loop(self) -> None:
        last_seq = -1
        current: FrameSource | None = None
        next_telemetry = time.monotonic()
        while not self._stop.is_set():
            self._drain_commands()
            src = self._source
            if src is not current:
                current, last_seq = src, -1
                self.processor.reset()
                view = getattr(self.processor, 'set_view_mode', None)
                if view is not None:
                    view(bool(getattr(src, 'desk_view', False)))
                self.proc_ms.clear()
                self.age_ms.clear()
                self.loop_rate.reset()
            now = time.monotonic()
            if now >= next_telemetry:
                next_telemetry = now + self.telemetry_period
                self.hub.publish_msg(encode_msg("telemetry", self.telemetry()))
            if src is None:
                time.sleep(0.05)
                continue
            frame = src.slot.wait_newer(last_seq, timeout=0.05)
            if frame is None:
                continue
            last_seq = frame.seq
            t0 = time.monotonic()
            frozen = frame.frozen or src.paused or not src.enabled
            try:
                process = getattr(self.processor, "process_frozen", self.processor.process) if frozen else self.processor.process
                state = process(frame)
            except Exception:
                log.exception("processor failed on frame %d", frame.seq)
                real = getattr(self.processor, "real", None)
                if real is not None:
                    real.off("error")
                state = None
            t1 = time.monotonic()
            self.proc_ms.add((t1 - t0) * 1000.0)
            self.age_ms.add((t1 - frame.t_capture) * 1000.0)
            self.loop_rate.tick(t1)
            self.frames_processed += 1
            if state is not None and self.hub.client_count:
                self.hub.publish_msg(encode_msg("state", {"seq": frame.seq, **state}))
            if self.hub.client_count:
                self.encoder.offer(frame, int(bool(getattr(src, "mirror", False))) | (2 if frozen else 0))

    def telemetry(self) -> dict[str, Any]:
        src = self._source
        return {
            "t_wall_ms": time.time() * 1000.0,
            "source": src.info() if src else None,
            "engine": {
                "proc_ms": self.proc_ms.snapshot(),
                "age_ms": self.age_ms.snapshot(),
                "rate": self.loop_rate.snapshot(),
                "frames": self.frames_processed,
            },
            "preview": {
                "encode_ms": self.encoder.encode_ms.snapshot(),
                "rate": self.encoder.rate.snapshot(),
                "kb_per_frame": (lambda s: None if s["p50"] is None else round(s["p50"] / 1024, 1))(
                    self.encoder.bytes_per_frame.snapshot()),
            },
            "clients": self.hub.client_count,
        }
