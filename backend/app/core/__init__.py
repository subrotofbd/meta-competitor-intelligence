"""Cross-cutting concerns: configuration, logging, security helpers.

S0.1 -- empty by design. Populated in S0.2:
  - `config.py`  settings loaded from environment / .env via pydantic-settings
  - `logging.py` structured logging with run_id propagation (stdlib only)

This layer must not import from `api`, `db`, `models`, `schemas`, or
`services` -- it is the bottom of the dependency graph.
"""
