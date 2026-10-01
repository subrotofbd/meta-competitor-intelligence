"""ASGI application entrypoint.

Checkpoint S3.2: the read API for ads, search, and CSV export.

  GET /ads
  GET /ads/{id}
  GET /ads/{id}/snapshots
  GET /exports/ads.csv

Still absent by design:
  /healthz                     a liveness probe, and a real need before compose
                               can depend on this service
  /competitors, /collections   the operator surface, S1.1
  /ads/{id}/media/{asset_id}   byte serving. S2.4 stores references only, so there
                               is nothing to serve and the route would be a lie
  /ads/{id}/analyze            deliberately NOT here. Analysis is triggered by the
                               collection pipeline, never by a page view
  /auth/*, any login UI        a post-S3 seam (AGENTS.md section 12)

The factory is used so tests can build an isolated instance rather than importing a
module-level singleton.
"""

from fastapi import FastAPI

from app import __version__
from app.api.ads import router as ads_router
from app.api.errors import register_exception_handlers
from app.core.config import AppEnv, get_settings


def create_app(*, app_env: AppEnv | None = None) -> FastAPI:
    """Build the ASGI application.

    Args:
        app_env: Overrides the environment read from settings. Tests pass `LOCAL`
            explicitly so they never depend on the developer's `.env`, and so the
            docs-gating below is exercised deterministically rather than by whatever
            happens to be in the shell.

    Returns:
        The application, with the S3.2 routers and the exception handlers installed.
    """
    environment = app_env or get_settings().app_env

    # Docs and the OpenAPI schema are disabled in production. An S0.1 review item,
    # finally closed: with routes in place the schema discloses the whole data model,
    # and shipping that unauthenticated is a real disclosure rather than a cosmetic
    # one. No authentication is added here -- only the existing `app_env` setting.
    production = environment is AppEnv.PROD

    app = FastAPI(
        title="Brandset Meta Competitor Intelligence",
        version=__version__,
        docs_url=None if production else "/docs",
        redoc_url=None,
        openapi_url=None if production else "/openapi.json",
    )
    app.include_router(ads_router)
    register_exception_handlers(app)
    return app


app = create_app()
