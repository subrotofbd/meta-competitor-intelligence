"""The jobs table for durable collection orchestration.

S1.2 adds the queue persistence layer that S0.3 declared but could not implement
without a table. Every operation in `JobQueue` now has a real implementation
using PostgreSQL row locking (`SELECT ... FOR UPDATE SKIP LOCKED`).

The table name is hard-coded as `jobs` (not configurable) because this is the
single queue implementation; multiple queues would each need their own table and
their own `PostgresJobQueue` instance. The S0.3 validation of the table name as
a bare lowercase identifier is preserved as a safety invariant.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

#: Revision identifiers, used by Alembic.
revision: str = "0003_jobs_table"
down_revision: str | None = "0002_collection_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
        ),
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
        sa.Column(
            "kind",
            sa.String(128),
            nullable=False,
        ),
        sa.Column(
            "payload",
            JSONB,
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "worker_id",
            sa.String(128),
            nullable=True,
        ),
        sa.Column(
            "attempt",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "error_type",
            sa.String(64),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )

    # Indexes for the access patterns the queue uses:
    # 1. Claiming: find pending jobs whose lease has expired (or is NULL)
    op.create_index(
        "ix_jobs_status_lease",
        "jobs",
        ["status", "lease_expires_at"],
        unique=False,
    )
    # 2. Worker lookups: find all jobs a worker currently holds
    op.create_index(
        "ix_jobs_worker_id",
        "jobs",
        ["worker_id"],
        unique=False,
    )
    # 3. Kind-based routing/filtering
    op.create_index(
        "ix_jobs_kind",
        "jobs",
        ["kind"],
        unique=False,
    )

    # Check constraints for data integrity
    op.create_check_constraint(
        "ck_jobs_status",
        "jobs",
        "status IN ('pending', 'running', 'completed', 'failed', 'dead')",
    )
    op.create_check_constraint(
        "ck_jobs_attempt_nonneg",
        "jobs",
        "attempt >= 0",
    )
    op.create_check_constraint(
        "ck_jobs_finished_at_required",
        "jobs",
        "status NOT IN ('completed', 'failed', 'dead') OR finished_at IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_jobs_running_requires_lease",
        "jobs",
        "status != 'running' OR (worker_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_jobs_error_message_on_failure",
        "jobs",
        "status NOT IN ('failed', 'dead') OR error_message IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_jobs_error_message_max",
        "jobs",
        "error_message IS NULL OR length(error_message) <= 2000",
    )


def downgrade() -> None:
    # The downgrade is structured to be reversible without executing DROP against
    # a live database. It is rendered offline via `alembic downgrade --sql` and
    # never run directly (checkpoint rules require explicit consent for DROP).
    op.drop_index("ix_jobs_kind", table_name="jobs")
    op.drop_index("ix_jobs_worker_id", table_name="jobs")
    op.drop_index("ix_jobs_status_lease", table_name="jobs")
    op.drop_table("jobs")
