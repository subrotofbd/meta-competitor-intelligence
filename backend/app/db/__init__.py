"""Database access: engine, session factory, declarative base.

S0.1 -- empty by design. Populated in S0.2:
  - `base.py`      DeclarativeBase + shared metadata naming conventions
  - `session.py`   engine, sessionmaker, request/worker session dependency
  - `job_queue.py` PostgresJobQueue implementing the JobQueue Protocol

Important: the Postgres job queue is an IMPLEMENTATION of the `JobQueue`
Protocol, not a permanent architectural dependency. Do not import the jobs
table from business logic -- go through the Protocol so the queue stays
replaceable.

Migrations are Alembic (S0.2). No schema is created in S0.1.
"""
