"""Thread-safe, bounded in-process fan-out for already-persisted run events."""

from __future__ import annotations

import asyncio
import threading
from collections import defaultdict
from typing import Any


class RuntimeBroadcaster:
    """A single-runtime broadcaster; SQLite cursor replay is the reliability path."""

    def __init__(self) -> None:
        self._queues: dict[str, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any]]]]] = defaultdict(set)
        self._lock = threading.Lock()

    async def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        pair = (asyncio.get_running_loop(), queue)
        with self._lock:
            self._queues[run_id].add(pair)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            subscribers = self._queues.get(run_id)
            if subscribers is None:
                return
            for pair in tuple(subscribers):
                if pair[1] is queue:
                    subscribers.discard(pair)
            if not subscribers:
                self._queues.pop(run_id, None)

    def publish(self, event: dict[str, Any]) -> None:
        """Schedule non-blocking fan-out on each subscriber's owning event loop."""
        run_id = event.get("run_id")
        if not run_id:
            return
        with self._lock:
            subscribers = tuple(self._queues.get(run_id, ()))
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(self._publish_to_queue, queue, dict(event))
            except RuntimeError:
                # A closed browser loop is equivalent to disconnect; replay is
                # still available from SQLite for the next connection.
                self.unsubscribe(run_id, queue)

    @staticmethod
    def _publish_to_queue(queue: asyncio.Queue[dict[str, Any]], event: dict[str, Any]) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            # Do not block the producer. One gap marker tells the client to
            # recover the durable tail via its sequence cursor.
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                queue.put_nowait({"type": "stream.gap", "run_id": event.get("run_id"), "sequence_no": event.get("sequence_no")})
            except asyncio.QueueFull:
                pass


runtime_broadcaster = RuntimeBroadcaster()
