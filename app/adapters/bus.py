"""In-process pub/sub that feeds the SSE stream.

Swap seam: replace publish/subscribe with Redis pub/sub (or NATS) and the API
layer stays identical -- that is how one box becomes N boxes behind a load
balancer without touching domain code.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

log = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called once at app startup so worker threads can publish safely."""
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish(self, topic: str, data: dict[str, Any]) -> None:
        """Safe to call from any thread (workers, simulator, request handlers)."""
        message = {"topic": topic, "data": data}
        if self._loop is None or not self._subscribers:
            return
        try:
            self._loop.call_soon_threadsafe(self._fanout, message)
        except RuntimeError:  # loop closed during shutdown
            pass

    def _fanout(self, message: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                # Slow client: drop the frame rather than stall the producer.
                log.debug("dropping SSE frame for slow subscriber")

    @staticmethod
    def encode_sse(message: dict[str, Any]) -> str:
        return f"event: {message['topic']}\ndata: {json.dumps(message['data'], default=str)}\n\n"


bus = EventBus()
