"""시연 화면(60초 무입력) 자동 복귀용 사람 접근 감지 API (/api/idle)."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter

from ..engine import Engine
from ..pipeline import VisionProcessor
from ..presence import PresenceWatch


def make_router(engine: Engine, processor: VisionProcessor) -> APIRouter:
    r = APIRouter(prefix="/api/idle")
    watch = PresenceWatch()
    seen: dict[str, float] = {"t": 0.0}

    @r.get("/presence")
    async def presence(reset: bool = False) -> dict[str, Any]:
        """시연 화면이 떠 있는 동안 프런트가 약 3Hz 로 부른다. reset=1 이면 지금 장면을 배경으로 다시 잡는다.
        깊이 모델이 없거나 카메라 영상이 없으면 ready=false (프런트는 마우스·키보드로만 복귀)."""
        if reset:
            watch.reset()
            seen["t"] = 0.0
        svc = processor.depth
        if not svc.available:
            return {"ready": False, "reason": "model_missing", "present": False}
        now = time.monotonic()
        if not svc.busy and (svc.latest is None or now - svc.latest[1] > 0.25):
            frame = await asyncio.wrap_future(engine.submit(processor.snapshot))
            if frame is not None:
                svc.submit(frame.image, lambda depth: None)      # 결과는 svc.latest 에 남는다
        if svc.latest is None:
            return {"ready": False, "reason": "computing", "present": False}
        depth, t = svc.latest
        if t <= seen["t"] or now - t > 1.5:                     # 새 깊이가 없으면 지난 판단을 그대로
            return {**watch.state(), "present": watch.present and now - t <= 1.5}
        seen["t"] = t
        return watch.update(depth)

    return r
