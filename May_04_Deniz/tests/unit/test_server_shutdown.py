import unittest
from unittest.mock import AsyncMock, patch

from server.shutdown import ServerShutdownRoutine


class ServerShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_wait_for_clients_uses_configured_shutdown_grace(self):
        routine = ServerShutdownRoutine({"shutdown_grace_seconds": 12.5})

        with patch("server.shutdown.asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
            await routine._wait_for_clients()

        sleep_mock.assert_awaited_once_with(12.5)


if __name__ == "__main__":
    unittest.main()
