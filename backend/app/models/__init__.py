"""SQLAlchemy ORM models -- persistence shape only.

S0.1 -- empty by design. Tables arrive per checkpoint:
  S1.1  competitors, facebook_pages, collection_runs, provider_runs, raw_responses
  S2.1  ads, ad_snapshots
  S2.2  ad_creatives, ad_platforms, ad_countries, landing_pages, media_assets
  S3.1  ad_analysis, ai_jobs
  S0.2  jobs (queue implementation detail)

Rules that apply to every model added here:
  - UUID primary keys, `created_at` / `updated_at` on every table
  - `data_origin` and `evidence_class` where a value's provenance is known
  - `ad_snapshots` is APPEND-ONLY. Never update or delete an observation.
  - `media_assets` is content-addressed by sha256
No models are defined in S0.1.
"""
