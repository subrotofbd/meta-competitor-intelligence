"""ASGI application entrypoint.

Checkpoint S0.1: this is a bare application object with NO routes.

Adding routes is checkpoint work:
  - /healthz                     S0.2 (liveness for compose)
  - /competitors, /collections   S1.1
  - /ads, /ads/{id}, /exports    S3.2
  - /auth/*                      post-S3 seam (no login UI in S0-S3)

The factory is used so tests can build an isolated instance rather than
importing a module-level singleton.
"""

from fastapi import FastAPI

from app import __version__


def create_app() -> FastAPI:
    """Build the ASGI application. No routes are registered in S0.1."""
    return FastAPI(
        title="Brandset Meta Competitor Intelligence",
        version=__version__,
        # Docs are useful locally but must never be exposed unauthenticated
        # in a deployed environment. Revisit with the auth seam.
        docs_url="/docs",
        redoc_url=None,
    )


app = create_app()
