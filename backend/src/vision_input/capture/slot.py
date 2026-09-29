"""최신 프레임 한 장만 보관하는 슬롯 (drop-oldest).

캡처 스레드는 절대 기다리지 않고 덮어쓴다. 소비자는 항상 가장 최근 프레임을 받는다.
처리가 느려져도 큐가 쌓여 지연이 늘어나는 일이 없다.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class Frame:
    seq: int            # 소스 안에서 단조 증가
    image: np.ndarray   # BGR uint8, (H, W, 3)
    t_capture: float    # time.monotonic() - 프레임을 받은 시각
    t_wall: float       # time.time() - 브라우저와 비교용 (같은 기기)
    frozen: bool = False  # 멈춘 미리보기: 추적·학습·입력은 진행하지 않는다.

    @property
    def size(self) -> tuple[int, int]:
        h, w = self.image.shape[:2]
        return w, h


class LatestSlot:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._frame: Frame | None = None
        self._consumed_seq = -1
        self._dropped = 0
        self._closed = False

    def put(self, frame: Frame) -> None:
        with self._cond:
            prev = self._frame
            if prev is not None and prev.seq > self._consumed_seq:
                self._dropped += 1  # 한 번도 읽히지 않고 덮어써짐
            self._frame = frame
            self._cond.notify_all()

    def latest(self) -> Frame | None:
        return self._frame

    def wait_newer(self, after_seq: int, timeout: float | None = None) -> Frame | None:
        """after_seq 보다 새로운 프레임을 기다린다. 시간 초과·종료 시 None."""
        with self._cond:
            self._cond.wait_for(
                lambda: self._closed or (self._frame is not None and self._frame.seq > after_seq),
                timeout,
            )
            f = self._frame
            if f is None or f.seq <= after_seq:
                return None
            self._consumed_seq = max(self._consumed_seq, f.seq)
            self._cond.notify_all()
            return f

    def wait_consumed(self, seq: int, timeout: float | None = None) -> bool:
        """seq 프레임이 소비될 때까지 기다린다 (오프라인 재생에서 프레임을 버리지 않기 위함)."""
        with self._cond:
            return self._cond.wait_for(lambda: self._closed or self._consumed_seq >= seq, timeout)

    @property
    def dropped(self) -> int:
        return self._dropped

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()
