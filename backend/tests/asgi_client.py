"""A dependency-free ASGI driver, so the API tests need no HTTP client.

`fastapi.testclient.TestClient` requires `httpx`, which this project does not
install -- and adding a dependency to make tests run is a decision for a human, not
something a test file should do to itself. So this drives the ASGI application
directly: build a `scope`, feed it a `receive` that yields one request body, and
collect what the app sends back.

That is the whole protocol for the requests these tests make, and driving it
directly means the tests exercise the **real** application -- routing, dependency
overrides, exception handlers, status codes and all -- rather than calling route
functions and asserting on their return values, which would skip exactly the HTTP
contract the tests exist to pin.

`ASGITestClient` keeps the session dependency pointed at the fixture's
rolled-back transaction, so real rows written by a test are visible to a request and
nothing is ever committed.
"""

from __future__ import annotations

import json
from collections.abc import MutableMapping
from typing import Any, cast
from urllib.parse import urlencode

from sqlalchemy.orm import Session
from starlette.types import Message, Receive, Scope, Send

from app.db.session import get_session
from app.main import create_app


class ASGITestClient:
    """Drive a FastAPI app in-process, with no HTTP client installed."""

    def __init__(self, session: Session, *, app_env: Any = None) -> None:
        from app.core.config import AppEnv

        self._session = session
        self._app = create_app(app_env=app_env or AppEnv.LOCAL)
        # Overriding the one session dependency keeps the request inside the
        # fixture's outer transaction.
        self._app.dependency_overrides[get_session] = lambda: session

    def get(self, path: str, **params: Any) -> Response:
        """GET `path` with query parameters. `None` values are omitted."""
        query = {k: v for k, v in params.items() if v is not None}
        if query:
            path = f"{path}?{urlencode(query)}"
        return self._request("GET", path)

    def _request(self, method: str, path: str) -> Response:
        import asyncio

        body = json.dumps({}).encode()
        scope: dict[str, Any] = {
            "type": "http",
            # `spec_version` "2.4" is deliberate. Starlette branches on it: below
            # 2.4 it races `stream_response` against a task that waits for
            # `http.disconnect`, so a `receive()` that returns promptly cancels the
            # stream before it sends a single body chunk. A real server blocks in
            # `receive()`, which is why the race never fires in production and only
            # showed up here -- the CSV endpoint came back 200 with an empty body.
            # 2.4 takes the direct path, with no race to lose.
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path.split("?")[0],
            "raw_path": path.split("?")[0].encode(),
            "query_string": path.split("?")[1].encode() if "?" in path else b"",
            "root_path": "",
            "headers": [(b"host", b"testserver"), (b"content-type", b"application/json")],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }

        messages: list[Message] = [{"type": "http.request", "body": body, "more_body": False}]
        sent: list[Message] = []

        async def receive() -> MutableMapping[str, Any]:
            return messages.pop(0) if messages else {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            sent.append(message)

        # Starlette's `ServerErrorMiddleware` sends the handler's response and *then*
        # re-raises the original exception, so a 500 leaves both a complete response
        # and an exception in flight. That is ASGI behaviour, not a bug, and
        # `TestClient(raise_server_exceptions=False)` tolerates it in exactly this
        # way -- so the response is read from whatever was sent, and the exception
        # only matters if nothing was.
        try:
            # The scope, receive and send are built by hand, which is the whole point
            # of this driver, so they are cast at the single boundary where they meet
            # Starlette's ASGI types rather than suppressed at every use.
            asyncio.run(
                self._app(
                    cast("Scope", scope),
                    cast("Receive", receive),
                    cast("Send", send),
                )
            )
        except Exception:
            if not sent:
                raise

        status = 500
        headers: dict[str, str] = {}
        chunks: list[bytes] = []
        for message in sent:
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = {
                    key.decode().lower(): value.decode() for key, value in message["headers"]
                }
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))

        return Response(status_code=status, headers=headers, body=b"".join(chunks).decode("utf-8"))


class Response:
    """What an ASGI app sent back, with the accessors the tests actually use."""

    def __init__(self, status_code: int, headers: dict[str, str], body: str) -> None:
        self.status_code = status_code
        self.headers = headers
        self.body = body

    def json(self) -> Any:
        return json.loads(self.body)

    @property
    def text(self) -> str:
        return self.body

    def __repr__(self) -> str:
        return f"<Response {self.status_code} {self.body[:80]!r}>"
