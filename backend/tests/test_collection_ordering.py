"""The one ordering rule in the collection flow: store, *then* read.

A response that has been read is a response that can be refused, and a refused
response is one we no longer have. This checkpoint moved normalization out of
the provider and into the orchestrator, behind a commit, precisely so that a
parser's opinion about one ad can never cost us the payload that ad arrived in.

The tests come in two kinds, and the split matters:

* **Unit**, with a recording session and no database. These pin the *order* of
  operations, which is the whole claim. An order cannot be observed after the
  fact, only while it happens, so the fake is the instrument here -- it is not a
  stand-in for a database, it is the only thing that can see a sequence.
* **Integration**, against the real migrated schema. These pin that the row
  genuinely lands, genuinely keeps the whole payload including the record
  nothing could read, and genuinely survives a failed reading.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CollectionRun,
    CollectionRunStatus,
    Competitor,
    FacebookPage,
    ProviderRun,
    RawResponse,
)
from app.providers.data.mock import MockBatch, MockPage, MockProvider
from app.providers.data.normalize import (
    NormalizationError,
    NormalizationErrorKind,
    normalize_payload,
)
from app.providers.data.provenance import DataOrigin
from app.services import collection as collection_module
from app.services.collection import (
    ERROR_MESSAGE_LIMIT,
    CollectionOrchestrator,
    _describe,
    _excerpt,
)
from tests.conftest import StubAd, StubResult

PAGE_ID = "100000000000031"
COUNTRY = "IN"

#: One ad a reader can make sense of, and one it cannot. Both are stored; only
#: one becomes a `RawAdRecord`. A payload of only the readable ad would let a
#: regression that drops the whole response pass unnoticed.
PAYLOAD_WITH_ONE_BAD_RECORD = {
    "ads": [
        {
            "ad_id": "mock-ad-000701",
            "page_id": PAGE_ID,
            "status": "active",
            "ad_creative_bodies": [{"body": "Readable."}],
        },
        {"page_id": PAGE_ID, "ad_creative_bodies": [{"body": "No identity."}]},
    ]
}


def _page_with(raw: dict[str, Any], page_id: str = PAGE_ID) -> MockPage:
    return MockPage(
        page=SimpleNamespace(provider_page_id=page_id, page_name="Test", url=None),
        batches=(MockBatch(raw=raw),),
    )


def _provider(raw: dict[str, Any], page_id: str = PAGE_ID) -> MockProvider:
    """A provider serving exactly one batch, with no cursor after it.

    The page id is a parameter rather than a constant because the orchestrator
    asks for `run.facebook_page.page_id`, and each integration test creates its
    own page. A provider keyed on the wrong id serves `{"ads": []}`, which would
    make every assertion below pass over an empty response.
    """
    return MockProvider(
        {page_id: _page_with(raw, page_id)},
        clock=lambda: datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
    )


class _RecordingQueue:
    """A queue that remembers being called, so "it never was" is checkable.

    One fake, used by every test here. An earlier version of this file had a
    second queue that raised instead, which meant the assertion about the queue
    seam only held for the test that happened to use the weaker fake.
    """

    def __init__(self) -> None:
        self.enqueued: list[Any] = []

    def enqueue(self, job: Any) -> str:
        self.enqueued.append(job)
        return "job-that-should-not-exist"


# ============================================================
# The order itself
# ============================================================


class _RecordingSession:
    """A session that writes down what it was asked to do, in order.

    Deliberately does nothing else. The orchestrator is handed this instead of a
    database so the sequence is the observable, and a sequence is the entire
    claim under test.
    """

    def __init__(self, run: Any) -> None:
        self.run = run
        self.trace: list[str] = []

    def get(self, model: Any, primary_key: Any) -> Any:
        self.trace.append("get")
        return self.run

    def add(self, instance: Any) -> None:
        self.trace.append(f"add:{type(instance).__name__}")

    def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        """Accepts the S2.1 ad-history upserts and discards them.

        Recorded in the trace so a test can see they happened, but the rows go
        nowhere: this session is a trace, not a database, and the real
        persistence is proved against PostgreSQL in the S2.1 integration tests.
        """
        self.trace.append("execute")
        return StubResult(StubAd(id=uuid.uuid4(), meta_ad_id="stub"))

    def flush(self) -> None:
        self.trace.append("flush")

    def commit(self) -> None:
        self.trace.append("commit")

    def rollback(self) -> None:
        self.trace.append("rollback")


def _fake_run() -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        country=COUNTRY,
        # S2.3: status is per Page + country, so the orchestrator reads the run's
        # page id out before its first commit. Kept on the fake run because the
        # real one has it.
        facebook_page_id=uuid.uuid4(),
        # Read before the orchestrator's first commit and handed to S2.1, whose
        # ad identity is keyed on the provider that issued the ids.
        provider="scripted",
        data_origin=DataOrigin.third_party,
        status=CollectionRunStatus.PENDING,
        started_at=None,
        finished_at=None,
        records_returned=0,
        error_type=None,
        error_message=None,
        facebook_page=SimpleNamespace(
            page_id=PAGE_ID,
            name="Test",
            url="https://example.invalid/page",
        ),
    )


def _record_a_run(monkeypatch: pytest.MonkeyPatch, raw: dict[str, Any]):
    """Run one job against a recording session, returning the trace and outcome.

    The normalizer is wrapped rather than replaced, so the reading under test is
    still the production one -- only its position in the trace is new.
    """
    session = _RecordingSession(_fake_run())
    real = collection_module.normalize_payload
    monkeypatch.setattr(
        collection_module,
        "normalize_payload",
        lambda payload: (session.trace.append("normalize"), real(payload))[1],
    )

    orchestrator = CollectionOrchestrator(
        session,  # type: ignore[arg-type]
        _provider(raw),
        _RecordingQueue(),  # type: ignore[arg-type]
    )
    outcome = orchestrator.execute_collection_job(session.run.id)
    return session, outcome


def test_the_raw_response_is_written_and_committed_before_anything_reads_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The claim, stated as a sequence.

    `add:RawResponse`, then a `commit` that *follows* it, then `normalize`. Read
    any other way round and a parser that disliked one ad would have taken the
    payload with it.

    The commit is located relative to the write rather than to the start of the
    trace. There is an earlier commit -- the one that marks the run RUNNING --
    and asserting against that one would pass even if the commit protecting the
    payload were deleted, which is precisely the regression worth catching.
    """
    session, _ = _record_a_run(monkeypatch, PAYLOAD_WITH_ONE_BAD_RECORD)

    trace = session.trace
    assert "add:RawResponse" in trace, trace
    assert "normalize" in trace, trace

    written = trace.index("add:RawResponse")
    read = trace.index("normalize")
    assert written < read, trace
    assert trace.index("commit", written) < read, trace


