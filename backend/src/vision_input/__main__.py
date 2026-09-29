"""CLI.

    python -m vision_input serve                 # 카메라 자동 선택 (연속성 카메라 우선)
    python -m vision_input serve --camera 0      # 장치 번호 지정
    python -m vision_input serve --synthetic     # 카메라 없이 합성 장면
    python -m vision_input cameras               # 장치 목록
"""

from __future__ import annotations

import argparse
import asyncio
import webbrowser
import json
import logging
import sys

from .config import LOOPBACK_HOSTS, Settings


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="vision_input")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="웹 서버 실행")
    s.add_argument("--host", default=None)
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--camera", type=int, default=None, help="장치 번호 (-1 = 자동)")
    s.add_argument("--width", type=int, default=None)
    s.add_argument("--height", type=int, default=None)
    s.add_argument("--fps", type=int, default=None)
    s.add_argument("--synthetic", action="store_true", help="합성 장면으로 실행")
    s.add_argument("--video", help="카메라 대신 영상 반복 재생 (프로젝트 폴더 안 경로)")
    s.add_argument("--allow-remote", action="store_true",
                   help="루프백이 아닌 주소 바인딩 허용 (인증이 없으므로 위험)")
    s.add_argument("--log-level", default="info")
    s.add_argument("--no-browser", action="store_true", help="브라우저 자동 열기 끄기")
    s.add_argument("--keep-alive", action="store_true", help="웹앱 창을 닫아도 서버 유지")
    s.add_argument("--hand-backend", choices=["vision", "mediapipe"], default=None,
                   help="손 인식 엔진 (기본 vision = Apple Vision). 실행 중에는 마우스 패널에서 바꿀 수 있음")

    sub.add_parser("cameras", help="카메라 목록")

    args = p.parse_args(argv)

    if args.cmd == "cameras":
        from .capture.devices import list_cameras
        print(json.dumps(list_cameras(), ensure_ascii=False, indent=2))
        return 0

    import uvicorn

    from .server.app import CameraSpec, FileSpec, SyntheticSpec, create_app

    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # EfficientTAM 이미지 분할기가 호출마다 root 로거에 INFO 두 줄을 남긴다 (재분할·모양 재획득 때 초당 수십 줄).
    _noisy = ("For numpy array image", "Computing image embeddings", "Image embeddings computed")
    for handler in logging.getLogger().handlers:
        handler.addFilter(lambda r: not (r.name == "root" and r.levelno <= logging.INFO
                                         and str(r.msg).startswith(_noisy)))
    settings = Settings()
    if args.hand_backend:
        import os
        os.environ["VI_HAND_BACKEND"] = args.hand_backend
    if args.host:
        settings.server.host = args.host
    if args.port:
        settings.server.port = args.port
    settings.server.allow_remote = settings.server.allow_remote or args.allow_remote
    if settings.server.host not in LOOPBACK_HOSTS and not settings.server.allow_remote:
        print(f"refusing to bind {settings.server.host}: 인증이 없는 로컬 전용 서버입니다. "
              "정말 필요하면 --allow-remote 를 쓰세요.", file=sys.stderr)
        return 2

    cam = settings.camera
    spec: CameraSpec | SyntheticSpec | FileSpec
    if args.video:
        from pathlib import Path
        spec = FileSpec(path=str(Path(args.video).resolve()))
        try:
            spec.resolved()
        except ValueError as exc:
            print(f"--video: {exc}", file=sys.stderr)
            return 2
    elif args.synthetic:
        spec = SyntheticSpec()
    else:
        spec = CameraSpec(
            index=cam.index if args.camera is None else args.camera,
            width=args.width or cam.width, height=args.height or cam.height,
            fps=args.fps or cam.fps, mirror=cam.mirror)
    from .server.browser_session import BrowserSession
    host = settings.server.host
    browser_host = "127.0.0.1" if host in ("0.0.0.0", "::") else f"[{host}]" if ":" in host else host
    url = f"http://{browser_host}:{settings.server.port}"
    server = None
    def shutdown():
        print("웹앱 연결이 모두 닫혀 AnyControl을 종료합니다.")
        server.should_exit = True
    session = None if args.keep_alive else BrowserSession(shutdown)
    app = create_app(settings, spec, browser_session=session)
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=settings.server.port,
                                          log_level=args.log_level, ws_max_size=1 << 20))
    print(f"AnyControl → {url}")
    if session is not None:
        print("마지막 웹앱 창을 닫으면 5초 후 종료합니다. 새로고침·재연결은 계속 사용할 수 있습니다.")
    async def open_when_ready():
        while not server.started and not server.should_exit:
            await asyncio.sleep(.1)
        if server.started and not server.should_exit:
            opened = await asyncio.to_thread(webbrowser.open, url, new=1)
            if not opened:
                print(f"브라우저를 자동으로 열지 못했습니다. 직접 접속하세요: {url}")
    async def serve():
        opener = None if args.no_browser else asyncio.create_task(open_when_ready())
        try:
            await server.serve()
        finally:
            if session is not None:
                session.close()
            if opener is not None:
                opener.cancel()
                await asyncio.gather(opener, return_exceptions=True)
    asyncio.run(serve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
