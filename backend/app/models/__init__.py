"""SQLAlchemy ORM models -- persistence shape only.

Tables arrive per checkpoint:
  S1.1  competitors, facebook_pages, collection_runs, provider_runs, raw_responses
  S1.2  jobs (queue implementation detail)
  S2.1  ads, ad_snapshots, seen_in_run
  S2.2  no new tables. Two nullable columns on ad_snapshots -- `copy_hash` and
        `creative_hash` -- plus duplicate detection grouping over them
  S2.3  ad_status_by_context -- status per ad *per Page + country*, because
        `ads` cannot hold it (see the module docstring). No column on `ads`
  S2.4  media_assets + ad_snapshot_media -- creative *references* only. No bytes
        are acquired, so `storage_key` is NULL on every row (see below)
  S3.1  ad_analysis, ai_jobs

**SUPERSEDED -- an earlier charter listed five S2.2 tables: `ad_creatives`,
`ad_platforms`, `ad_countries`, `landing_pages`, `media_assets`.** That claim was
removed from the list above so it cannot be read as current scope. **Four remain
deferred; `media_assets` was built in S2.4.**

  - `ad_creatives` cannot be built honestly yet.
    `app/providers/data/normalize.py` reads only the first creative body and
    flattens it into `RawAdRecord`, so the normalized contract exposes no
    card-level structure, and the committed corpus holds nine ads, every one
    single-bodied. A per-card table built now would fabricate rows rather than
    record observations. It needs a normalizer change first, which is its own
    checkpoint.
  - `ad_platforms`, `ad_countries` and `landing_pages` are per-dimension
    targeting tables, not attempted by S2.2 or S2.4.
  - `media_assets` **was** built, in S2.4 -- as creative *references*, not bytes.
    `AGENTS.md` section 12 forbids media byte downloads in S0-S3, so every row has
    `storage_key = NULL`, meaning "a reference is held, the bytes have not been
    acquired". `creative_hash` v1 remains a **provider-key** digest and is not
    reinterpreted; byte-based hashing would be a `creative_hash` v2 in a later,
    separately approved checkpoint. No `bytes`, `sha256` or `downloaded_at` column
    exists, because none could be truthfully populated.

This note is here because a stale charter is worse than no charter: a reader who
trusted the old S2.2 line would treat unbuilt tables as approved scope.

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
  - `media_assets` is identified by `UNIQUE(provider, provider_key)`. A provider
    key is an **identity hint**, not a content digest: nothing verifies that a
    provider keeps its keys stable, so a rotated key becomes a second row rather
    than a guessed merge. It is deliberately **parentless** -- a creative is shared
    across ads (the corpus has one key on two ads), so the observation
    relationship lives in the `ad_snapshot_media` link table instead of a foreign
    key here. There is no `sha256` column and no media bytes in S0-S3;
    `storage_key` is the future-facing content key, and it is NULL on every row
    S2.4 writes.
  - one parent per row. No ambiguous foreign keys, and no `ON DELETE CASCADE`
    anywhere in the collected-data chain. `media_assets` is the single exception
    and has no parent at all, as described above.

Importing this package registers every table on `Base.metadata`, which is what
`database/migrations/env.py` relies on for autogenerate.
"""

from app.models.ad_status import AdStatusByContext
from app.models.ads import Ad, AdSnapshot, SeenInRun
from app.models.jobs import Job
from app.models.media import AdSnapshotMedia, MediaAsset
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
    "AdSnapshotMedia",
    "AdStatusByContext",
    "CollectionRun",
    "CollectionRunStatus",
    "Competitor",
    "CountryCodeMixin",
    "FacebookPage",
    "Job",
    "MediaAsset",
    "ProviderRun",
    "ProviderRunStatus",
    "RawResponse",
    "SeenInRun",
    "TimestampMixin",
    "UuidPrimaryKeyMixin",
]