def test_nothing_is_written_before_the_provider_is_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    """The session is quiet while the call is in flight.

    Checked in the trace rather than against a real session: this suite's database
    fixture binds every session to an outer transaction that is always rolled
    back, so a real session is *always* "in a transaction" here and could not
    distinguish the orchestrator's discipline from the fixture's.

    This asserts only what it can see: no row is written before the provider is
    called. Whether a transaction is *open* is not observable through this fake,
    and the orchestrator's own answer to that -- reading what it needs out of the
    ORM before committing, so no attribute access reopens one -- is a code
    property rather than a trace property.
    """
    session = _RecordingSession(_fake_run())
    trace_when_fetching: list[list[str]] = []

    class _WatchingProvider(MockProvider):
        def fetch_page_ads(self, *args: Any, **kwargs: Any) -> Any:
            trace_when_fetching.append(list(session.trace))
            return super().fetch_page_ads(*args, **kwargs)

    orchestrator = CollectionOrchestrator(
        session,  # type: ignore[arg-type]
        _WatchingProvider(
            {PAGE_ID: _page_with(PAYLOAD_WITH_ONE_BAD_RECORD)},
            clock=lambda: datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
        ),
        _RecordingQueue(),  # type: ignore[arg-type]
    )
    orchestrator.execute_collection_job(session.run.id)

    assert len(trace_when_fetching) == 1
    at_fetch = trace_when_fetching[0]
    assert at_fetch, "the trace was empty, so this would pass for the wrong reason"
    assert not any(entry.startswith("add:") for entry in at_fetch), at_fetch


