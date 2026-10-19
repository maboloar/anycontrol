import asyncio
from unittest.mock import Mock

from vision_input.server.browser_session import BrowserSession


def test_last_tab_closes_server_but_refresh_and_other_tabs_keep_it_alive():
    async def scenario():
        shutdown = Mock()
        s = BrowserSession(shutdown, grace_seconds=.02)
        s.connected(1)
        s.connected(2)
        s.disconnected(1)
        await asyncio.sleep(.03)
        shutdown.assert_not_called()
        s.disconnected(2)
        s.connected(3)  # refresh/reconnect cancels the pending exit
        await asyncio.sleep(.03)
        shutdown.assert_not_called()
        s.disconnected(3)
        await asyncio.sleep(.03)
        shutdown.assert_called_once()
    asyncio.run(scenario())


def test_no_exit_before_first_tab_and_cleanup_cancels_pending_exit():
    async def scenario():
        shutdown = Mock()
        s = BrowserSession(shutdown, grace_seconds=.01)
        s.disconnected(100)
        await asyncio.sleep(.02)
        shutdown.assert_not_called()
        s.connected(1)
        s.disconnected(1)
        s.close()
        await asyncio.sleep(.02)
        shutdown.assert_not_called()
    asyncio.run(scenario())


def test_bye_beacon_removes_the_client_and_starts_shutdown_even_if_the_socket_stays_open():
    import json
    import time as _time

    from fastapi.testclient import TestClient

    from vision_input.server.app import SyntheticSpec, create_app
    from vision_input.server.browser_session import BrowserSession
    from .test_server import RectSeg

    calls = []
    session = BrowserSession(lambda: calls.append(1), grace_seconds=.2)
    app = create_app(initial_source=SyntheticSpec(width=320, height=240, fps=30), segmenter=RectSeg(),
                     serve_frontend=False, browser_session=session)
    with TestClient(app) as c:
        with c.websocket_connect('/ws') as ws:
            client_id = json.loads(ws.receive_text())['data']['client_id']
            assert c.post('/api/bye', json={'client_id': client_id}).json() == {'ok': True}
            _time.sleep(.6)
            assert calls == [1]  # 소켓은 아직 열려 있어도 창을 닫는다는 신호만으로 종료 절차가 시작된다
        assert c.post('/api/bye', json={'client_id': 12345}).status_code == 200  # 모르는 번호는 무시
