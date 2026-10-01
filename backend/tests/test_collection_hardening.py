"""The three ways a collection run goes wrong operationally.

S1.2 shipped a walk that could not notice a provider misbehaving, a record list
with no ceiling, and no way to notice a worker had vanished. Each of those ends
the same way: a run that never finishes, and a page that can never be collected
again. Each is closed here.

They share a shape, which is why they are in one file: a condition only a
misbehaving or absent provider creates, a deterministic way to stop, and a
promise that whatever was already committed is still there afterwards. That last
part is the one worth testing hardest, because the failure mode of every
hardening measure is discarding good data while preventing a bad outcome.

Nothing here touches the raw-before-normalize guarantee. Every test that runs a
walk asserts afterwards that the response it collected is still stored.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import (
    CollectionRun,
    CollectionRunStatus,
    Competitor,
    FacebookPage,
    Job,
    ProviderRun,
    RawResponse,
)
from app.models.jobs import JobStatus
from app.models.runs import ProviderRunStatus
from app.providers.data.errors import Blocked
from app.providers.data.models import CostEstimate, PageRef, ProviderResult, RequestMeta
from app.providers.data.provenance import DataOrigin
from app.services.collection import (
    ERROR_TYPE_ABANDONED,
    ERROR_TYPE_BLOCKED,
    ERROR_TYPE_CURSOR_CYCLE,
    ERROR_TYPE_PAGE_LIMIT,
    ERROR_TYPE_RECORD_LIMIT,
    INTERNAL_ERROR_MESSAGE,
    CollectionOrchestrator,
)
from tests.conftest import StubAd, StubResult

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
LONG_AGO = timedelta(hours=2)


def _ad(ad_id: str) -> dict[str, Any]:
    """One minimal readable record, small so a page can hold many."""
    return {
        "ad_id": ad_id,
        "status": "active",
        "ad_creative_bodies": [{"body": f"Copy for {ad_id}."}],
    }


def _cost() -> CostEstimate:
    return CostEstimate(amount=0, currency="USD", method="scripted; nothing was requested")


class _ScriptedProvider:
    """A provider serving a fixed script of batches, keyed by cursor.

    What the orchestrator actually depends on is a cursor contract, so that is
    what this provides -- including the ways a real provider gets it wrong. It
    holds no state beyond the calls it was asked for, so a test can assert on
    exactly how many times it was called.
    """

    name = "scripted"
    origin = DataOrigin.third_party

    def __init__(self, script: dict[str | None, tuple[dict[str, Any], str | None]]) -> None:
        self._script = script
        self.calls: list[str | None] = []

    def fetch_page_ads(
        self, page: PageRef, country: str, *, cursor: str | None = None
    ) -> ProviderResult:
        self.calls.append(cursor)
        if cursor not in self._script:
            raise AssertionError(f"asked for a cursor that was never issued: {cursor!r}")
        raw, next_cursor = self._script[cursor]
        return ProviderResult(
            raw=raw,
            next_cursor=next_cursor,
            request_meta=RequestMeta(
                provider=self.name,
                origin=self.origin,
                country=country,
                requested_at=NOW,
                cursor=cursor,
            ),
            cost_estimate=_cost(),
        )


def _linear(*raws: dict[str, Any]) -> dict[str | None, tuple[dict[str, Any], str | None]]:
    """A straight walk: the first page under `None`, then `c0`, `c1`, and so on.

    Written as a helper because a script has to name the cursor a page is
    served *under* as well as the one it hands *back*, and getting the two out
    of step produces a provider that raises rather than one that misbehaves --
    which is a different test entirely.
    """
    return {
        (None if index == 0 else f"c{index - 1}"): (
            raw,
            f"c{index}" if index < len(raws) - 1 else None,
        )
        for index, raw in enumerate(raws)
    }


def _orchestrator(
    session: Any,
    provider: Any,
    *,
    max_records: int = 10_000,
    max_pages: int = 200,
) -> CollectionOrchestrator:
    return CollectionOrchestrator(  # type: ignore[arg-type]
        session,
        provider,
        _RecordingQueue(),
        max_records=max_records,
        max_pages=max_pages,
    )


class _RecordingQueue:
    """Remembers what it was asked to enqueue, so scheduling can be asserted on.

    The walk never enqueues; that is pinned in `test_collection_ordering.py`.
    This fake exists because the recovery tests do schedule, to show a
    recovered page is collectible again.
    """

    def __init__(self) -> None:
        self.enqueued: list[Any] = []

    def enqueue(self, job: Any) -> str:
        self.enqueued.append(job)
        return f"job-{len(self.enqueued)}"


# ============================================================
# 1. Cursor cycle protection
#
# The guard lives at the top of the walk: before following a cursor, check
# whether it is one we have already followed. So a cursor we have *not* yet
# followed is followed even if it points at a page we already have -- the
# provider asked for it, and it is the second time round that is a circle.
# ============================================================


def test_a_normal_multi_page_walk_collects_every_page_in_order() -> None:
    """The ordinary case, unchanged: three pages, three calls, in order.

    Pinned first because cycle detection is only safe if it cannot fire on a
    walk that is behaving. Each cursor is seen exactly once, on the way past.
    """
    provider = _ScriptedProvider(
        {
            None: ({"ads": [_ad("a1"), _ad("a2")]}, "c1"),
            "c1": ({"ads": [_ad("a3")]}, "c2"),
            "c2": ({"ads": [_ad("a4")]}, None),
        }
    )
    session = _FakeSession()

    outcome = _orchestrator(session, provider).execute_collection_job(session.run_id)

    assert provider.calls == [None, "c1", "c2"]
    assert [r.external_ad_id for r in outcome.records] == ["a1", "a2", "a3", "a4"]
    assert outcome.status is CollectionRunStatus.COMPLETE
    assert outcome.stopped_reason is None
    assert outcome.errors == ()


def test_a_cursor_pointing_at_its_own_page_stops_the_walk() -> None:
    """A cursor that hands back its own page is a circle, not progress.

    Detected *before* the fetch, so the repeated page is never requested. Left
    to run, this is an unbounded loop that adds a `provider_run` and a
    `raw_response` on every single pass.
    """
    provider = _ScriptedProvider(
        {
            None: ({"ads": [_ad("a1")]}, "c1"),
            "c1": ({"ads": [_ad("a2")]}, "c1"),
        }
    )
    session = _FakeSession()

    outcome = _orchestrator(session, provider).execute_collection_job(session.run_id)

    assert provider.calls == [None, "c1"], "the repeated cursor was fetched again"
    assert outcome.stopped_reason == ERROR_TYPE_CURSOR_CYCLE
    assert outcome.status is CollectionRunStatus.PARTIAL


def test_a_cursor_cycle_still_keeps_every_response_already_collected() -> None:
    """The pages collected before the circle are still stored, and still whole.

    This is the property the whole walk is arranged around. A walk that stops
    early because the provider misbehaved has still seen real responses, and
    they may be the only copy of anything the provider has since stopped
    serving.
    """
    provider = _ScriptedProvider(
        {
            None: ({"ads": [_ad("a1")]}, "c1"),
            "c1": ({"ads": [_ad("a2")]}, "c1"),
        }
    )
    session = _FakeSession()

    _orchestrator(session, provider).execute_collection_job(session.run_id)

    assert session.raw_payloads == [{"ads": [_ad("a1")]}, {"ads": [_ad("a2")]}]
    assert len(session.raw_payloads) == 2, "the repeated page must not have been stored"
    assert session.provider_run_count == 2


def test_a_cursor_cycle_terminates_deterministically() -> None:
    """The same misbehaving provider stops at the same place, every time.

    A guard that itself leaned on a clock or on set iteration order would be no
    better than the loop it replaces.
    """
    script = {
        None: ({"ads": [_ad("a1")]}, "c1"),
        "c1": ({"ads": [_ad("a2")]}, "c2"),
        "c2": ({"ads": [_ad("a3")]}, "c1"),
    }

    results = []
    for _ in range(3):
        provider = _ScriptedProvider(dict(script))
        session = _FakeSession()
        outcome = _orchestrator(session, provider).execute_collection_job(session.run_id)
        results.append((provider.calls, outcome.stopped_reason, len(outcome.records)))

    assert results == [([None, "c1", "c2"], ERROR_TYPE_CURSOR_CYCLE, 3)] * 3


def test_a_long_but_finite_walk_is_not_mistaken_for_a_cycle() -> None:
    """Twenty distinct cursors is a big page, not a bug.

    The guard counts nothing and compares nothing but equality, so a provider
    with many genuinely different cursors is followed to the end.
    """
    script: dict[str | None, tuple[dict[str, Any], str | None]] = {}
    for index in range(20):
        script[f"c{index}" if index else None] = (
            {"ads": [_ad(f"a{index}")]},
            f"c{index + 1}" if index < 19 else None,
        )
    provider = _ScriptedProvider(script)
    session = _FakeSession()

    outcome = _orchestrator(session, provider).execute_collection_job(session.run_id)

    assert len(provider.calls) == 20
    assert outcome.status is CollectionRunStatus.COMPLETE
    assert len(outcome.records) == 20


def test_the_run_says_why_the_walk_stopped() -> None:
    """ "It stopped" is not actionable. The cursor in the message is."""
    provider = _ScriptedProvider(
        {
            None: ({"ads": [_ad("a1")]}, "c1"),
            "c1": ({"ads": [_ad("a2")]}, "c1"),
        }
    )
    session = _FakeSession()

    _orchestrator(session, provider).execute_collection_job(session.run_id)

    assert session.run_row["error_type"] == ERROR_TYPE_CURSOR_CYCLE
    assert "c1" in session.run_row["error_message"]


# ============================================================
# 2. Record-count safety
# ============================================================


def test_a_run_stops_at_the_record_ceiling() -> None:
    """Reaching the ceiling ends the walk and says so.

    The run is `partial`, not `complete`: it did not read everything the
    provider was offering, and `complete` would be a claim it has not earned.
    """
    provider = _ScriptedProvider(
        {
            None: ({"ads": [_ad("a1"), _ad("a2")]}, "c1"),
            "c1": ({"ads": [_ad("a3")]}, None),
        }
    )
    session = _FakeSession()

    outcome = _orchestrator(session, provider, max_records=2).execute_collection_job(session.run_id)

    assert outcome.stopped_reason == ERROR_TYPE_RECORD_LIMIT
    assert outcome.status is CollectionRunStatus.PARTIAL
    assert [r.external_ad_id for r in outcome.records] == ["a1", "a2"]
    assert provider.calls == [None], "the walk continued past the ceiling"


def test_the_ceiling_boundary_is_exact() -> None:
    """Reaching the ceiling with nothing more offered is a finished run.

    The off-by-one here is the difference between a setting that works and one
    that quietly refuses a legitimate collection, so both sides are pinned: land
    exactly on the ceiling and let the provider say it is done, and the run is
    `complete`. The same total with one more page still on offer is a limit
    stop, because something was withheld.
    """
    script: dict[str | None, tuple[dict[str, Any], str | None]] = {
        None: ({"ads": [_ad("a1"), _ad("a2")]}, "c1"),
        "c1": ({"ads": [_ad("a3")]}, None),
    }

    at_limit = _FakeSession()
    exactly = _orchestrator(
        at_limit, _ScriptedProvider(dict(script)), max_records=3
    ).execute_collection_job(at_limit.run_id)

    withheld = _FakeSession()
    stopped = _orchestrator(
        withheld, _ScriptedProvider(dict(script)), max_records=2
    ).execute_collection_job(withheld.run_id)

    assert len(exactly.records) == 3
    assert exactly.stopped_reason is None
    assert exactly.status is CollectionRunStatus.COMPLETE
    assert stopped.stopped_reason == ERROR_TYPE_RECORD_LIMIT
    assert stopped.status is CollectionRunStatus.PARTIAL
    assert len(stopped.records) == 2


def test_the_ceiling_does_not_invent_a_stop_the_provider_did_not_cause() -> None:
    """A short page from a provider with one page is just a short page.

    Landing exactly on the ceiling and then being told there is nothing more is
    not a limit stop. Reporting one would put a false explanation on a run that
    did exactly what it was asked.
    """
    session = _FakeSession()

    outcome = _orchestrator(
        session,
        _ScriptedProvider({None: ({"ads": [_ad("a1"), _ad("a2")]}, None)}),
        max_records=2,
    ).execute_collection_job(session.run_id)

    assert outcome.stopped_reason is None
    assert outcome.status is CollectionRunStatus.COMPLETE


def test_a_page_that_overshoots_the_ceiling_is_still_stored_and_still_read() -> None:
    """The ceiling bounds a run's accumulation, not what a provider may serve.

    A single page of five with a ceiling of three is stored whole and read
    whole. Truncating it would throw away readable records to satisfy a memory
    bound, and would leave stored evidence the returned reading does not
    account for.
    """
    page = {"ads": [_ad(f"a{index}") for index in range(5)]}
    session = _FakeSession()

    outcome = _orchestrator(
        session,
        _ScriptedProvider({None: (page, "c1"), "c1": ({"ads": [_ad("z")]}, None)}),
        max_records=3,
    ).execute_collection_job(session.run_id)

    assert len(outcome.records) == 5
    assert outcome.stopped_reason == ERROR_TYPE_RECORD_LIMIT
    assert session.raw_payloads == [page]


def test_the_ceiling_keeps_every_response_already_collected() -> None:
    """Pages stored before the ceiling was reached are untouched."""
    provider = _ScriptedProvider(
        {
            None: ({"ads": [_ad("a1")]}, "c1"),
            "c1": ({"ads": [_ad("a2")]}, None),
        }
    )
    session = _FakeSession()

    _orchestrator(session, provider, max_records=1).execute_collection_job(session.run_id)

    assert session.raw_payloads == [{"ads": [_ad("a1")]}]
    assert session.provider_run_count == 1


def test_the_run_message_names_the_setting_that_stopped_it() -> None:
    """An operator can act on this without reading the source.

    The message names the condition and the setting, because the setting is the
    thing they would change.
    """
    session = _FakeSession()

    _orchestrator(
        session,
        _ScriptedProvider(_linear({"ads": [_ad("a1"), _ad("a2")]}, {"ads": [_ad("a3")]})),
        max_records=1,
    ).execute_collection_job(session.run_id)

    assert session.run_row["error_type"] == ERROR_TYPE_RECORD_LIMIT
    assert "collection_max_records_per_run" in session.run_row["error_message"]


# ============================================================
# 2b. Page ceiling
#
# The guard the other two cannot be. Both of them terminate on the provider
# *repeating* something or *producing* something; a provider offering a fresh
# cursor and nothing in it does neither, and would be fetched for ever,
# committing a row each time. Found by review, not by the original brief.
# ============================================================


def _endless_empty_provider(pages: int) -> _ScriptedProvider:
    """A provider that offers a new cursor every time and nothing in it.

    Well-formed, empty responses: no cycle, no records, no errors. The two
    hardest cases for the other guards, because both of their counters stay at
    zero.
    """
    return _ScriptedProvider(_linear(*([{"ads": []}] * pages)))


def test_a_provider_offering_nothing_at_all_still_terminates() -> None:
    """Empty pages, a fresh cursor each time, and a stop.

    Without the page ceiling this walk never ends, and it commits a
    `provider_run` and a `raw_response` on every single pass -- unbounded disk
    from one misbehaving endpoint.
    """
    provider = _endless_empty_provider(pages=50)
    session = _FakeSession()

    outcome = _orchestrator(session, provider, max_pages=5).execute_collection_job(session.run_id)

    assert len(provider.calls) == 5, "the walk kept going past the page ceiling"
    assert outcome.stopped_reason == ERROR_TYPE_PAGE_LIMIT
    assert outcome.status is CollectionRunStatus.PARTIAL
    assert outcome.records == ()
    assert outcome.errors == ()


def test_a_provider_offering_only_unreadable_records_also_terminates() -> None:
    """Garbage that is well-formed enough to reject, page after page.

    `records` never grows here, so a ceiling counted over readable records
    alone would never fire and the `errors` list would grow without bound. It
    is counted over attempts for that reason.
    """
    provider = _ScriptedProvider(_linear(*([{"ads": [{"unmodelled": 1}]}] * 50)))
    session = _FakeSession()

    outcome = _orchestrator(session, provider, max_pages=4).execute_collection_job(session.run_id)

    assert len(provider.calls) == 4
    assert outcome.stopped_reason == ERROR_TYPE_PAGE_LIMIT
    assert outcome.records == ()
    assert len(outcome.errors) == 4


def test_the_record_ceiling_counts_records_it_could_not_read() -> None:
    """Unreadable records count towards the ceiling.

    They occupy the same memory and the same `errors` list, so excluding them
    would make the ceiling exactly useless against the provider most likely to
    trigger it.
    """
    provider = _ScriptedProvider(_linear({"ads": [{"a": 1}, {"b": 2}]}, {"ads": [{"c": 3}]}))
    session = _FakeSession()

    outcome = _orchestrator(session, provider, max_records=2).execute_collection_job(session.run_id)

    assert outcome.stopped_reason == ERROR_TYPE_RECORD_LIMIT
    assert outcome.records == ()
    assert len(outcome.errors) == 2


def test_the_page_ceiling_leaves_every_response_already_collected() -> None:
    """The pages fetched before the ceiling are still stored, and still whole."""
    provider = _ScriptedProvider(
        _linear({"ads": [_ad("a0")]}, {"ads": [_ad("a1")]}, {"ads": [_ad("a2")]})
    )
    session = _FakeSession()

    _orchestrator(session, provider, max_pages=2).execute_collection_job(session.run_id)

    assert session.raw_payloads == [{"ads": [_ad("a0")]}, {"ads": [_ad("a1")]}]
    assert session.provider_run_count == 2


def test_the_page_ceiling_boundary_is_exact() -> None:
    """Exactly as many pages as allowed, and the provider done, is complete."""
    provider = _ScriptedProvider(_linear({"ads": [_ad("a0")]}, {"ads": [_ad("a1")]}))

    exact = _FakeSession()
    at_limit = _orchestrator(exact, provider, max_pages=2).execute_collection_job(exact.run_id)

    over = _FakeSession()
    stopped = _orchestrator(over, provider, max_pages=1).execute_collection_job(over.run_id)

    assert at_limit.stopped_reason is None
    assert at_limit.status is CollectionRunStatus.COMPLETE
    assert len(at_limit.records) == 2
    assert stopped.stopped_reason == ERROR_TYPE_PAGE_LIMIT
    assert len(stopped.records) == 1


# ============================================================
# 2c. What a run is allowed to say about itself
# ============================================================


class _ExplodingProvider:
    """A provider that fails the way real infrastructure does.

    Not with a tidy message. A SQLAlchemy exception's text carries the failed
    statement, the host, the database user, and an absolute filesystem path
    including the operating system's username.
    """

    name = "exploding"
    origin = DataOrigin.third_party

    def fetch_page_ads(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(
            '(psycopg.errors.UndefinedColumn) column "provider_runs.nope" does not exist\n'
            "[SQL: INSERT INTO provider_runs (collection_run_id, status) "
            "VALUES (%(id)s, 'succeeded')]\n"
            "(Background on this error at: https://sqlalche.me/e/20/f405)\n"
            r"connection: host=db.internal port=5432 user=brandset db=brandset"
            "\n"
            r'File "C:\Users\Someone\app\services\collection.py", line 545, in execute'
        )


def test_an_internal_failure_does_not_persist_its_own_text() -> None:
    """`get_run_error` exists to hand this column to a caller.

    The detail of an unexpected internal failure goes to the worker's log, where
    an operator reads it, not into a row that is about to be shown to somebody.
    A typed *provider* error is the opposite case and is kept -- that message is
    the provider's, and says what the reader needs.
    """
    session = _FakeSession()

    _orchestrator(session, _ExplodingProvider()).execute_collection_job(session.run_id)

    message = session.run_row["error_message"]
    assert message == INTERNAL_ERROR_MESSAGE
    for leak in ("provider_runs", "db.internal", "brandset", "SQLAlchemy", "C:\\Users"):
        assert leak not in message, leak


def test_a_typed_provider_error_keeps_the_providers_own_message() -> None:
    """Provider-authored text is the useful kind, and stays."""
    session = _FakeSession()

    _orchestrator(session, _BlockedProvider()).execute_collection_job(session.run_id)

    assert session.run_row["error_type"] == ERROR_TYPE_BLOCKED
    assert "refused" in session.run_row["error_message"]


def test_a_blocked_provider_cannot_forge_a_log_line() -> None:
    """A provider message carrying a newline must not become two log lines.

    The escaping is applied on the short path as well as the truncated one.
    Returning short text unchanged -- which this function used to do -- left
    exactly this open.
    """
    session = _FakeSession()

    _orchestrator(session, _BlockedProvider(with_newline=True)).execute_collection_job(
        session.run_id
    )

    message = session.run_row["error_message"]
    assert "\n" not in message
    assert "\\n" in message


class _BlockedProvider:
    """Raises the typed `Blocked` error, which is terminal and not retried."""

    name = "blocker"
    origin = DataOrigin.third_party

    def __init__(self, *, with_newline: bool = False) -> None:
        self._message = (
            "the provider refused this request\n2026-10-01 ERROR forged audit line"
            if with_newline
            else "the provider refused this request"
        )

    def fetch_page_ads(self, *args: Any, **kwargs: Any) -> Any:
        raise Blocked(self._message, provider=self.name)


# ============================================================
# 3. Stale run recovery
# ============================================================


@pytest.mark.integration
def test_a_stale_run_with_no_job_row_at_all_is_recoverable(db_session: Session) -> None:
    """A job row that was never created, or was removed out of band.

    The candidate query finds this run on `status` and `updated_at` alone, and
    "no job holds a lease" is true when there is no job at all -- so recovery
    still has to act. This is one of the two shapes a real crash produces.
    """
    run = _full_chain(db_session, "100000000000048")
    _start_run(db_session, run)
    _provider_call(db_session, run.id, when=NOW - LONG_AGO)
    db_session.commit()

    assert (
        db_session.execute(
            select(Job).where(Job.payload["collection_run_id"].astext == str(run.id))
        )
        .scalars()
        .all()
        == []
    )

    recovered = _orchestrator(db_session, _never_called()).recover_stale_runs(now=NOW)

    assert recovered == (run.id,)
    db_session.refresh(run)
    assert run.status is CollectionRunStatus.FAILED


@pytest.mark.parametrize("job_status", [JobStatus.COMPLETED, JobStatus.FAILED])
def test_a_stale_run_whose_job_already_finished_is_recoverable(
    db_session: Session, job_status: str
) -> None:
    """A terminal job plus a `running` run is a contradiction, and it resolves to failed.

    The worker sets the run's status before it completes the job, so a terminal
    job with a `running` run means the worker died in between. Leaving the run
    `running` would block the page for ever.
    """
    run = _full_chain(db_session, "100000000000049")
    _start_run(db_session, run)
    db_session.add(_job_for(run.id, status=job_status))
    _provider_call(db_session, run.id, when=NOW - LONG_AGO)
    db_session.commit()

    recovered = _orchestrator(db_session, _never_called()).recover_stale_runs(now=NOW)

    assert recovered == (run.id,)
    db_session.refresh(run)
    assert run.status is CollectionRunStatus.FAILED


class _WorkerWinsSession:
    """A session where the worker finishes the run just as recovery writes it.

    A proxy rather than a patched function, so `recover_stale_runs` runs its
    real production code including its real `UPDATE`. An earlier version of this
    test rebuilt the guarded statement inside the test body, which meant it
    proved the test's own copy of the guard rather than the one that ships --
    and removing the guard from the real code left that test green.
    """

    def __init__(self, inner: Session, run_id: uuid.UUID) -> None:
        self._inner = inner
        self._run_id = run_id
        self.armed = True
        self.raced = False

    def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if self.armed and str(statement).lstrip().upper().startswith("UPDATE COLLECTION_RUNS"):
            self.armed = False
            self.raced = True
            # The worker's commit lands first. `updated_at` is nudged explicitly
            # rather than set to `now()`, because `now()` is fixed for the
            # transaction and would not differ from what recovery read -- which
            # would make the guard pass and the race unrepresentable.
            self._inner.execute(
                text(
                    "UPDATE collection_runs SET status = 'complete', "
                    "updated_at = updated_at + interval '1 second' WHERE id = :id"
                ),
                {"id": self._run_id},
            )
            self._inner.commit()
        return self._inner.execute(statement, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


@pytest.mark.integration
def test_recovery_does_not_overwrite_a_run_that_finished_meanwhile(db_session: Session) -> None:
    """The race the guarded `UPDATE` exists for.

    Between recovery reading a run and writing it, a live worker commits the
    run's real outcome. An unguarded ORM assignment would flush `failed` over
    that -- destroying the one record of what actually happened, which is the
    thing AGENTS.md section 8 exists to prevent.
    """
    run = _full_chain(db_session, "100000000000050")
    _start_run(db_session, run)
    _provider_call(db_session, run.id, when=NOW - LONG_AGO)
    db_session.add(_job_for(run.id, status=JobStatus.DEAD))
    db_session.commit()

    racing = _WorkerWinsSession(db_session, run.id)

    recovered = _orchestrator(racing, _never_called()).recover_stale_runs(now=NOW)

    assert racing.raced, "the race never happened, so this would pass vacuously"
    assert recovered == (), "recovery claimed a run a worker had already finished"
    db_session.expire_all()
    db_session.refresh(run)
    assert run.status is CollectionRunStatus.COMPLETE
    assert run.error_type is None


@pytest.mark.integration
def test_recovery_still_recovers_a_run_nobody_overtook(db_session: Session) -> None:
    """The same guarded write, without the race, must still match a row.

    Pins that the guard is a condition and not a veto. A `WHERE` clause that
    never matched would leave every "must not touch" test above green while
    recovering nothing at all.
    """
    run = _full_chain(db_session, "100000000000052")
    _start_run(db_session, run)
    _provider_call(db_session, run.id, when=NOW - LONG_AGO)
    db_session.add(_job_for(run.id, status=JobStatus.DEAD))
    db_session.commit()

    recovered = _orchestrator(db_session, _never_called()).recover_stale_runs(now=NOW)

    assert recovered == (run.id,)
    db_session.refresh(run)
    assert run.status is CollectionRunStatus.FAILED


@pytest.mark.integration
def test_recovery_reports_nothing_when_the_run_is_merely_recent(db_session: Session) -> None:
    """A run that has not been running for the timeout is not stale, however dead.

    Only the passage of the whole timeout, together with the other two signals,
    makes a run a candidate. Without the timeout, a run that started two
    seconds ago would be recoverable.
    """
    run = _full_chain(db_session, "100000000000051")
    _start_run(db_session, run, when=NOW - timedelta(seconds=5))
    db_session.add(_job_for(run.id, status=JobStatus.DEAD))
    db_session.commit()

    recovered = _orchestrator(db_session, _never_called()).recover_stale_runs(now=NOW)

    assert recovered == ()
    db_session.refresh(run)
    assert run.status is CollectionRunStatus.RUNNING


def _never_called() -> Any:
    """A provider that fails the test if the walk reaches for it.

    Recovery must not collect anything. A recovery pass that fetched from a
    provider would turn a repair into a collection run.
    """

    class _Forbidden:
        name = "forbidden"
        origin = DataOrigin.third_party

        def fetch_page_ads(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("recovery must not call a provider")

    return _Forbidden()


def _full_chain(session: Session, page_id: str) -> CollectionRun:
    competitor = Competitor(name="Hardening Fixture Co")
    session.add(competitor)
    session.flush()
    page = FacebookPage(
        competitor_id=competitor.id,
        page_id=page_id,
        country="IN",
        tracking_frequency="daily",
        is_tracked=True,
    )
    session.add(page)
    session.flush()
    run = CollectionRun(
        facebook_page_id=page.id,
        provider="scripted",
        country="IN",
        data_origin=DataOrigin.third_party,
        status=CollectionRunStatus.PENDING,
        records_returned=0,
    )
    session.add(run)
    session.flush()
    return run


def _age_the_run(session: Session, run: CollectionRun, *, when: datetime) -> None:
    """Make a run *look* old.

    `created_at` and `updated_at` are both server-set, so "this row has not been
    touched since two hours ago" is expressed by writing the columns directly.
    """
    session.execute(
        text("UPDATE collection_runs SET updated_at = :ts WHERE id = :id"),
        {"ts": when, "id": run.id},
    )
    session.commit()


def _start_run(session: Session, run: CollectionRun, *, when: datetime = NOW - LONG_AGO) -> None:
    run.status = CollectionRunStatus.RUNNING
    run.started_at = when
    session.flush()
    _age_the_run(session, run, when=when)


def _job_for(
    run_id: uuid.UUID,
    *,
    status: str,
    lease_expires_at: datetime | None = None,
) -> Job:
    terminal = status in (JobStatus.DEAD, JobStatus.FAILED)
    return Job(
        kind="collection.run",
        payload={"collection_run_id": str(run_id)},
        status=status,
        worker_id="worker-1" if status == JobStatus.RUNNING else None,
        lease_expires_at=lease_expires_at,
        started_at=NOW - LONG_AGO,
        finished_at=NOW - LONG_AGO if terminal or status == JobStatus.COMPLETED else None,
        attempt=1,
        error_message="gave up" if terminal else None,
        error_type="transient" if terminal else None,
    )


def _provider_call(session: Session, run_id: uuid.UUID, *, when: datetime) -> ProviderRun:
    """One provider call, backdated so "recent progress" can be tested."""
    call = ProviderRun(
        collection_run_id=run_id,
        status=ProviderRunStatus.SUCCEEDED,
        started_at=when,
        finished_at=when,
        request_meta={"provider": "scripted", "country": "IN"},
        http_status=200,
    )
    session.add(call)
    session.flush()
    session.execute(
        text("UPDATE provider_runs SET created_at = :ts WHERE id = :id"),
        {"ts": when, "id": call.id},
    )
    return call


@pytest.mark.integration
def test_a_run_a_worker_is_holding_is_not_treated_as_stale(db_session: Session) -> None:
    """A live lease means somebody is on it, whatever the clock says."""
    run = _full_chain(db_session, "100000000000041")
    _start_run(db_session, run)
    db_session.add(
        _job_for(run.id, status=JobStatus.RUNNING, lease_expires_at=NOW + timedelta(minutes=5))
    )
    db_session.commit()

    recovered = _orchestrator(db_session, _never_called()).recover_stale_runs(now=NOW)

    assert recovered == ()
    db_session.refresh(run)
    assert run.status is CollectionRunStatus.RUNNING


@pytest.mark.integration
def test_a_slow_run_that_is_still_adding_pages_is_not_treated_as_stale(
    db_session: Session,
) -> None:
    """The signal that protects a real walk: it is still making progress.

    This is the false positive the design exists to avoid. A run whose job lease
    has already lapsed looks abandoned on the lease alone -- the worker does not
    extend it, and a long walk outlives the five-minute lease -- so only the
    provider-call rows say otherwise. A run that is slow is not dead.
    """
    run = _full_chain(db_session, "100000000000042")
    _start_run(db_session, run, when=NOW - LONG_AGO)
    db_session.add(
        _job_for(run.id, status=JobStatus.RUNNING, lease_expires_at=NOW - timedelta(minutes=25))
    )
    # Lease long gone and the run row long untouched, but a page landed five
    # minutes ago.
    _provider_call(db_session, run.id, when=NOW - timedelta(minutes=5))
    db_session.commit()

    recovered = _orchestrator(db_session, _never_called()).recover_stale_runs(now=NOW)

    assert recovered == ()
    db_session.refresh(run)
    assert run.status is CollectionRunStatus.RUNNING


@pytest.mark.integration
def test_a_run_nobody_is_holding_and_nobody_is_advancing_is_recoverable(
    db_session: Session,
) -> None:
    """The actual crash: the worker is gone and the walk stopped where it was.

    All three signals agree, so the run is marked `failed` -- which is what
    hands the page back to `schedule_collection`.
    """
    run = _full_chain(db_session, "100000000000043")
    _start_run(db_session, run)
    db_session.add(
        _job_for(run.id, status=JobStatus.RUNNING, lease_expires_at=NOW - timedelta(hours=1))
    )
    _provider_call(db_session, run.id, when=NOW - LONG_AGO)
    db_session.commit()

    recovered = _orchestrator(db_session, _never_called()).recover_stale_runs(now=NOW)

    assert recovered == (run.id,)
    db_session.refresh(run)
    assert run.status is CollectionRunStatus.FAILED
    assert run.error_type == ERROR_TYPE_ABANDONED
    assert run.finished_at is not None


@pytest.mark.integration
def test_a_dead_job_with_no_lease_at_all_is_still_recoverable(db_session: Session) -> None:
    """`dead` is the case that made this a real problem.

    The queue already re-leases a job whose lease lapsed, so a crashed worker is
    mostly handled on its own. But a job that has burned its attempts goes
    `dead` and is never claimed again, and its run would sit `running` for ever
    -- which also stops `schedule_collection` from starting another, so the page
    is permanently uncollectible.
    """
    run = _full_chain(db_session, "100000000000044")
    _start_run(db_session, run)
    db_session.add(_job_for(run.id, status=JobStatus.DEAD))
    db_session.commit()

    recovered = _orchestrator(db_session, _never_called()).recover_stale_runs(now=NOW)

    assert recovered == (run.id,)
    db_session.refresh(run)
    assert run.status is CollectionRunStatus.FAILED


@pytest.mark.integration
def test_recovery_keeps_every_response_the_run_had_already_stored(
    db_session: Session,
) -> None:
    """The three pages a run collected before it died are still there, whole.

    Recovery changes one row's status. It must not touch a single
    `provider_run` or `raw_response`, because those are the only copy of
    anything a provider may since have stopped serving.
    """
    run = _full_chain(db_session, "100000000000045")
    _start_run(db_session, run)
    db_session.add(_job_for(run.id, status=JobStatus.DEAD))
    for index in range(3):
        call = _provider_call(db_session, run.id, when=NOW - LONG_AGO)
        db_session.add(RawResponse(provider_run_id=call.id, payload={"ads": [_ad(f"a{index}")]}))
    db_session.commit()

    before = db_session.execute(select(RawResponse)).scalars().all()
    _orchestrator(db_session, _never_called()).recover_stale_runs(now=NOW)

    after = db_session.execute(select(RawResponse)).scalars().all()
    assert [row.id for row in after] == [row.id for row in before]
    assert [row.payload for row in after] == [
        {"ads": [_ad("a0")]},
        {"ads": [_ad("a1")]},
        {"ads": [_ad("a2")]},
    ]


@pytest.mark.integration
@pytest.mark.parametrize(
    "status",
    [
        CollectionRunStatus.COMPLETE,
        CollectionRunStatus.PARTIAL,
        CollectionRunStatus.FAILED,
        CollectionRunStatus.PENDING,
    ],
)
def test_recovery_never_touches_a_run_that_is_not_running(
    db_session: Session, status: CollectionRunStatus
) -> None:
    """Only `running` is ever a candidate.

    The requirement that matters most here is the negative one: a `partial` or
    `failed` run must never be promoted, and a `complete` one must never be
    re-opened. Recovery is a one-way correction of one state, not a general
    status reconciliation that could quietly rewrite history.
    """
    run = _full_chain(db_session, "100000000000046")
    _start_run(db_session, run)
    if status is not CollectionRunStatus.PENDING:
        run.finished_at = NOW - timedelta(hours=1)
    run.status = status
    db_session.commit()
    _age_the_run(db_session, run, when=NOW - LONG_AGO)

    recovered = _orchestrator(db_session, _never_called()).recover_stale_runs(now=NOW)

    assert recovered == ()
    db_session.refresh(run)
    assert run.status is status


@pytest.mark.integration
def test_recovery_leaves_a_recovered_page_collectible_again(db_session: Session) -> None:
    """The point of recovering: `schedule_collection` stops refusing the page.

    It treats `pending` and `running` as "already being collected", so a run left
    `running` blocks every future attempt. Marking it `failed` is what actually
    gives the page back.
    """
    run = _full_chain(db_session, "100000000000047")
    _start_run(db_session, run)
    db_session.add(_job_for(run.id, status=JobStatus.DEAD))
    db_session.commit()

    orchestrator = _orchestrator(db_session, _never_called())
    orchestrator.recover_stale_runs(now=NOW)
    db_session.refresh(run)

    assert run.status is not CollectionRunStatus.RUNNING
    job_id = orchestrator.schedule_collection(run.facebook_page_id)
    assert job_id
    assert len(orchestrator._job_queue.enqueued) == 1


# ============================================================
# A walk with no database in it
#
# The walk's ordering guarantees are already pinned against the real schema in
# `test_collection_ordering.py`. These tests are about the loop's *decisions*,
# and a real session would only make them slower, not truer.
# ============================================================


class _FakeRun:
    """Enough of a `CollectionRun` for the walk, reporting what was set on it.

    The three fields a caller would read back -- status, error type, error
    message -- are mirrored onto the session so a test can assert on what the
    walk told the database, not only on what it returned.
    """

    _MIRRORED = ("status", "error_type", "error_message", "records_returned")

    def __init__(self, session: _FakeSession) -> None:
        object.__setattr__(self, "_session", session)
        object.__setattr__(self, "id", session.run_id)
        object.__setattr__(self, "country", "IN")
        # Read before the orchestrator's first commit and handed to S2.1, whose
        # ad identity is keyed on the provider that issued the ids.
        object.__setattr__(self, "provider", "scripted")
        object.__setattr__(self, "data_origin", DataOrigin.third_party)
        object.__setattr__(self, "status", CollectionRunStatus.PENDING)
        object.__setattr__(self, "started_at", None)
        object.__setattr__(self, "finished_at", None)
        object.__setattr__(self, "records_returned", 0)
        object.__setattr__(self, "error_type", None)
        object.__setattr__(self, "error_message", None)
        object.__setattr__(
            self,
            "facebook_page",
            SimpleNamespace(
                page_id="100000000000001", name="Scripted", url="https://example.invalid/p"
            ),
        )

    def __setattr__(self, name: str, value: Any) -> None:
        object.__setattr__(self, name, value)
        if name in self._MIRRORED:
            self._session.run_row[name] = value


class _FakeSession:
    """Records what a walk wrote, and nothing else."""

    def __init__(self) -> None:
        self.run_id = uuid.uuid4()
        self.raw_payloads: list[Any] = []
        self.provider_run_count = 0
        self.run_row: dict[str, Any] = {}

    def get(self, model: Any, primary_key: Any) -> Any:
        return _FakeRun(self)

    def add(self, instance: Any) -> None:
        if isinstance(instance, RawResponse):
            self.raw_payloads.append(instance.payload)
        elif isinstance(instance, ProviderRun):
            self.provider_run_count += 1

    def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        """Accepts the S2.1 ad-history upserts and discards them.

        A fake session that stored nothing has no ad to hand back, so each
        upsert yields a fresh stand-in. These tests assert what the *walk*
        decided -- which cursor, which ceiling, which status -- and the real
        persistence is proved against PostgreSQL elsewhere.
        """
        return StubResult(StubAd(id=uuid.uuid4(), meta_ad_id="stub"))

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        return None
