from __future__ import annotations

from typing import Dict, List


class Collector:
    def __init__(self, clash_client, db_conn, config) -> None:
        self.clash_client = clash_client
        self.db_conn = db_conn
        self.config = config

    async def run(self) -> None:
        # TODO: implement main collection loop
        raise NotImplementedError

    def get_live_snapshot(self) -> List[Dict]:
        return []

    def get_status(self) -> Dict:
        return {"connected": False, "last_update_ts": 0, "live_count": 0}
