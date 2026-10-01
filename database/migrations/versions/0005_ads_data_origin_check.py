"""Add the missing `data_origin` vocabulary check on `ads`.

## Why this migration exists

`0004_ad_history` created `ads.data_origin` with `create_constraint=False`, so the
named vocabulary check was never installed. The `Ad` model declares one --
`app/models/runs.py::_stored_enum` is called with its default
`create_constraint=True` -- so from S2.1 onward the model and the database
disagreed about `ads` and nothing noticed.

## How it went unnoticed

`alembic check` reports no drift, and that is not a bug in Alembic. Autogenerate
does not detect `CHECK` constraints, which is precisely why every check in this
package is declared in `__table_args__` and named, and why
`app/models/mixins.py` says so at length. The drift is invisible to the one tool
that exists to find drift. The only way to catch it is to compare the metadata's
declared checks against `pg_constraint` by name, which
`test_schema_integration.py` now does for the S2.1 tables as well as the S1 ones.

## Why it matters

`data_origin` is a closed vocabulary. `collection_runs.data_origin` has carried
`ck_collection_runs_data_origin` since S1.1, so a run cannot record an origin
outside the four values. On `ads` the column was a bare `VARCHAR`, so the same
impossible value was storable on the ad -- the row a reader would consult for
provenance, and the one with nothing to stop it. Two copies of the same fact
enforcing different rules is exactly the divergence the provenance design exists
to prevent, and `AGENTS.md` section 7 requires a migration for any change to
these values rather than a new member appended at a call site.

## What it does not do

Purely additive: one named `CHECK`, no data touched, no column altered, no table
dropped. The `ads` table is empty in every environment this checkpoint has run
against, so there is nothing to backfill and no row to repair -- but the
constraint would be equally correct over existing rows, since every value the
service writes is one of the four.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

#: Revision identifiers, used by Alembic.
revision: str = "0005_ads_data_origin_check"
down_revision: str | None = "0004_ad_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The constraint text is copied from the one `0002_collection_domain`
    # installed on `collection_runs`, so the two tables enforce an identical
    # vocabulary. It is written out rather than derived from the model, because a
    # migration that imported application code would be reading the code it is
    # supposed to be recording.
    op.create_check_constraint(
        op.f("ck_ads_data_origin"),
        "ads",
        "data_origin = ANY (ARRAY['official_api', 'public_ui', 'third_party', 'user_import'])",
    )


def downgrade() -> None:
    # Restores the exact `0004_ad_history` state: the column remains a `VARCHAR`
    # with no vocabulary check, and the provenance rule for `ads` is gone from
    # the database while remaining declared in the model.
    #
    # Not reversible in the useful sense, and the reason is stated here rather
    # than left to be discovered: the constraint can be added at any time and its
    # removal cannot be undone without a table rewrite if invalid data ever
    # arrives. The downgrade is offered for completeness -- every revision in
    # this project renders its downgrade offline, because running one issues
    # `DROP`s and the checkpoint rules require explicit human consent for that.
    op.drop_constraint(op.f("ck_ads_data_origin"), "ads", type_="check")
