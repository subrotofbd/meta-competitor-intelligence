"""SQLAlchemy ORM models -- persistence shape only.

Tables arrive per checkpoint:
  S1.1  competitors, facebook_pages, collection_runs, provider_runs, raw_responses
  S1.2  jobs (queue implementation detail)
  S2.1  ads, ad_snapshots, seen_in_run
  S2.2  ad_creatives, ad_platforms, ad_countries, landing_pages, media_assets
  S2.3  ads.current_status (the derived status state machine)
  S3.1  ad_analysis, ai_jobs

`users`, `settings` and `audit_logs` appear in `ARCHITECTURE.md` under slice-1
"Identity" but are assigned to no checkpoint here, and they are deliberately
absent from S1.1: they exist to serve authentication, which AGENTS.md places
after S3, and a `users` table created now would mean choosing a password-hash
column before the hashing design exists. S1.1 implements the five tables that
collection orchestration actually reads and writes.

Rules that apply to every model added here:
  - UUID primary keys, `created_at` / `updated_at` on every table
  - `data_origin` and `evidence_class` where a value's provenance is known
  - `ad_snapshots` is APPEND-ONLY. Never update or delete an observation.
    `seen_in_run` is not: it is a link row and is upserted, because a provider
    can serve one ad more than once in a single run.
  - `evidence_class` is *derived* from `data_origin` by
    `providers.data.provenance.evidence_class_for`, not stored. No table in this
    package carries the column, and the mapping is centralised precisely so that
    no call site can pick its own class.
  - `media_assets` is content-addressed by sha256
  - one parent per row. No ambiguous foreign keys, and no `ON DELETE CASCADE`
    anywhere in the collected-data chain.

Importing this package registers every table on `Base.metadata`, which is what
`database/migrations/env.py` relies on for autogenerate.
"""

from app.models.ads import Ad, AdSnapshot, SeenInRun
from app.models.jobs import Job
from app.models.mixins import CountryCodeMixin, TimestampMixin, UuidPrimaryKeyMixin
from app.models.runs import (
    CollectionRun,
    CollectionRunStatus,
    ProviderRun,
    ProviderRunStatus,
    RawResponse,
)
from app.models.tracking import Competitor, FacebookPage

__all__ = [
    "Ad",
    "AdSnapshot",
    "CollectionRun",
    "CollectionRunStatus",
    "Competitor",
    "CountryCodeMixin",
    "FacebookPage",
    "Job",
    "ProviderRun",
    "ProviderRunStatus",
    "RawResponse",
    "SeenInRun",
    "TimestampMixin",
    "UuidPrimaryKeyMixin",
]
