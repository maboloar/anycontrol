"""매핑·프로필·출력 모드 API.

- GET/PUT /api/mapping           현재 프로필 (PUT 은 검증 후 즉시 적용)
- PUT     /api/mapping/mode      observe(값만 보기) | send(가상 컨트롤러로 내보내기)
- GET     /api/mapping/schema    프로필 JSON Schema (프론트·프로필 편집기 공용)
- POST    /api/mapping/learn/start|stop   보여 주며 매핑하기
- GET/PUT/DELETE /api/profiles[/{name}]   저장된 프로필
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..engine import Engine
from ..mapping.schema import Profile
from ..mapping.store import ProfileStore
from ..pipeline import VisionProcessor


class ModeBody(BaseModel):
    mode: Literal["observe", "send"]


class LearnBody(BaseModel):
    object_id: int = Field(ge=1)


def make_router(engine: Engine, processor: VisionProcessor, store: ProfileStore) -> APIRouter:
    r = APIRouter(prefix="/api")

    async def on_engine(fn):  # type: ignore[no-untyped-def]
        return await asyncio.wrap_future(engine.submit(fn))

    @r.get("/mapping")
    async def get_mapping() -> dict[str, Any]:
        return await on_engine(processor.mapping_info)

    @r.put("/mapping")
    async def put_mapping(p: Profile) -> dict[str, Any]:
        return await on_engine(lambda: processor.set_profile(p))

    @r.put("/mapping/mode")
    async def put_mode(b: ModeBody) -> dict[str, Any]:
        return await on_engine(lambda: processor.set_output_mode(b.mode))

    @r.get("/mapping/schema")
    async def schema() -> dict[str, Any]:
        return Profile.model_json_schema()

    @r.post("/mapping/learn/start", status_code=204)
    async def learn_start(b: LearnBody) -> None:
        try:
            await on_engine(lambda: processor.learn_start(b.object_id))
        except KeyError as exc:
            raise HTTPException(404, "no such object") from exc

    @r.post("/mapping/learn/stop")
    async def learn_stop() -> dict[str, Any]:
        try:
            return await on_engine(processor.learn_stop)
        except LookupError as exc:
            raise HTTPException(409, "학습을 먼저 시작하세요") from exc

    @r.get("/profiles")
    async def list_profiles() -> list[dict[str, Any]]:
        return await asyncio.to_thread(store.list)

    @r.get("/profiles/{name}")
    async def load_profile(name: str) -> dict[str, Any]:
        try:
            p = await asyncio.to_thread(store.load, name)
        except KeyError as exc:
            raise HTTPException(404, "no such profile") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return p.model_dump(mode="json")

    @r.put("/profiles/{name}")
    async def save_profile(name: str, p: Profile) -> dict[str, Any]:
        try:
            p = Profile.model_validate({**p.model_dump(), "name": name})
            await asyncio.to_thread(store.save, p)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return p.model_dump(mode="json")

    @r.delete("/profiles/{name}", status_code=204)
    async def delete_profile(name: str) -> None:
        try:
            await asyncio.to_thread(store.delete, name)
        except KeyError as exc:
            raise HTTPException(404, "no such profile") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    return r
