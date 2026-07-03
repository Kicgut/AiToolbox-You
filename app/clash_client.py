from __future__ import annotations

from typing import AsyncIterator, Dict


class ClashClient:
    def __init__(self, base_url: str, secret: str) -> None:
        self.base_url = base_url
        self.secret = secret

    async def connect_connections_ws(self) -> AsyncIterator[Dict]:
        # TODO: implement WebSocket connection to ws://{base_url}/connections
        # yield parsed JSON messages
        raise NotImplementedError
