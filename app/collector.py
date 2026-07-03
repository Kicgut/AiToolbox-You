from __future__ import annotations

import asyncio
import itertools
import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from app import repository


@dataclass
class ConnState:
    last_upload: int
    last_download: int
    first_seen: bool = True


@dataclass
class LiveConn:
    id: str
    process_name: str
    host: str
    dest_port: int
    network: str
    direction: str
    chain: str
    rule: str
    speed_up: float
    speed_down: float
    total_up: int
    total_down: int
    start_ts: int
    _last_ts: float = field(default_factory=time.time, repr=False)


class Collector:
    def __init__(self, clash_client, db_conn, config) -> None:
        self.clash_client = clash_client
        self.db = db_conn
        self.config = config
        self.conn_states: Dict[str, ConnState] = {}
        self.minute_agg: Dict[Tuple[int, str, str], List[int]] = {}
        self.live_map: Dict[str, LiveConn] = {}
        self.connected: bool = False
        self.last_update_ts: float = 0
        self._backoff_iter = None
        self._task: asyncio.Task | None = None
        self._bg_tasks: List[asyncio.Task] = []

    def _next_backoff(self) -> float:
        if self._backoff_iter is None:
            self._backoff_iter = itertools.cycle(self.config.collector.ws_reconnect_backoff_sec)
        return next(self._backoff_iter)

    async def run(self) -> None:
        self._bg_tasks = [
            asyncio.create_task(self._flush_minute_loop()),
            asyncio.create_task(self._flush_connlog_loop()),
            asyncio.create_task(self._cleanup_loop()),
        ]
        while True:
            try:
                async for msg in self.clash_client.connect_connections_ws():
                    self._process_snapshot(msg, time.time())
            except Exception:
                self.connected = False
                await asyncio.sleep(self._next_backoff())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        for task in self._bg_tasks:
            task.cancel()

    def _process_snapshot(self, msg: dict, now: float) -> None:
        self.connected = True
        self.last_update_ts = now
        seen_ids = set()
        for conn in msg.get("connections", []):
            cid = conn["id"]
            seen_ids.add(cid)
            cur_up, cur_down = conn["upload"], conn["download"]
            metadata = conn.get("metadata", {})
            process_name = metadata.get("process") or "??"
            host = metadata.get("host") or metadata.get("destinationIP")
            network = metadata.get("network", "tcp")
            direction = self.classify_direction(conn.get("chains", []))
            chain = conn["chains"][0] if conn.get("chains") else "DIRECT"
            rule = conn.get("rule", "")
            prev = self.conn_states.get(cid)
            if prev is None:
                delta_up = delta_down = 0
                self.conn_states[cid] = ConnState(cur_up, cur_down)
            else:
                delta_up = max(0, cur_up - prev.last_upload)
                delta_down = max(0, cur_down - prev.last_download)
                prev.last_upload = cur_up
                prev.last_download = cur_down
                prev.first_seen = False
            minute_key = (int(now // 60 * 60), process_name, direction)
            agg = self.minute_agg.setdefault(minute_key, [0, 0])
            agg[0] += delta_up
            agg[1] += delta_down
            prev_live = self.live_map.get(cid)
            elapsed = now - prev_live._last_ts if prev_live else 1.0
            speed_up = delta_up / max(elapsed, 0.1)
            speed_down = delta_down / max(elapsed, 0.1)
            self.live_map[cid] = LiveConn(
                id=cid,
                process_name=process_name,
                host=host,
                dest_port=int(metadata.get("destinationPort", 0)),
                network=network,
                direction=direction,
                chain=chain,
                rule=rule,
                speed_up=speed_up,
                speed_down=speed_down,
                total_up=cur_up,
                total_down=cur_down,
                start_ts=int(metadata.get("start", now)),
                _last_ts=now,
            )
        closed = set(self.live_map) - seen_ids
        for cid in closed:
            del self.live_map[cid]
            self.conn_states.pop(cid, None)

    @staticmethod
    def classify_direction(chains: list[str]) -> str:
        return "direct" if chains and chains[-1] == "DIRECT" else "proxy"

    async def _flush_minute_loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.collector.minute_flush_interval_sec)
            agg = dict(self.minute_agg)
            self.minute_agg.clear()
            await repository.upsert_minute_stats(self.db, agg)

    async def _flush_connlog_loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.collector.connlog_flush_interval_sec)
            await repository.upsert_connection_log(self.db, self.live_map, self.conn_states)

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.collector.cleanup_interval_hours * 3600)
            await repository.delete_older_than(self.db, self.config.storage.retention_days)

    def get_live_snapshot(self) -> List[dict]:
        return [
            {
                "id": c.id,
                "process_name": c.process_name,
                "host": c.host,
                "dest_port": c.dest_port,
                "network": c.network,
                "direction": c.direction,
                "chain": c.chain,
                "rule": c.rule,
                "speed_up": c.speed_up,
                "speed_down": c.speed_down,
                "total_up": c.total_up,
                "total_down": c.total_down,
                "start_ts": c.start_ts,
            }
            for c in self.live_map.values()
        ]

    def get_status(self) -> dict:
        return {"connected": self.connected, "last_update_ts": self.last_update_ts, "live_count": len(self.live_map)}
