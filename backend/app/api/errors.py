"""Exception handlers: what an API failure is allowed to say.

## The rule

**No stack trace, ever, in any environment.** `main.py` does not set
`debug=True` today, but a future contributor might, and FastAPI's default debug
handler returns the traceback in the response body -- including local variable
values, which for this application means SQLAlchemy statements and, through them,
column values. Provider text, hashes and internal ids would ride along with it.

So the handlers are registered unconditionally rather than only in production. A
control that only exists in the configuration where it matters is a control that
is missing in the configuration where a developer is looking at a traceback.

## What is safe to say

- **404** -- the id was not found. The message repeats the caller's own id.
- **400** -- a filter value was not in its allowed set. The message names the field
  and the allowed values, because that is what lets a developer fix the request
  without reading this file.
- **500** -- "internal server error", and nothing else.

The 500 body deliberately carries no detail. `app.core.logging` is where a failure
gets diagnosed; an HTTP client is not.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


def register_exception_handlers(app: FastAPI) -> None:
    """Install the handlers on `app`.

    Args:
        app: The application to register on. Called once by `create_app`.
    """

    @app.exception_handler(Exception)
    async def unhandled(request: Request, error: Exception) -> JSONResponse:
        """Catch-all: log, answer 500, reveal nothing.

        Registered for bare `Exception` so an unforeseen failure cannot fall through
        to FastAPI's debug handler. The traceback goes to the log via `exc_info`,
        where a developer can find it, rather than to the caller, where it would
        disclose internals.

        `HTTPException` is re-raised rather than swallowed so the deliberate 400s and
        404s in `api/ads.py` keep their own status codes and messages.
        """
        from fastapi import HTTPException

        if isinstance(error, HTTPException):
            raise error

        import logging

        logging.getLogger(__name__).exception(
            "unhandled error serving %s %s", request.method, request.url.path
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "internal server error"},
        )