def test_the_status_says_which_of_three_outcomes_happened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty record tuple means three different things, and the status tells them apart.

    Without this, a caller holding a `CollectionOutcome` cannot distinguish a run
    that was already terminal from one that reached a provider with nothing to
    report from one that was blocked halfway -- and the last of those is the one
    a human needs to see.
    """
    _, partial = _record_a_run(monkeypatch, PAYLOAD_WITH_ONE_BAD_RECORD)
    assert partial.status is CollectionRunStatus.PARTIAL

    _, clean = _record_a_run(monkeypatch, {"ads": [PAYLOAD_WITH_ONE_BAD_RECORD["ads"][0]]})
    assert clean.status is CollectionRunStatus.COMPLETE

    _, empty = _record_a_run(monkeypatch, {"ads": []})
    assert empty.status is CollectionRunStatus.COMPLETE
    assert empty.records == ()


def test_a_run_that_was_already_terminal_is_reported_as_such(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Doing nothing is not the same as finding nothing."""
    session = _RecordingSession(_fake_run())
    session.run.status = CollectionRunStatus.FAILED

    outcome = CollectionOrchestrator(
        session,  # type: ignore[arg-type]
        _provider(PAYLOAD_WITH_ONE_BAD_RECORD),
        _RecordingQueue(),  # type: ignore[arg-type]
    ).execute_collection_job(session.run.id)

    assert outcome.status is CollectionRunStatus.FAILED
    assert session.trace == ["get"], session.trace


# ============================================================
# The message a run leaves behind
# ============================================================


def test_a_run_message_names_a_few_failures_and_says_how_many_more() -> None:
    """A pointer, capped, with the rest counted rather than dropped.

    Eleven unreadable records produce a message naming five and saying six more.
    The count matters as much as the sample: a reader who knows the total can
    tell a one-off from a systematically broken feed.
    """
    errors = [
        NormalizationError(NormalizationErrorKind.INVALID_DATE, f"field_{index}", "detail")
        for index in range(11)
    ]

    message = _describe(errors)

    assert "11 record(s)" in message
    assert "and 6 more" in message
    for index in range(5):
        assert f"field_{index}" in message
    assert "field_5" not in message


def test_a_whole_payload_failure_is_not_reported_as_a_record_index() -> None:
    """`ads[None]` would be our own bookkeeping wearing the provider's clothes."""
    message = _describe(
        [NormalizationError(NormalizationErrorKind.MALFORMED_PAYLOAD, "payload", "not an object")]
    )

    assert "None" not in message
    assert "payload: not an object" in message


def test_a_run_message_cannot_exceed_the_column() -> None:
    """The bound is enforced here, not inferred from three separate constants.

    `collection_runs.error_message` has a `CHECK` on its length, and an
    `IntegrityError` from the `finally` that writes the run's status would
    supersede whatever was being handled. `detail` is already `repr`-escaped and
    capped by the normalizer, so this is about a belt-and-braces guarantee rather
    than about the reachable worst case.
    """
    errors = [
        NormalizationError(NormalizationErrorKind.INVALID_TYPE, "a" * 400, "d" * 400, index=index)
        for index in range(50)
    ]

    message = _describe(errors)

    assert len(message) <= ERROR_MESSAGE_LIMIT
    assert "\n" not in message


def test_a_provider_error_long_enough_to_break_the_commit_is_excerpted() -> None:
    """A provider message is untrusted text going into a length-checked column.

    `_handle_provider_error` writes `str(error)` straight to a column with a
    `CHECK`. A provider that returned a 5000-character message would raise
    `IntegrityError` from the `finally` block that saves the run's status, which
    is the last place a failure should come from.
    """
    excerpt = _excerpt("x" * 5000 + "\n[INFO] forged log line")

    assert len(excerpt) <= ERROR_MESSAGE_LIMIT
    assert "\n" not in excerpt
    assert "truncated" in excerpt


def test_a_short_error_is_escaped_rather_than_returned_raw() -> None:
    """Short input is still escaped. This used to assert the opposite.

    Returning short text unchanged meant a provider could put a newline into
    `run.error_message` and have it printed as a forged line by anything that
    logs the column. The quotes `repr` adds are the visible cost of closing that;
    the message is still readable, which is what the column is for.
    """
    assert _excerpt("blocked: the provider refused the request") == (
        "'blocked: the provider refused the request'"
    )


def test_excerpt_stays_inside_the_column_even_when_repr_expands_the_text() -> None:
    """The bound is applied to the rendered string, not the input.

    `repr` doubles a backslash and quadruples a control character, so budgeting
    on the input length produces a string several times over the limit -- which
    trips the column's `CHECK` and raises `IntegrityError` from the `finally`
    that saves the run's status. That is precisely the outcome this function
    exists to prevent, and it was reachable from a provider-supplied cursor.
    """
    for hostile in ("\\" * 3000, "\x01" * 3000, "\t" * 3000, "\n" * 3000, "x" * 9000):
        excerpt = _excerpt(hostile)
        assert len(excerpt) <= ERROR_MESSAGE_LIMIT, repr(hostile[:8])
        assert "\n" not in excerpt, repr(hostile[:8])
        assert "\r" not in excerpt, repr(hostile[:8])


