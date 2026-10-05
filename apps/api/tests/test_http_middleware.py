"""StripNulMiddleware (Phase 7): NULs are removed from JSON bodies, and streaming responses still
stream. The middleware reads the body itself; it must then hand the real receive channel back, or
a streaming response (Ask Mo's SSE) sees an instant "disconnect" and ends with nothing sent."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.routing import Route

from momentum.core.http import StripNulMiddleware


async def _stream(request: Request) -> StreamingResponse:
    text = (await request.json())["text"]

    async def events() -> AsyncIterator[bytes]:
        for i in range(3):
            await asyncio.sleep(0.01)
            yield f"data: {text} {i}\n\n".encode()

    return StreamingResponse(events(), media_type="text/event-stream")


async def _call(body: bytes) -> bytes:
    app = StripNulMiddleware(
        Starlette(routes=[Route("/api/v1/chat", _stream, methods=["POST"])]),
        api_prefix="/api/v1",
    )
    sent: list[dict[str, Any]] = []
    first = True
    done = asyncio.Event()

    async def receive() -> dict[str, Any]:
        nonlocal first
        if first:
            first = False
            return {"type": "http.request", "body": body, "more_body": False}
        await done.wait()  # like a real server: no disconnect while the client is listening
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/api/v1/chat",
        "raw_path": b"/api/v1/chat",
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json"), (b"content-length", b"%d" % len(body))],
        "server": ("test", 80),
        "client": ("test", 1),
    }
    await asyncio.wait_for(app(scope, receive, send), timeout=5)
    done.set()
    return b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")


async def test_a_streaming_response_streams_to_the_end() -> None:
    out = await _call(json.dumps({"text": "hi"}).encode())
    assert out == b"data: hi 0\n\ndata: hi 1\n\ndata: hi 2\n\n"


async def test_nul_is_stripped_and_the_stream_still_completes() -> None:
    out = await _call(json.dumps({"text": "a\u0000b"}).encode())
    assert out.count(b"data: ab") == 3
