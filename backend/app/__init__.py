"""Brandset Meta Competitor Intelligence -- backend application package.

Checkpoint S0.1 (foundation only).

This package intentionally contains NO business logic yet. It exists so that
`import app` resolves and the dependency/import graph is fixed early.

Layering (see ARCHITECTURE.md). Each layer may only import from the layers
above/left of it; providers and AI adapters are the only permitted external
boundaries, and they must never be imported outside the composition root.

    api        -> HTTP routers. Thin. No business logic.
    core       -> config, logging, security helpers. No framework imports.
    db         -> engine, session factory, base declarative, unit of work.
    models     -> SQLAlchemy ORM models. Persistence shape only.
    schemas    -> Pydantic request/response contracts.
    services   -> business logic, orchestration, use cases.
    providers  -> AdDataProvider / AIProvider implementations. (S1+)

Deferred and NOT present yet: database models, migrations, provider logic,
AI logic, authentication, API business endpoints, media storage.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
