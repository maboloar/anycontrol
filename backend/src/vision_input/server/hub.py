"""브라우저 클라이언트 fan-out.

엔진 스레드에서 publish_* 를 부르면 이벤트 루프로 넘겨 각 클라이언트 채널에 넣는다.
프레임은 클라이언트마다 최신 1장만 유지하므로 느린 탭이 엔진이나 다른 탭을 막지 않는다.
"""

from __future__ import annotations

import asyncio
import itertools
from collections import deque


class ClientChannel:
    def __init__(self, max_msgs: int = 256) -> None:
        self.id = next(_ids)
        self._frame: bytes | None = None
        self._msgs: deque[str] = deque(maxlen=max_msgs)
        self._event = asyncio.Event()
        self.frames_dropped = 0

    # 이벤트 루프 스레드에서만 호출
    def offer_frame(self, data: bytes) -> None:
        if self._frame is not None:
            self.frames_dropped += 1
        self._frame = data
        self._event.set()

    def offer_msg(self, text: str) -> None:
        self._msgs.append(text)
        self._event.set()

    async def next_batch(self) -> tuple[list[str], bytes | None]:
        await self._event.wait()
        self._event.clear()
        msgs = list(self._msgs)
        self._msgs.clear()
        frame, self._frame = self._frame, None
        return msgs, frame


_ids = itertools.count(1)


class Hub:
    def __init__(self) -> None:
        self._clients: dict[int, ClientChannel] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def add(self) -> ClientChannel:
        ch = ClientChannel()
        self._clients[ch.id] = ch
        return ch

    def remove(self, ch: ClientChannel) -> None:
        self._clients.pop(ch.id, None)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    # -- 스레드 안전 publish --
    def publish_frame(self, data: bytes) -> None:
        self._call(self._fanout_frame, data)

    def publish_msg(self, text: str) -> None:
        self._call(self._fanout_msg, text)

    def _call(self, fn, arg) -> None:  # type: ignore[no-untyped-def]
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(fn, arg)
        except RuntimeError:  # 루프 종료 중
            pass

    def _fanout_frame(self, data: bytes) -> None:
        for ch in list(self._clients.values()):
            ch.offer_frame(data)

    def _fanout_msg(self, text: str) -> None:
        for ch in list(self._clients.values()):
            ch.offer_msg(text)
