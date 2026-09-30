"""Pydantic request/response contracts.

S0.1 -- empty by design. Arrives with the endpoints that need it (S1.1, S3.2).

Schemas are the API's public contract. They are separate from ORM models on
purpose so the external shape can evolve without silently changing storage,
and so nullable AI fields stay honestly nullable rather than being coerced
into a non-null type.
"""
