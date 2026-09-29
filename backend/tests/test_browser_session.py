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
