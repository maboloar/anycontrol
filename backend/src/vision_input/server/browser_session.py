"""마지막 웹앱 연결 종료 후 잠깐 기다렸다가 서버를 정상 종료한다."""
from __future__ import annotations

import asyncio
from collections.abc import Callable


class BrowserSession:
    def __init__(self, shutdown: Callable[[], None], grace_seconds: float = 5.):
        self.shutdown = shutdown
        self.grace_seconds = grace_seconds
        self.clients: set[int] = set()
        self.pending: asyncio.TimerHandle | None = None

    def connected(self, client_id: int) -> None:
        self.close()
        self.clients.add(client_id)

    def disconnected(self, client_id: int) -> None:
        if client_id not in self.clients:
            return
        self.clients.remove(client_id)
        if not self.clients:
            self.pending = asyncio.get_running_loop().call_later(self.grace_seconds, self._finish)

    def _finish(self) -> None:
        self.pending = None
        if not self.clients:
            self.shutdown()

    def close(self) -> None:
        if self.pending is not None:
            self.pending.cancel()
            self.pending = None
