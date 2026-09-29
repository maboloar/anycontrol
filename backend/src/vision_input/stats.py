"""가벼운 롤링 통계 (p50/p95, 주기 추정)."""

from __future__ import annotations

import threading
from collections import deque

import numpy as np


class Rolling:
    """최근 N개 값의 분위수. 여러 스레드에서 add/snapshot 해도 안전하다."""

    def __init__(self, size: int = 240) -> None:
        self._buf: deque[float] = deque(maxlen=size)
        self._lock = threading.Lock()

    def add(self, value: float) -> None:
        with self._lock:
            self._buf.append(float(value))

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()

    def __len__(self) -> int:
        return len(self._buf)

    def snapshot(self) -> dict[str, float | None]:
        with self._lock:
            if not self._buf:
                return {"p50": None, "p95": None, "max": None, "n": 0}
            arr = np.fromiter(self._buf, dtype=np.float64)
        p50, p95 = np.percentile(arr, [50, 95])
        return {"p50": round(float(p50), 3), "p95": round(float(p95), 3),
                "max": round(float(arr.max()), 3), "n": int(arr.size)}


class RateMeter:
    """이벤트 간격으로 fps 를 추정한다."""

    def __init__(self, size: int = 90) -> None:
        self._intervals = Rolling(size)
        self._last: float | None = None

    def tick(self, t: float) -> None:
        if self._last is not None and t > self._last:
            self._intervals.add((t - self._last) * 1000.0)
        self._last = t

    def reset(self) -> None:
        self._intervals.clear()
        self._last = None

    def snapshot(self) -> dict[str, float | None]:
        s = self._intervals.snapshot()
        fps = None if not s["p50"] else round(1000.0 / s["p50"], 2)
        return {"fps": fps, "interval_ms": s}
