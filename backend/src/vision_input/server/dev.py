"""개발자 모드 전용 API (/api/dev). 깊이 모델 비교 실험. 접촉 판정 같은 실제 기능에는 쓰이지 않는다."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import depth_model as dm
from ..engine import Engine
from ..pipeline import VisionProcessor


class AutoReseg(BaseModel):
    enabled: bool | None = None
    long_s: float | None = Field(default=None, ge=3, le=600)


def make_router(engine: Engine, processor: VisionProcessor) -> APIRouter:
    r = APIRouter(prefix="/api/dev")
    downloader = dm.Downloader()
    model = processor.depth.model     # 펜 기울기·마우스 깊이와 같은 모델을 쓴다 (한 번만 적재)

    @r.get("/depth-model")
    async def depth_status() -> dict[str, Any]:
        return downloader.state()

    @r.post("/depth-model/download", status_code=202)
    async def depth_download() -> dict[str, Any]:
        """사용자가 개발자 모드에서 직접 눌렀을 때만 가중치(약 50MB, Apache-2.0)를 내려받는다."""
        downloader.start()
        return downloader.state()

    @r.get("/depth-map")
    async def depth_map() -> dict[str, Any]:
        """Depth Anything 으로 만든 깊이 맵 (개발자 보기: 카메라 영상 위에 겹쳐 본다). 요청이 올 때만, 최신이 0.3초보다 오래됐으면 새로 계산한다."""
        svc = processor.depth
        if not svc.available:
            return {"ready": False, "reason": "model_missing"}
        frame = await asyncio.wrap_future(engine.submit(processor.snapshot))
        now = time.monotonic()
        # 추적기의 배경 모델이 이미 ~6Hz 로 계산해 두므로 대개는 최신 결과를 그대로 돌려준다 (없거나 오래됐을 때만 직접 요청)
        if frame is not None and not svc.busy and (svc.latest is None or now - svc.latest[1] > 0.15):
            svc.submit(frame.image, lambda depth: None)           # 결과는 svc.latest 에 남는다
        if svc.latest is None:
            return {"ready": False, "reason": "no_frame" if frame is None else "computing", "error": svc.error}
        depth, t = svc.latest
        return {"ready": True, "age": round(now - t, 2), "ms": None if svc.model.last_ms is None else round(svc.model.last_ms, 1),
                **dm.depth_map_images(depth)}

    @r.get("/auto-reseg")
    async def auto_reseg_get() -> dict[str, Any]:
        """자동 분할 재지정 설정 (재추적 뒤 1초 정지, 그리고 long_s 초 정지마다 지금 프레임에서 다시 분할)."""
        return await asyncio.wrap_future(engine.submit(processor.auto_reseg_info))

    @r.put("/auto-reseg")
    async def auto_reseg_put(body: AutoReseg) -> dict[str, Any]:
        return await asyncio.wrap_future(engine.submit(lambda: processor.set_auto_reseg(body.enabled, body.long_s)))

    @r.get("/scene-map")
    async def scene_map() -> dict[str, Any]:
        """정지 배경 모델(색 + 깊이)의 전경 판정 (개발자 보기): 빨강 = 배경과 달라짐(물체·손), 파랑 = 배경 그대로, 투명 = 모름."""
        def snap():  # type: ignore[no-untyped-def]
            sc = getattr(processor.tracker, "scene", None)
            if sc is None or not sc.cfg.enabled:
                return {"ready": False, "reason": "disabled"}
            if sc.mean is None or sc.work is None:
                return {"ready": False, "reason": "no_frame"}
            lg = sc.logit(sc.t)          # 무효(카메라 이동·장면 변화)면 None: 격자만 그려 왜 꺼졌는지 보여 준다
            return {"ready": True, "info": {**sc.info(), "unstable_frac": sc.cfg.unstable_frac},
                    **dm.scene_map_images(lg, sc.work, getattr(sc, "cells", None), sc.cfg.cell_changed)}
        return await asyncio.wrap_future(engine.submit(snap))

    @r.get("/pen/{oid}/depth-compare")
    async def depth_compare(oid: int) -> dict[str, Any]:
        if not dm.is_available():
            return {"ready": False, "reason": "model_missing", **downloader.state()}

        def grab():  # type: ignore[no-untyped-def]
            pen = processor.pens.get(oid)
            if pen is None:
                raise KeyError(oid)
            frame, obj = processor.snapshot(), processor.objects.get(oid)
            return pen, None if frame is None else frame.image.copy(), None if obj is None else obj.out.mask

        try:
            pen, image, mask = await asyncio.wrap_future(engine.submit(grab))
        except KeyError as exc:
            raise HTTPException(404, "펜으로 등록된 물체가 아닙니다.") from exc
        if image is None:
            return {"ready": False, "reason": "no_frame"}
        try:
            # 모델 추론은 엔진(프레임 처리) 스레드를 막지 않게 따로 돌린다. 평면 계수는 읽기만 한다.
            return await asyncio.to_thread(pen.depth_compare, image, mask, model)
        except Exception as exc:  # Core ML 사용 불가 등
            raise HTTPException(409, f"깊이 모델 실행 실패: {exc}") from exc

    return r
