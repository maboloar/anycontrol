"""마우스 모드와 긴급 정지 API."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from ..engine import Engine
from ..mapping.schema import Profile


class GameSetupBody(BaseModel):
    object_id: int = Field(ge=1)
    position: bool
    profile: Profile


class RealBody(BaseModel):
    on: bool


class TrackingBody(BaseModel):
    input_mirror: bool | None = None
    hand_occlusion: bool | None = None
    segmentation_enabled: bool | None = None
    segmentation_hz: float | None = Field(None, ge=.05, le=2.)
    hand_backend: Literal["vision", "mediapipe"] | None = Field(
        None, description="손 인식 엔진: vision(Apple Vision, 기본) | mediapipe. 실행 중에 바꿀 수 있다")


class HandDrawingBody(BaseModel):
    enabled: bool


class AutoStartBody(BaseModel):
    kind: Literal['hand', 'object', 'pen']
    object_id: int | None = Field(None, ge=1)


class AutoActionBody(BaseModel):
    session_id: str = Field(min_length=32, max_length=32)
    step_key: str | None = Field(None, max_length=32)


class CalBody(BaseModel):
    """책상 위 종이 네 모서리 (0..1 정규화, 순서 무관)와 종이 크기 (기본 A4 가로 놓기)."""

    points: list[list[float]] = Field(min_length=4, max_length=4)
    width_m: float = Field(0.297, gt=0.01, le=5)
    depth_m: float = Field(0.210, gt=0.01, le=5)

    @field_validator("points")
    @classmethod
    def _pts(cls, v: list[list[float]]) -> list[list[float]]:
        if any(len(p) != 2 or not all(0 <= c <= 1 for c in p) for p in v):
            raise ValueError("points must be 4 × [x, y] in 0..1")
        return v


class LineCalBody(BaseModel):
    """수평에 가까운 카메라에서 책상 좌우 기준선 두 끝점."""

    points: list[list[float]] = Field(min_length=2, max_length=2)

    @field_validator("points")
    @classmethod
    def _pts(cls, v: list[list[float]]) -> list[list[float]]:
        if any(len(p) != 2 or not all(0 <= c <= 1 for c in p) for p in v):
            raise ValueError("points must be 2 × [x, y] in 0..1")
        return v


from ..io.mouse import MouseSettings
from ..pipeline import VisionProcessor


def make_router(engine: Engine, processor: VisionProcessor) -> APIRouter:
    r = APIRouter(prefix="/api")

    async def on_engine(fn):  # type: ignore[no-untyped-def]
        return await asyncio.wrap_future(engine.submit(fn))

    @r.get('/auto-calibration')
    async def get_auto() -> dict[str, Any] | None:
        return await on_engine(lambda: None if processor.auto_calibration is None else processor.auto_calibration.state())

    @r.post('/auto-calibration/start')
    async def start_auto(body: AutoStartBody) -> dict[str, Any]:
        try:
            return await on_engine(lambda: processor.start_auto_calibration(body.kind, body.object_id))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @r.post('/auto-calibration/{action}')
    async def auto_action(action: Literal['record', 'back', 'apply', 'cancel', 'skip'], body: AutoActionBody) -> dict[str, Any]:
        def run():
            import time
            session = processor.auto_session(body.session_id)
            if action == 'record':
                session.record(body.step_key, time.monotonic())
            elif action == 'skip':
                session.skip(body.step_key, time.monotonic())
            elif action == 'back':
                session.back(time.monotonic())
            elif action == 'cancel':
                processor.cancel_auto_calibration()
            elif action == 'apply':
                return processor.apply_auto_calibration(body.session_id)
            return session.state()
        try:
            return await on_engine(run)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @r.get("/mouse")
    async def get_mouse() -> dict[str, Any]:
        return await on_engine(processor.mouse_info)

    @r.put("/mouse")
    async def put_mouse(s: MouseSettings) -> dict[str, Any]:
        try:
            return await on_engine(lambda: processor.set_mouse(s))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @r.get("/tracking")
    async def get_tracking() -> dict[str, Any]:
        tracker = processor.tracker
        return {"input_mirror": processor.input_mirror, "hand_occlusion": processor.hand_occlusion, "hands_available": processor.hands is not None,
                **processor.hand_backend_info(),
                "tier1_mode": getattr(tracker, "t1_mode", "off"),
                "tier1_stats": getattr(tracker, "t1_stats", {}),
                "tier1_error": getattr(tracker, "t1_error", None),
                "segmentation_enabled": getattr(tracker, "refresh_enabled", False),
                "segmentation_hz": getattr(getattr(tracker, "cfg", None), "refresh_hz", .5),
                "segmentation_effective_hz": getattr(tracker, "refresh_effective_hz", 0),
                "segmentation_ms": round(getattr(tracker, "refresh_ms", 0), 1),
                "segmentation_backend": getattr(tracker, "refresh_backend", None),
                "segmentation_stats": getattr(tracker, "refresh_stats", {}),
                "segmentation_error": getattr(tracker, "refresh_error", None)}

    @r.get("/drawing/hand")
    async def get_hand_drawing() -> dict[str, Any]:
        return await on_engine(processor.hand_drawing_info)

    @r.put("/drawing/hand")
    async def put_hand_drawing(b: HandDrawingBody) -> dict[str, Any]:
        try:
            return await on_engine(lambda: processor.set_hand_drawing(b.enabled))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @r.post("/drawing/hand/clear")
    async def clear_hand_drawing() -> dict[str, Any]:
        await on_engine(processor.hand_drawing.clear)
        return await on_engine(processor.hand_drawing_info)

    @r.put("/tracking")
    async def put_tracking(b: TrackingBody) -> dict[str, Any]:
        if b.hand_occlusion and processor.hands is None:
            raise HTTPException(409, "손 인식 모델이 없어 켤 수 없습니다")

        def _set():  # type: ignore[no-untyped-def]
            if b.input_mirror is not None:
                processor.set_input_mirror(b.input_mirror)
            if b.hand_occlusion is not None:
                processor.hand_occlusion = b.hand_occlusion
            if b.hand_backend is not None:
                processor.set_hand_backend(b.hand_backend)
            if b.segmentation_enabled is not None or b.segmentation_hz is not None:
                tracker = processor.tracker
                if tracker is not None and hasattr(tracker, "configure_refresh"):
                    tracker.configure_refresh(b.segmentation_enabled if b.segmentation_enabled is not None else tracker.refresh_enabled,
                                              b.segmentation_hz if b.segmentation_hz is not None else tracker.cfg.refresh_hz)

        try:
            await on_engine(_set)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return await get_tracking()

    @r.get("/calibration")
    async def get_cal() -> dict[str, Any]:
        return await on_engine(processor.calibration_info)

    @r.put("/calibration")
    async def put_cal(b: CalBody) -> dict[str, Any]:
        try:
            return await on_engine(lambda: processor.set_calibration(b.points, b.width_m, b.depth_m))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @r.put("/calibration/line")
    async def put_line_cal(b: LineCalBody) -> dict[str, Any]:
        try:
            return await on_engine(lambda: processor.set_touchpad_line(b.points))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @r.delete("/calibration", status_code=204)
    async def del_cal() -> None:
        await on_engine(processor.clear_calibration)

    @r.post("/stop")
    async def stop() -> dict[str, Any]:
        """긴급 정지: 마우스 끄기 + 눌린 버튼 모두 놓기 + 펜 떼기."""
        processor.real.off("stop")
        await on_engine(processor.emergency_stop)
        return await on_engine(processor.mouse_info)

    @r.post("/game-setup")
    async def game_setup(b: GameSetupBody) -> dict[str, Any]:
        def setup():
            if b.object_id not in processor.objects:
                raise ValueError("게임에 연결할 물체를 먼저 등록하세요.")
            if processor.auto_calibration and processor.auto_calibration.active:
                raise ValueError("자동 보정을 마치거나 취소하세요.")
            processor.real.off("user")
            settings = processor.mouse.settings.model_copy(update={
                "mode": "object" if b.position else "off", "object_id": b.object_id,
                "coordinate_mode": "image", "pen_relative": False,
                "hand_clicks": False, "object_tap": False})
            processor.set_mouse(settings)
            # 손 모델이 없어도 이동은 사용할 수 있다. 키보드 Space로 충격파를 쓸 수 있다.
            profile = b.profile
            if processor.hands is None:
                profile = profile.model_copy(update={"mappings": [m for m in profile.mappings if m.input.source != "hand"]})
            processor.set_profile(profile)
            processor.set_neutral(b.object_id)
            processor.set_output_mode("send")
            return {"mouse": processor.mouse_info(), "mapping": processor.mapping_info()}
        try:
            return await on_engine(setup)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @r.get("/real")
    async def real_info() -> dict[str, Any]:
        return processor.real.info(time.monotonic())

    @r.put("/real")
    async def put_real(b: RealBody) -> dict[str, Any]:
        try:
            if b.on:
                await on_engine(processor.enable_real)
            else:
                processor.real.off("user")  # 엔진이 바빠도 즉시 해제
            return await real_info()
        except PermissionError as exc:
            raise HTTPException(403, "손쉬운 사용 권한이 필요합니다. 권한 설정을 열어 허용하세요.") from exc
        except (ValueError, ImportError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @r.post("/real/permission")
    async def real_permission() -> dict[str, Any]:
        from ..io.macos import request_accessibility
        return {"trusted": await asyncio.to_thread(request_accessibility)}

    return r