# ============================================================
# Partial success
# ============================================================


def test_a_malformed_record_does_not_cost_the_ones_around_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One unreadable ad is one ad, not a page."""
    _, outcome = _record_a_run(monkeypatch, PAYLOAD_WITH_ONE_BAD_RECORD)

    assert [record.external_ad_id for record in outcome.records] == ["mock-ad-000701"]
    assert len(outcome.errors) == 1
    assert outcome.errors[0].kind is NormalizationErrorKind.MISSING_IDENTITY
    assert outcome.errors[0].index == 1


def test_a_readable_payload_reports_nothing_wrong(monkeypatch: pytest.MonkeyPatch) -> None:
    _, outcome = _record_a_run(monkeypatch, {"ads": [PAYLOAD_WITH_ONE_BAD_RECORD["ads"][0]]})

    assert len(outcome.records) == 1
    assert outcome.errors == ()


def test_a_fully_unreadable_payload_reports_every_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing readable is still a payload that arrived, and still gets stored.

    The distinction that matters downstream: this is not a failed run. The
    provider answered, the response is on disk, and a human can go and read it.
    """
    session, outcome = _record_a_run(
        monkeypatch,
        {"ads": [{"page_id": PAGE_ID, "ad_creative_bodies": [{"body": "x"}]}]},
    )

    assert outcome.records == ()
    assert len(outcome.errors) == 1
    assert "add:RawResponse" in session.trace
    assert session.run.status is CollectionRunStatus.PARTIAL
    assert session.run.records_returned == 0


def test_a_run_with_unreadable_records_is_partial_not_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`partial` is the status that means "some of it arrived".

    `ARCHITECTURE.md` forbids treating the output of a partial run as evidence
    about an ad, so this run must be distinguishable from one that got nothing
    and from one that never reached the provider.
    """
    session, _ = _record_a_run(monkeypatch, PAYLOAD_WITH_ONE_BAD_RECORD)

    assert session.run.status is CollectionRunStatus.PARTIAL
    assert session.run.records_returned == 1
    assert session.run.error_message is not None
    assert "ad_id" in session.run.error_message


def test_a_clean_run_is_complete_and_says_nothing_about_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run that read cleanly must not leave a stale explanation behind."""
    session, _ = _record_a_run(monkeypatch, {"ads": [PAYLOAD_WITH_ONE_BAD_RECORD["ads"][0]]})

    assert session.run.status is CollectionRunStatus.COMPLETE
    assert session.run.error_type is None
    assert session.run.error_message is None


# ============================================================
# Against the real schema
# ============================================================


def _full_chain(session: Session, page_id: str) -> CollectionRun:
    competitor = Competitor(name="Corrective Fixture Co")
    session.add(competitor)
    session.flush()
    page = FacebookPage(
        competitor_id=competitor.id,
        page_id=page_id,
        country=COUNTRY,
        tracking_frequency="daily",
        is_tracked=True,
    )
    session.add(page)
    session.flush()
    run = CollectionRun(
        facebook_page_id=page.id,
        provider="mock",
        country=COUNTRY,
        data_origin="third_party",
        status=CollectionRunStatus.PENDING,
        records_returned=0,
    )
    session.add(run)
    session.flush()
    return run


def _orchestrator_for(session: Session, run: CollectionRun, raw: dict[str, Any]):
    """An orchestrator whose provider serves `raw` for *this* run's page.

    Taking the page id from the run is the point. Each integration test creates
    its own page, and a provider keyed on a different id would serve
    `{"ads": []}` -- an empty response against which every assertion below would
    pass for the wrong reason.
    """
    return CollectionOrchestrator(
        session,
        _provider(raw, run.facebook_page.page_id),
        _RecordingQueue(),  # type: ignore[arg-type]
    )


