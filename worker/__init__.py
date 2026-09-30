"""Worker package -- separate process from the API.

S0.1: entrypoint structure only. No jobs, no queue logic, no scheduling.

`python -m worker` is the intended entrypoint (ARCHITECTURE.md). The worker
consumes jobs through the `JobQueue` Protocol. The Postgres implementation
(S0.2) is replaceable -- do not let this package depend on the Postgres jobs
table directly.

Arrives later:
  S0.2  job claiming/acknowledgement, retries with capped backoff + jitter
  S1.2  collection orchestration
"""
