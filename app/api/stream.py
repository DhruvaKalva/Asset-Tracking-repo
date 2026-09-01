"""Server-sent events: the live half of the dashboard.

SSE rather than WebSockets because the traffic is one-way. It survives proxies,
needs no handshake protocol, reconnects on its own in the browser, and scales by
swapping the in-process bus for Redis pub/sub.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.adapters.bus import bus

router = APIRouter(tags=["stream"])

KEEPALIVE_SECONDS = 15


@router.get("/stream/assets")
async def stream_assets(request: Request):
    queue = bus.subscribe()

    async def generator():
        try:
            yield "retry: 3000\n\n"
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                    yield bus.encode_sse(message)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"  # keeps intermediaries from closing us
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx: do not buffer the stream
        },
    )


@router.get("/stream/health")
def stream_health():
    return {"subscribers": bus.subscriber_count}
