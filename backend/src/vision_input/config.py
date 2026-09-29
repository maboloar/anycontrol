"""설정. 환경변수 VI_ 접두사로 덮어쓸 수 있다 (예: VI_CAMERA__INDEX=1)."""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class CameraSettings(BaseModel):
    index: int = -1  # -1 = 자동 (연속성 카메라 우선, 없으면 0)
    width: int = 1280
    height: int = 720
    fps: int = 60    # 연속성 카메라는 720p60 지원. 내장 카메라는 30 으로 떨어진다
    mirror: bool = False


class PreviewSettings(BaseModel):
    """브라우저로 보내는 미리보기 영상. 추적은 원본 해상도로 하고 미리보기만 줄인다."""

    max_width: int = Field(960, ge=160, le=3840)
    jpeg_quality: int = Field(70, ge=10, le=95)
    max_fps: float = Field(30.0, gt=0, le=120)


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8767
    # 개발 서버(Vite) 출처. 같은 포트의 자기 자신은 런타임에 자동 추가된다.
    dev_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]
    allow_remote: bool = False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VI_", env_nested_delimiter="__")

    camera: CameraSettings = CameraSettings()
    preview: PreviewSettings = PreviewSettings()
    server: ServerSettings = ServerSettings()
    telemetry_hz: float = 4.0

    def allowed_origins(self) -> set[str]:
        port = self.server.port
        own = {f"http://127.0.0.1:{port}", f"http://localhost:{port}", f"http://[::1]:{port}"}
        return own | set(self.server.dev_origins)

    def allowed_hosts(self) -> list[str]:
        if self.server.allow_remote:
            return ["*"]
        return ["127.0.0.1", "localhost", "[::1]", "testserver"]
