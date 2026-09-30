"""Test suite root.

S0.1 -- intentionally contains no tests. The first tests arrive in S1.1
(normalizer, hashing, URL canonicalisation) and S1.3 (provider contracts).

Layout, per ARCHITECTURE.md:
  backend/tests/unit/          fast, isolated
  backend/tests/integration/   real Postgres (testcontainers)
  backend/tests/contract/      per-provider, sanitized fixtures
  backend/tests/fixtures/      sanitized recorded provider payloads

Fixture hygiene: real Page IDs, Ad IDs, and personal data must be scrubbed
before anything under `fixtures/` is committed.
"""
