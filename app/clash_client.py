from __future__ import annotations

import json
from typing import AsyncIterator, Dict

import websockets


class ClashClient:
    def __init__(self, base_url: str, secret: str) -> None:
        self.base_url = base_url
        self.secret = secret

    async def connect_connections_ws(self) -> AsyncIterator[Dict]:
        url = f"ws://{self.base_url}/connections"
        headers = {}
        params = ""
        if self.secret:
            headers["Authorization"] = f"Bearer {self.secret}"
            params = f"?token={self.secret}"
        async with websockets.connect(url + params, extra_headers=headers) as ws:
            async for raw in ws:
                yield json.loads(raw)