@pytest.mark.integration
def test_the_raw_response_is_stored_and_survives_a_failed_reading(
    db_session: Session,
) -> None:
    """The headline property, against PostgreSQL.

    A reading that could not make sense of one record must leave the stored
    payload complete -- including that record. The `payload_hash` trigger also
    proves the row is a real one and not a pending insert nobody flushed.
    """
    run = _full_chain(db_session, "100000000000032")
    outcome = _orchestrator_for(
        db_session, run, PAYLOAD_WITH_ONE_BAD_RECORD
    ).execute_collection_job(run.id)

    stored = db_session.execute(select(RawResponse)).scalar_one()
    db_session.refresh(stored)
    assert stored.payload == PAYLOAD_WITH_ONE_BAD_RECORD
    assert len(stored.payload["ads"]) == 2
    assert stored.payload_hash is not None

    assert [record.external_ad_id for record in outcome.records] == ["mock-ad-000701"]
    assert len(outcome.errors) == 1


@pytest.mark.integration
def test_the_provider_call_is_recorded_alongside_the_payload_it_kept(
    db_session: Session,
) -> None:
    """One call, one response, and the two are still linked.

    This link is what makes a stored payload diagnosable: the request metadata
    and the cursor say where the response came from, which is the first thing
    anyone wants when a reading turns out to be wrong.
    """
    run = _full_chain(db_session, "100000000000033")
    _orchestrator_for(db_session, run, PAYLOAD_WITH_ONE_BAD_RECORD).execute_collection_job(run.id)

    call = db_session.execute(select(ProviderRun)).scalar_one()
    stored = db_session.execute(select(RawResponse)).scalar_one()

    assert stored.provider_run_id == call.id
    assert call.collection_run_id == run.id
    assert call.request_meta["provider"] == "mock"
    assert call.request_meta["country"] == COUNTRY


@pytest.mark.integration
def test_a_stored_response_can_be_read_again_after_the_run(
    db_session: Session,
) -> None:
    """A parser bug is fixed by re-reading, so the payload has to still be there.

    This is the reason for the ordering. `normalize_payload` is a pure function,
    so re-running it against the stored payload is how a reading gets corrected
    -- which is only possible while the payload is still on disk.
    """
    run = _full_chain(db_session, "100000000000034")
    first = _orchestrator_for(db_session, run, PAYLOAD_WITH_ONE_BAD_RECORD).execute_collection_job(
        run.id
    )

    stored = db_session.execute(select(RawResponse)).scalar_one()
    db_session.refresh(stored)
    second = normalize_payload(stored.payload)

    assert second.records == first.records
    assert second.errors == first.errors


@pytest.mark.integration
def test_a_partially_read_run_is_recorded_as_partial_in_the_database(
    db_session: Session,
) -> None:
    """The status is a stored fact, not just an in-memory one.

    A caller that finds out about the run later has to be able to tell that some
    of it arrived, because the history rules refuse to treat partial output as
    evidence about an ad.
    """
    run = _full_chain(db_session, "100000000000035")
    _orchestrator_for(db_session, run, PAYLOAD_WITH_ONE_BAD_RECORD).execute_collection_job(run.id)

    db_session.refresh(run)
    assert run.status is CollectionRunStatus.PARTIAL
    assert run.records_returned == 1
    assert run.error_message is not None
    assert "ad_id" in run.error_message


@pytest.mark.integration
def test_the_queue_seam_is_untouched_by_a_run(db_session: Session) -> None:
    """The S1.2 job lifecycle is unchanged: executing a run never enqueues.

    Scheduling is the only thing that talks to the queue. This is the seam a
    worker depends on, and the point of returning a `CollectionOutcome` rather
    than changing the queue is that the worker keeps working unchanged.
    """
    run = _full_chain(db_session, "100000000000036")
    queue = _RecordingQueue()

    CollectionOrchestrator(
        db_session,
        _provider(PAYLOAD_WITH_ONE_BAD_RECORD, run.facebook_page.page_id),
        queue,  # type: ignore[arg-type]
    ).execute_collection_job(run.id)

    assert queue.enqueued == []


def test_the_orchestrator_keeps_the_signature_the_worker_depends_on() -> None:
    """Only the positional contract, because only that is a dependency.

    The composition root builds the orchestrator from the session factory, so it
    never passes the safety settings positionally -- they are keyword-only with
    defaults, added by later checkpoints, and asserting their names here would
    fail on the next one for no reason a reader would care about.
    """
    parameters = inspect.signature(CollectionOrchestrator.__init__).parameters
    assert [
        name
        for name, parameter in parameters.items()
        if parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    ] == ["self", "session", "provider", "job_queue"]

    execute = inspect.signature(CollectionOrchestrator.execute_collection_job)
    assert list(execute.parameters) == ["self", "run_id"]
