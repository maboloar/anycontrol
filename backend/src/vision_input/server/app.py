"""FastAPI 앱.

보안 모델: 로컬 전용. 인증은 없다.
- 기본 바인딩은 127.0.0.1 (__main__ 에서 강제)
- Host 헤더 검사 → DNS rebinding 차단
- Origin 검사 → 다른 웹사이트가 브라우저를 통해 로컬 서버에 접속(CSWSH)하는 것을 차단
- CORS 헤더를 내보내지 않으므로 다른 출처는 응답을 읽을 수 없다
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from .. import PROTOCOL_VERSION, __version__
from ..capture import CameraSource, FrameSource, SyntheticSource, VideoFileSource
from ..capture.avf import AVAILABLE as AVF_AVAILABLE
from ..capture.avf import AVFCameraSource
from ..capture.devices import list_cameras, select_camera
from ..config import Settings
from ..engine import Engine
from ..pipeline import VisionProcessor
from ..tracking import gpu
from ..tracking.segment import Segmenter, default_segmenter
from ..mapping.store import ProfileStore
from .control import make_router as make_control_router
from .hub import Hub
from .browser_session import BrowserSession
from .mapping import make_router as make_mapping_router
from .objects import make_router
from .protocol import decode_msg, encode_msg

log = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).resolve().parents[4] / "frontend" / "dist"


# ---------------------------------------------------------------- sources
class CameraSpec(BaseModel):
    kind: Literal["camera"] = "camera"
    index: int = Field(-1, ge=-1, le=32, description="-1 = 자동 (연속성 카메라 우선)")
    width: int = Field(1280, ge=160, le=3840)
    height: int = Field(720, ge=120, le=2160)
    fps: int = Field(60, ge=1, le=240)
    mirror: bool = False
    device_id: str | None = Field(None, min_length=1, max_length=512)
    desk_view: bool = False
    paused: bool = False
    enabled: bool = True


class SyntheticSpec(BaseModel):
    kind: Literal["synthetic"] = "synthetic"
    width: int = Field(1280, ge=160, le=3840)
    height: int = Field(720, ge=120, le=2160)
    fps: float = Field(30.0, gt=0, le=240)
    paused: bool = False


PROJECT_ROOT = Path(__file__).resolve().parents[4]


class FileSpec(BaseModel):
    """녹화 재생 (개발·데모용). 경로는 프로젝트 폴더 안이어야 한다 (임의 파일 읽기 방지)."""

    kind: Literal["file"] = "file"
    path: str = Field(min_length=1, max_length=512)
    loop: bool = True
    paused: bool = False

    def resolved(self) -> Path:
        p = (PROJECT_ROOT / self.path).resolve() if not Path(self.path).is_absolute() else Path(self.path).resolve()
        if not p.is_relative_to(PROJECT_ROOT) or not p.is_file():
            raise ValueError("video must be an existing file inside the project folder")
        if p.suffix.lower() not in {".mov", ".mp4", ".m4v", ".avi", ".mkv"}:
            raise ValueError("unsupported video type")
        return p


SourceSpec = Annotated[CameraSpec | SyntheticSpec | FileSpec, Field(discriminator="kind")]


class PlaybackBody(BaseModel):
    paused: bool


class PowerBody(BaseModel):
    enabled: bool


def resolve_camera_index(index: int) -> int:
    if index >= 0:
        return index
    cams = list_cameras()
    for c in cams:
        if c["is_continuity"]:
            return int(c["index"])
    return 0


def build_source(spec: CameraSpec | SyntheticSpec | FileSpec) -> FrameSource:
    if isinstance(spec, SyntheticSpec):
        return SyntheticSource(spec.width, spec.height, spec.fps, paused=spec.paused)
    if isinstance(spec, FileSpec):
        return VideoFileSource(spec.resolved(), loop=spec.loop, realtime=True, max_width=1280, paused=spec.paused)
    if AVF_AVAILABLE:  # 네이티브: 포맷·fps 직접 제어, PTS 기반 캡처 시각
        cameras = list_cameras()
        if not cameras and not spec.desk_view and not spec.device_id:
            # 카메라가 없어도 서버/UI는 열어 영상·합성 소스로 바꿀 수 있게 한다.
            return AVFCameraSource(max(0, spec.index), spec.width, spec.height, spec.fps, spec.mirror,
                                   paused=spec.paused, enabled=spec.enabled)
        c = select_camera(cameras, spec.index, spec.device_id, spec.desk_view)
        desk = c.get('is_desk_view', False)
        return AVFCameraSource(c['index'], 1920 if desk else spec.width, 1440 if desk else spec.height,
                               min(spec.fps, 30) if desk else spec.fps, spec.mirror,
                               device_id=c['unique_id'], desk_view=desk, parent_id=c.get('parent_id'),
                               paused=spec.paused, enabled=spec.enabled)
    if spec.desk_view:
        raise ValueError('Desk View는 macOS AVFoundation 환경에서 사용할 수 있습니다')
    index = resolve_camera_index(spec.index)
    return CameraSource(index, spec.width, spec.height, spec.fps, spec.mirror, paused=spec.paused, enabled=spec.enabled)


def default_tracker_factory():  # type: ignore[no-untyped-def]
    """본 트래커가 있으면 쓰고, 없으면 등록만 되는 상태(추적 없음)로 둔다."""
    try:
        from ..tracking.vi_tracker import ViTracker
    except ImportError:
        log.warning("tracker unavailable; objects will not move")
        return None
    return ViTracker


# ---------------------------------------------------------------- origin guard
class OriginGuard:
    """Origin 헤더가 있으면 허용 목록에 있어야 한다. (브라우저는 교차 출처 요청에 항상 Origin 을 붙인다.)"""

    def __init__(self, app: ASGIApp, allowed: set[str]) -> None:
        self.app, self.allowed = app, allowed

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            origin = next((v.decode() for k, v in scope.get("headers", []) if k == b"origin"), None)
            if origin is not None and origin not in self.allowed:
                log.warning("rejected origin %s on %s", origin, scope.get("path"))
                if scope["type"] == "websocket":
                    await receive()  # websocket.connect
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    await send({"type": "http.response.start", "status": 403,
                                "headers": [(b"content-type", b"text/plain")]})
                    await send({"type": "http.response.body", "body": b"forbidden origin"})
                return
        await self.app(scope, receive, send)


# ---------------------------------------------------------------- app
def create_app(settings: Settings | None = None,
               initial_source: CameraSpec | SyntheticSpec | FileSpec | None = None,
               processor: VisionProcessor | None = None, serve_frontend: bool = True,
               segmenter: Segmenter | None = None, profile_store: ProfileStore | None = None,
               browser_session: BrowserSession | None = None) -> FastAPI:
    settings = settings or Settings()
    hub = Hub()
    processor = processor or VisionProcessor(default_tracker_factory())
    segmenter = segmenter or default_segmenter()
    engine = Engine(hub, settings.preview, processor, settings.telemetry_hz)
    start_spec = initial_source or CameraSpec(index=settings.camera.index, width=settings.camera.width,
                                              height=settings.camera.height, fps=settings.camera.fps,
                                              mirror=settings.camera.mirror)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        hub.bind_loop(asyncio.get_running_loop())
        warm = getattr(segmenter, "warmup", None)
        if warm is not None:  # 첫 분할의 컴파일(수 초)을 미리 끝낸다
            gpu.submit(warm)
        engine.start()
        try:
            engine.set_source(await asyncio.to_thread(build_source, start_spec))
            app.state.source_spec = start_spec
            yield
        finally:
            if browser_session is not None:
                browser_session.close()
            await asyncio.to_thread(engine.stop)

    app = FastAPI(title="AnyControl", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.settings, app.state.hub, app.state.engine = settings, hub, engine
    app.add_middleware(OriginGuard, allowed=settings.allowed_origins())
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts())

    app.include_router(make_router(engine, processor, segmenter))
    app.include_router(make_control_router(engine, processor))
    app.include_router(make_mapping_router(engine, processor, profile_store or ProfileStore()))

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__, "protocol": PROTOCOL_VERSION}


    @app.get("/api/cameras")
    async def cameras() -> list[dict[str, Any]]:
        return await asyncio.to_thread(list_cameras)

    @app.post('/api/source/desk-view/setup')
    async def desk_setup() -> dict[str, bool]:
        if not any(c.get('is_desk_view') for c in await asyncio.to_thread(list_cameras)):
            raise HTTPException(409, 'Desk View 장치를 찾을 수 없습니다. iPhone 연결을 확인하세요.')
        from ..capture.desk_setup import present_desk_view
        try:
            await asyncio.to_thread(present_desk_view)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {'opened': True}

    @app.get("/api/source")
    async def get_source() -> dict[str, Any]:
        src = engine.source
        return {"spec": app.state.source_spec.model_dump(), "info": src.info() if src else None}

    @app.put("/api/source")
    async def put_source(spec: Annotated[SourceSpec, Body()], reset: bool = False) -> dict[str, Any]:
        old = app.state.source_spec
        # 표시 반전·일시정지·전원만 바꾸면 같은 소스를 유지한다.
        if not reset and isinstance(old, CameraSpec) and isinstance(spec, CameraSpec) and old.model_dump(
                exclude={"mirror", "paused", "enabled"}) == spec.model_dump(exclude={"mirror", "paused", "enabled"}):
            def configure():
                src = engine.source
                if src is None:
                    raise ValueError("카메라 소스가 없습니다")
                src.mirror, src.paused, src.enabled = spec.mirror, spec.paused, spec.enabled
                processor.set_paused(spec.paused or not spec.enabled)
                app.state.source_spec = spec
                return {"spec": spec.model_dump(), "info": src.info()}
            return await asyncio.wrap_future(engine.submit(configure))
        try:
            src = await asyncio.to_thread(build_source, spec)
        except Exception as exc:
            raise HTTPException(400, f"cannot build source: {exc}") from exc
        await asyncio.to_thread(engine.set_source, src)
        app.state.source_spec = spec
        return {"spec": spec.model_dump(), "info": src.info()}

    @app.put("/api/source/playback")
    async def playback(body: PlaybackBody) -> dict[str, bool]:
        def configure():
            src = engine.source
            if src is None:
                raise ValueError("선택한 소스가 없습니다")
            src.paused = body.paused
            app.state.source_spec.paused = body.paused
            processor.set_paused(body.paused or not src.enabled)
            return {"paused": src.paused}
        return await asyncio.wrap_future(engine.submit(configure))

    @app.put("/api/source/power")
    async def power(body: PowerBody) -> dict[str, bool]:
        if not isinstance(app.state.source_spec, CameraSpec):
            raise HTTPException(409, "카메라를 선택한 상태에서만 전원을 조절할 수 있습니다")
        def configure():
            src = engine.source
            src.enabled = body.enabled
            app.state.source_spec.enabled = body.enabled
            processor.set_paused(not body.enabled or src.paused)
            return {"enabled": src.enabled}
        return await asyncio.wrap_future(engine.submit(configure))

    @app.post("/api/source/restart")
    async def restart() -> dict[str, Any]:
        if isinstance(app.state.source_spec, CameraSpec):
            raise HTTPException(409, "카메라는 일시정지·재생 또는 구도 적용을 사용하세요")
        return await put_source(app.state.source_spec.model_copy(update={"paused": True}))

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        ch = hub.add()
        if browser_session is not None:
            browser_session.connected(ch.id)

        async def sender() -> None:
            while True:
                msgs, frame = await ch.next_batch()
                for m in msgs:
                    await websocket.send_text(m)
                if frame is not None:
                    await websocket.send_bytes(frame)

        task = asyncio.create_task(sender())
        try:
            await websocket.send_text(encode_msg("hello", {"version": __version__, "protocol": PROTOCOL_VERSION,
                                                           "client_id": ch.id}))
            while True:
                text = await websocket.receive_text()
                try:
                    type_, data = decode_msg(text)
                except ValueError as exc:
                    ch.offer_msg(encode_msg("error", {"message": str(exc)}))
                    continue
                if type_ == "ping":
                    ch.offer_msg(encode_msg("pong", {"client_t": data.get("t"), "server_t": time.time() * 1000}))
                else:
                    ch.offer_msg(encode_msg("error", {"message": f"unknown type {type_}"}))
        except WebSocketDisconnect:
            pass
        finally:
            hub.remove(ch)
            if not hub.client_count:
                processor.real.off("disconnected")
            if browser_session is not None:
                browser_session.disconnected(ch.id)
            task.cancel()

    if serve_frontend and FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

    return app
