"""The S2.1 ad history tables: `ads`, `ad_snapshots`, `seen_in_run`.

## Why this migration creates `ads` without one of its foreign keys

`ads.latest_snapshot_id` points at `ad_snapshots.id`, and `ad_snapshots.ad_id`
points back at `ads.id`. The two tables reference each other, so they cannot both
be created with their constraints in one pass.

The chosen resolution is the ordinary one: create `ads` with the column present
but the constraint absent, create `ad_snapshots`, then add the constraint with
`ALTER TABLE`. That keeps every foreign key immediate and checkable, which a
deferrable constraint would not be, and it means the writer never depends on
constraint timing -- `ads` is simply inserted with a NULL latest snapshot, the
snapshot is written, and the pointer is then updated.

## Append-only enforcement

`AGENTS.md` section 8 says `ad_snapshots` is append-only, and the reason is
physical: a commercial ad that stops running is gone from Meta permanently
(`DATA_ACCESS.md`), so the row is often the only copy we will ever have. A rule
that only the application respects is a rule that one careless refactor breaks
silently, and this table is the one place where a silent write is
irrecoverable. So the invariant is enforced by the database, with the smallest
thing that does it: one trigger function and one trigger.

It is deliberately not more than that. There is no versioning scheme, no
soft-delete, no event log -- just a refusal to change or remove a row that
records an observation.

`seen_in_run` is deliberately **not** protected this way. It is a link, not an
observation: a provider can serve one ad twice in a single walk, and the honest
response to the second sighting is to correct the link. Its `updated_at` is
therefore expected to move, and `ad_snapshots.updated_at` never does.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

#: Revision identifiers, used by Alembic.
revision: str = "0004_ad_history"
down_revision: str | None = "0003_jobs_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: Refuses any UPDATE or DELETE on the append-only table. One function, used by
#: one trigger; there is nothing else to configure.
_APPEND_ONLY_GUARD = """
CREATE OR REPLACE FUNCTION ad_snapshots_append_only()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'ad_snapshots is append-only: % is not permitted. A new observation is a '
        'new row, and a deleted observation cannot be re-acquired from the '
        'provider.', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    # ------------------------------------------------------------------ ads
    # `latest_snapshot_id` is created here without its foreign key, because
    # `ad_snapshots` does not exist yet. It is added after that table.
    op.create_table(
        "ads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(255), nullable=False),
        sa.Column("meta_ad_id", sa.String(255), nullable=False),
        sa.Column(
            "data_origin",
            sa.Enum(
                "official_api",
                "public_ui",
                "third_party",
                "user_import",
                name="data_origin",
                native_enum=False,
                create_constraint=False,
            ),
            nullable=False,
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latest_snapshot_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ads")),
        sa.UniqueConstraint("provider", "meta_ad_id", name="uq_ads_provider_meta_ad_id"),
        sa.CheckConstraint("btrim(provider) <> ''", name=op.f("ck_ads_provider_not_blank")),
        sa.CheckConstraint("btrim(meta_ad_id) <> ''", name=op.f("ck_ads_meta_ad_id_not_blank")),
        sa.CheckConstraint(
            "last_seen_at >= first_seen_at",
            name=op.f("ck_ads_ad_sighting_order"),
        ),
    )

    # ---------------------------------------------------------- ad_snapshots
    op.create_table(
        "ad_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ad_id", sa.Uuid(), nullable=False),
        sa.Column("collection_run_id", sa.Uuid(), nullable=False),
        sa.Column("raw_ref", sa.Uuid(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("ad_status", sa.String(255), nullable=True),
        sa.Column("meta_delivery_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("normalized", JSONB, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ad_snapshots")),
        sa.UniqueConstraint("ad_id", "collection_run_id", name="uq_ad_snapshots_ad_run"),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_ad_snapshots_content_hash_is_sha256_hex"),
        ),
        # Every delete is RESTRICT, never CASCADE: an ad's history outlives any
        # part of the chain that produced it, and a cascade would take that
        # history with a single page deletion.
        sa.ForeignKeyConstraint(
            ["ad_id"],
            ["ads.id"],
            name="fk_ad_snapshots_ad_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["collection_run_id"],
            ["collection_runs.id"],
            name="fk_ad_snapshots_collection_run_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["raw_ref"],
            ["raw_responses.id"],
            name="fk_ad_snapshots_raw_ref",
            ondelete="RESTRICT",
        ),
    )

    # The remaining half of the circular reference. Immediate, not deferrable.
    op.create_foreign_key(
        "fk_ads_latest_snapshot_id",
        "ads",
        "ad_snapshots",
        ["latest_snapshot_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # ------------------------------------------------------------ seen_in_run
    op.create_table(
        "seen_in_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ad_id", sa.Uuid(), nullable=False),
        sa.Column("collection_run_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_seen_in_run")),
        sa.UniqueConstraint("ad_id", "collection_run_id", name="uq_seen_in_run_ad_run"),
        sa.ForeignKeyConstraint(
            ["ad_id"],
            ["ads.id"],
            name="fk_seen_in_run_ad_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["collection_run_id"],
            ["collection_runs.id"],
            name="fk_seen_in_run_collection_run_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["ad_snapshots.id"],
            name="fk_seen_in_run_snapshot_id",
            ondelete="RESTRICT",
        ),
    )

    # ------------------------------------------------------ append-only guard
    op.execute(_APPEND_ONLY_GUARD)
    op.execute(
        """
        CREATE TRIGGER trg_ad_snapshots_append_only
        BEFORE UPDATE OR DELETE ON ad_snapshots
        FOR EACH ROW EXECUTE FUNCTION ad_snapshots_append_only();
        """
    )


def downgrade() -> None:
    # Structured to be reversible without executing a DROP against a live
    # database. It is rendered offline with `alembic downgrade --sql` and never
    # run directly: the checkpoint rules require explicit consent for DROP, and
    # dropping `ad_snapshots` here would destroy the only copy of observations
    # that the providers have since stopped serving.
    op.execute("DROP TRIGGER IF EXISTS trg_ad_snapshots_append_only ON ad_snapshots;")
    op.execute("DROP FUNCTION IF EXISTS ad_snapshots_append_only();")

    op.drop_table("seen_in_run")
    op.drop_constraint("fk_ads_latest_snapshot_id", "ads", type_="foreignkey")
    op.drop_table("ad_snapshots")
    op.drop_table("ads")
