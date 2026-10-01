"""Turning normalized records into ad history: identity, snapshots, and links.

Three tables, three questions, and this module is where they are answered.

    "is this the same ad we already have?"  ->  `ads`, keyed (provider, meta_ad_id)
    "has it changed since we last looked?"   ->  `ad_snapshots`, one per change
    "which run saw it?"                      ->  `seen_in_run`, one per (ad, run)

## The order of operations, and why it is this order

For each ad, in this sequence:

1. **Resolve identity.** Upsert the `ads` row on `(provider, meta_ad_id)`. The
   upsert -- rather than a select-then-insert -- is what makes two workers
   processing the same ad safe, and what makes reprocessing idempotent.
2. **Compute `content_hash` v1** from the record. Not from the stored JSONB, so
   that JSONB's key normalisation cannot move a digest.
3. **Compare** against the snapshot `ads.latest_snapshot_id` points at.
4. **Write a snapshot** only when there is none, or the digest differs.
5. **Move `latest_snapshot_id`** only when a snapshot was written. An unchanged
   re-observation must not move the pointer, because the pointer means "this is
   the ad's current state" and nothing about the state changed.
6. **Upsert the `seen_in_run` link**, pointing at whichever snapshot applies.

The circular reference between `ads.latest_snapshot_id` and `ad_snapshots.ad_id`
needs no trickery: step 1 inserts the ad with a NULL pointer, step 4 inserts the
snapshot, step 5 fills the pointer in.

## Timestamps come from the database, not from Python

`first_seen_at` and `last_seen_at` are stamped with `now()` inside the same
statement that inserts or updates the row, and the `seen_in_run` link's
`created_at` is stamped with the same `now()` in the same transaction. Because
PostgreSQL's `now()` is the transaction timestamp, the two are *equal by
construction* rather than approximately equal -- so "when we first saw this ad"
and "when the run recorded that sighting" cannot disagree.

`last_seen_at` only ever moves forward: `greatest(last_seen_at, now())` means a
re-processed run cannot rewind an ad's history, whatever order things arrive in.

## Where the append-only rule lives

Not here. This module only ever *inserts* snapshots, and the database refuses
`UPDATE`/`DELETE` on the table regardless of who asks. A rule that only the
application respects is a rule one careless refactor breaks silently, and this
is the one table where a silent write is irrecoverable.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.ads import Ad, AdSnapshot, SeenInRun
from app.providers.data.models import RawAdRecord
from app.providers.data.provenance import DataOrigin
from app.services.content_hash import content_hash_v1


@dataclass(frozen=True, slots=True)
class ObservedRecord:
    """One normalized record, and the stored response it was read from.

    The response id travels with the record because that is what a snapshot has
    to cite. Keeping them in one value makes it impossible to write a snapshot
    that cannot name its own source.
    """

    record: RawAdRecord
    raw_response_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class PersistedObservation:
    """What one ad's observation turned into.

    Attributes:
        ad_id: The ad's identity row.
        meta_ad_id: The provider's id, echoed for logs and assertions.
        snapshot_id: The snapshot the run's sighting resolved to.
        content_hash: The v1 digest that was compared.
        created_snapshot: Whether this observation appended a new snapshot. The
            flag is the interesting part: a run that saw nothing new still
            persisted a link, and a caller needs to tell those apart.
    """

    ad_id: uuid.UUID
    meta_ad_id: str
    snapshot_id: uuid.UUID
    content_hash: str
    created_snapshot: bool


def persist_observations(
    session: Session,
    *,
    run_id: uuid.UUID,
    observations: Sequence[ObservedRecord],
    provider: str,
    data_origin: DataOrigin,
) -> tuple[PersistedObservation, ...]:
    """Write one run's worth of ad history.

    ## Idempotence is conditional, and the condition is the input

    **Re-processing the same run with identical input is idempotent**, and leaves
    exactly the same rows. Three things make that true, and each is a separate
    mechanism rather than one general guarantee: identity is an upsert on
    `(provider, meta_ad_id)`, so the ad row already exists; an unchanged
    `content_hash` writes no snapshot and does not move `latest_snapshot_id`; and
    the `seen_in_run` link is an upsert on `(ad_id, collection_run_id)`, so the
    sighting is recorded without adding a second row.

    **Re-processing the same run with *changed* content is not idempotent, and the
    database refuses it.** If the records now hash to a different digest,
    `_persist_one` finds no current snapshot for that ad and attempts a second
    `ad_snapshots` row for the same `(ad_id, collection_run_id)` pair.
    `uq_ad_snapshots_ad_run` rejects it with an `IntegrityError`.

    That rejection is intentional, and it is the reason the guarantee above is
    stated conditionally rather than flatly. One collection run represents one
    observation of an ad, so `(ad, run)` is the identity of that observation and
    admits exactly one row. A run that produced two different readings of the
    same ad is not a re-processing of one observation -- it is two observations
    wearing one run's identity, and the honest record of that is a *new run*
    rather than a second snapshot inside the first. The alternative, appending
    anyway, would let a single run claim the ad changed twice within seconds and
    would make the per-run history a record of a reading rather than of a walk.

    Re-processing is therefore safe precisely in the case it is actually for: a
    parser bug is fixed, the *stored* payloads are re-read, and a fixed parser
    reads the same bytes to the same digest. A digest that moves on re-read
    because the *reader* changed is the case the constraint turns away, and it
    is turned away loudly rather than silently recorded.

    Nothing here decides whether an ad is active, or whether its absence means
    anything; that is S2.3.

    Args:
        session: The run's session. The caller commits.
        run_id: The collection run every observation belongs to.
        observations: Every record the run read, each paired with the response it
            came from. May contain the same ad more than once.
        provider: The provider that issued the ids. Part of ad identity.
        data_origin: How the values were obtained (`AGENTS.md` section 7).

    Returns:
        One result per distinct ad, in first-appearance order.

    Raises:
        IntegrityError: If an observation's content differs from the snapshot
            already stored for the same `(ad, run)` pair. See the idempotence
            note above; the caller is expected to treat this as a signal that a
            new run is required, not to retry the same one.
    """
    results: list[PersistedObservation] = []
    for observed in _one_sighting_per_ad(observations):
        results.append(
            _persist_one(
                session,
                observed=observed,
                run_id=run_id,
                provider=provider,
                data_origin=data_origin,
            )
        )
    return tuple(results)


def _one_sighting_per_ad(observations: Sequence[ObservedRecord]) -> list[ObservedRecord]:
    """Collapse a run's records to one sighting per ad, keeping the last.

    A provider can serve the same ad more than once in a single walk, and the
    committed corpus does exactly that. The last sighting wins because it is the
    one the run's single snapshot describes, and because "last in the run's own
    order" is the only rule available: that order is the provider's pagination
    and array order, and nothing in the contract says it is chronological. It is
    deterministic, which is what the snapshot rule needs, and it is not a claim
    about which sighting is newer.

    First-appearance order is preserved for the ads themselves, so the output
    order does not depend on which sighting won.
    """
    latest: dict[str, ObservedRecord] = {}
    for observed in observations:
        latest[observed.record.external_ad_id] = observed
    return list(latest.values())


def _resolve_ad(
    session: Session,
    *,
    provider: str,
    meta_ad_id: str,
    data_origin: DataOrigin,
) -> Ad:
    """Find or create the ad, advancing `last_seen_at` on an existing one.

    A PostgreSQL upsert rather than a select followed by an insert: two workers
    that reach the same new ad at the same moment would both miss the select and
    one would fail on the unique constraint, which is a worse outcome than
    either of them winning.
    """
    statement = (
        insert(Ad)
        .values(
            provider=provider,
            meta_ad_id=meta_ad_id,
            data_origin=data_origin,
            first_seen_at=func.now(),
            last_seen_at=func.now(),
        )
        .on_conflict_do_update(
            index_elements=[Ad.provider, Ad.meta_ad_id],
            set_={
                # Never backwards, whatever order runs are processed in.
                "last_seen_at": func.greatest(Ad.last_seen_at, func.now()),
                "updated_at": func.now(),
            },
        )
        .returning(Ad)
    )
    ad: Ad = session.execute(statement).scalar_one()
    return ad


def _persist_one(
    session: Session,
    *,
    observed: ObservedRecord,
    run_id: uuid.UUID,
    provider: str,
    data_origin: DataOrigin,
) -> PersistedObservation:
    record = observed.record
    ad = _resolve_ad(
        session, provider=provider, meta_ad_id=record.external_ad_id, data_origin=data_origin
    )
    digest = content_hash_v1(record)

    current = _current_snapshot(session, ad)
    if current is not None and current.content_hash == digest:
        snapshot_id = current.id
        created_snapshot = False
    else:
        snapshot = AdSnapshot(
            ad_id=ad.id,
            collection_run_id=run_id,
            raw_ref=observed.raw_response_id,
            content_hash=digest,
            ad_status=record.ad_status,
            meta_delivery_start=record.meta_delivery_start,
            normalized=_normalized_json(record),
        )
        session.add(snapshot)
        session.flush()
        snapshot_id = snapshot.id
        created_snapshot = True
        ad.latest_snapshot_id = snapshot.id

    _link(session, ad_id=ad.id, run_id=run_id, snapshot_id=snapshot_id)

    return PersistedObservation(
        ad_id=ad.id,
        meta_ad_id=record.external_ad_id,
        snapshot_id=snapshot_id,
        content_hash=digest,
        created_snapshot=created_snapshot,
    )


def _current_snapshot(session: Session, ad: Ad) -> AdSnapshot | None:
    """The snapshot the ad's pointer names, or `None` if it has none yet."""
    if ad.latest_snapshot_id is None:
        return None
    return session.get(AdSnapshot, ad.latest_snapshot_id)


def _link(session: Session, *, ad_id: uuid.UUID, run_id: uuid.UUID, snapshot_id: uuid.UUID) -> None:
    """Record that this run saw this ad, correcting the link if it already did.

    `created_at` is deliberately absent from the update: the row's first-write
    time is when *this run* observed the ad, and a second sighting within the
    same run must not move it.
    """
    session.execute(
        insert(SeenInRun)
        .values(ad_id=ad_id, collection_run_id=run_id, snapshot_id=snapshot_id)
        .on_conflict_do_update(
            index_elements=[SeenInRun.ad_id, SeenInRun.collection_run_id],
            set_={"snapshot_id": snapshot_id, "updated_at": func.now()},
        )
    )


def _normalized_json(record: RawAdRecord) -> dict[str, object]:
    """The normalized record, as JSON-safe values.

    Provider order is preserved exactly as S1.3 produced it. This is the stored
    form, not the hashed form: `content_hash` is computed from the record itself,
    so that JSONB normalising key order and whitespace cannot move a digest.

    JSONB has no decimal type, so a media duration is stored in its exact decimal
    *string* form. A float would round; a string round-trips back through
    `RawAdRecord` unchanged, which is the only property that matters for
    evidence.
    """
    return record.model_dump(mode="json")
