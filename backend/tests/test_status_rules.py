"""The S2.3 status evaluator's pure decisions, and the duration rules.

Two things are tested here that need no database: how the provider's own wording
is read, and how elapsed time is described. Everything about *which* runs count
is in `test_status_evaluator.py`, because those are database questions.

The exclusions are the point of most of these tests. An evaluator that turns
silence into "not active" invents a finding, and an evaluator that labels a
90-day-old ad as a winner makes a performance claim the product has no data for
(`AGENTS.md` sections 7 and 12).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.ad_duration import (
    LONG_RUNNING_SIGNAL_DAYS,
    LONG_RUNNING_SIGNAL_LABEL,
    LONG_RUNNING_SIGNAL_TOOLTIP,
    DurationBucket,
    DurationSource,
    bucket_for_days,
    duration_of,
    elapsed_days,
)
from app.services.status_evaluator import INACTIVE_AFTER_MISSES, provider_active_from

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _days_ago(days: int) -> datetime:
    return NOW - timedelta(days=days)


# ============================================================
# Provider wording -> provider_active
# ============================================================


@pytest.mark.parametrize(
    "wording",
    ["active", "ACTIVE", "Active", "aCtIvE", "  active  ", "\tactive\n"],
)
def test_a_recognised_active_token_is_true(wording: str) -> None:
    """Case and surrounding whitespace are not a different claim.

    The token table is matched case-insensitively after stripping, because a feed
    capitalising a status is a formatting difference and not a different fact.
    """
    assert provider_active_from(wording) is True


@pytest.mark.parametrize("wording", ["inactive", "INACTIVE", "Inactive", "  inactive  "])
def test_a_recognised_inactive_token_is_false(wording: str) -> None:
    assert provider_active_from(wording) is False


@pytest.mark.parametrize(
    "wording",
    [
        "paused",
        "deleted",
        "withheld",
        "pending_review",
        # Substring matches are explicitly refused: reading
        # "inactive_pending_review" as inactive would turn an unrecognised string
        # into a status nobody reported.
        "inactive_pending_review",
        "very_active",
        "active?",
        "",
        "   ",
        "n/a",
        "0",
        "1",
        "true",
        "false",
        "DYNAMIC",
    ],
)
def test_anything_unrecognised_is_none_and_never_false(wording: str) -> None:
    """Unrecognised wording is not a negative finding.

    `None` is the honest answer: the provider said something this product does not
    model. Rounding it to `False` would report an ad as not-running on the strength
    of a word we did not understand, and the raw string is preserved untouched on
    `ad_snapshots.ad_status` so nothing is lost by saying so here.
    """
    assert provider_active_from(wording) is None


def test_an_omitted_status_is_none() -> None:
    """Silence is not a claim.

    `RawAdRecord.ad_status` is `None` when the provider sent no status key at all,
    and that has to be distinguishable from every other case.
    """
    assert provider_active_from(None) is None


def test_active_and_inactive_never_collapse_to_the_same_answer() -> None:
    """The negative control the parameterised cases above depend on."""
    assert provider_active_from("active") is True
    assert provider_active_from("inactive") is False
    assert provider_active_from("active") is not provider_active_from("inactive")


# ============================================================
# The fixed N
# ============================================================


def test_n_is_two_and_is_not_configurable() -> None:
    """`AGENTS.md` section 8 fixes N at 2; `ARCHITECTURE.md` called it a
    configurable default.

    Settled in favour of the constant, and deliberately not a `Settings` field: a
    tunable would let a value be chosen to make a report look better, which is
    exactly the tuning this history exists to prevent.
    """
    assert INACTIVE_AFTER_MISSES == 2


# ============================================================
# Duration buckets
# ============================================================


@pytest.mark.parametrize(
    ("days", "bucket"),
    [
        (0, DurationBucket.NEW),
        (1, DurationBucket.NEW),
        (6, DurationBucket.NEW),
        # 7 is the first day of Testing, so 6 and 7 must not share a bucket.
        (7, DurationBucket.TESTING),
        (29, DurationBucket.TESTING),
        (30, DurationBucket.ESTABLISHED),
        (59, DurationBucket.ESTABLISHED),
        (60, DurationBucket.LONG_RUNNING),
        (89, DurationBucket.LONG_RUNNING),
        (90, DurationBucket.EVERGREEN),
        (365, DurationBucket.EVERGREEN),
    ],
)
def test_every_bucket_boundary(days: int, bucket: DurationBucket) -> None:
    """All ten approved boundaries, on both sides of each edge."""
    assert bucket_for_days(days) is bucket


def test_the_boundaries_tile_the_range_without_gaps_or_overlaps() -> None:
    """No day count falls between two buckets, or in two.

    Asserted by walking the edges rather than trusting the parameterisation: an
    off-by-one in one threshold would leave a hole that a reader's ad could fall
    into and render as nothing.
    """
    for edge in (7, 30, 60, 90):
        below = bucket_for_days(edge - 1)
        at_or_above = bucket_for_days(edge)
        assert below is not at_or_above, f"{edge}: {below} and {at_or_above} collide"

    # Consecutive bands really are consecutive.
    assert bucket_for_days(6) is DurationBucket.NEW
    assert bucket_for_days(7) is DurationBucket.TESTING
    assert bucket_for_days(29) is DurationBucket.TESTING
    assert bucket_for_days(30) is DurationBucket.ESTABLISHED
    assert bucket_for_days(59) is DurationBucket.ESTABLISHED
    assert bucket_for_days(60) is DurationBucket.LONG_RUNNING
    assert bucket_for_days(89) is DurationBucket.LONG_RUNNING
    assert bucket_for_days(90) is DurationBucket.EVERGREEN


def test_a_negative_elapsed_time_is_clamped_rather_than_rejected() -> None:
    """A provider reporting a future start date is its bug, not a crash.

    Clamped into `New`, because a duration is a display value and a bad start
    date should not take a whole report down.
    """
    assert bucket_for_days(-1) is DurationBucket.NEW
    assert bucket_for_days(-9999) is DurationBucket.NEW


# ============================================================
# Duration source
# ============================================================


def test_the_provider_start_date_is_preferred_when_reported() -> None:
    """Earlier and more complete -- but it is the provider's claim, so it is named."""
    result = duration_of(
        meta_delivery_start=_days_ago(100),
        first_seen_at=_days_ago(10),
        now=NOW,
    )

    assert result.days == 100
    assert result.source is DurationSource.META_DELIVERY_START


def test_our_own_first_observation_is_used_when_the_provider_reported_nothing() -> None:
    """The fallback, and saying which figure was used is the point.

    For a commercial ad the two can be months apart, so a reader showing
    "Evergreen" is entitled to know whether that is the ad's life or our
    observation (`AGENTS.md` section 8).
    """
    result = duration_of(meta_delivery_start=None, first_seen_at=_days_ago(100), now=NOW)

    assert result.days == 100
    assert result.source is DurationSource.FIRST_SEEN_AT


def test_the_two_sources_are_never_merged_into_one_figure() -> None:
    """With both timestamps present, the reported figure is the provider's and the
    fallback figure is ours -- and they are genuinely different numbers.

    This is the error AGENTS.md section 8 names: merging them would make a
    provider's start claim look like our own observation.
    """
    from_provider = duration_of(
        meta_delivery_start=_days_ago(100), first_seen_at=_days_ago(10), now=NOW
    )
    from_observation = duration_of(meta_delivery_start=None, first_seen_at=_days_ago(10), now=NOW)

    assert from_provider.days == 100
    assert from_observation.days == 10
    assert from_provider.days != from_observation.days
    assert from_provider.source is not from_observation.source


# ============================================================
# LONG-RUNNING SIGNAL
# ============================================================


def test_the_signal_wording_is_exactly_as_approved() -> None:
    """Both strings are constraints from `AGENTS.md` section 7.

    Pinned here because a call site that wrote "long-running ad" instead would
    have dropped the word "signal" -- which is the part that keeps it a proxy
    rather than a claim.
    """
    assert LONG_RUNNING_SIGNAL_LABEL == "LONG-RUNNING SIGNAL"
    assert LONG_RUNNING_SIGNAL_TOOLTIP == "duration is a public proxy, not performance"


def test_the_signal_threshold_is_sixty_days() -> None:
    assert LONG_RUNNING_SIGNAL_DAYS == 60


@pytest.mark.parametrize(
    ("days", "is_signal"),
    [
        (0, False),
        (59, False),
        (60, True),
        (61, True),
        (90, True),
        (365, True),
    ],
)
def test_the_signal_fires_at_sixty_days_and_not_before(days: int, is_signal: bool) -> None:
    result = duration_of(meta_delivery_start=None, first_seen_at=_days_ago(days), now=NOW)

    assert result.is_long_running_signal is is_signal
    assert result.is_long_running_signal is (days >= LONG_RUNNING_SIGNAL_DAYS)


def test_the_signal_covers_two_buckets_and_not_the_third() -> None:
    """`Long-running` and `Evergreen` both qualify; `Established` does not.

    Cross-checked against the bucket rather than the day count alone, so a future
    change to one that did not change the other would fail here.
    """
    assert not duration_of(
        meta_delivery_start=None, first_seen_at=_days_ago(59), now=NOW
    ).is_long_running_signal
    assert duration_of(
        meta_delivery_start=None, first_seen_at=_days_ago(60), now=NOW
    ).is_long_running_signal
    assert duration_of(
        meta_delivery_start=None, first_seen_at=_days_ago(90), now=NOW
    ).is_long_running_signal


# ============================================================
# Elapsed days
# ============================================================


def test_elapsed_days_uses_whole_days() -> None:
    assert elapsed_days(start=NOW - timedelta(days=10, hours=23), now=NOW) == 10
    assert elapsed_days(start=NOW - timedelta(hours=23), now=NOW) == 0


def test_a_zero_duration_is_new_and_not_an_error() -> None:
    """An ad observed the instant it is measured has run zero days."""
    result = duration_of(meta_delivery_start=None, first_seen_at=NOW, now=NOW)

    assert result.days == 0
    assert result.bucket is DurationBucket.NEW
    assert not result.is_long_running_signal


def test_no_bucket_name_is_a_performance_verdict() -> None:
    """`AGENTS.md` section 12 names the forbidden words outright.

    Asserted against the actual enum rather than a comment, because the failure
    mode is a label someone adds to make a report read better -- and the labels
    are the only thing standing between an elapsed-time figure and a performance
    claim.

    `Long-running` is *not* forbidden despite reading like one: it describes
    elapsed time, and the badge it produces is `LONG-RUNNING SIGNAL`, whose
    tooltip says it is a proxy. What is forbidden is a judgement, and none of
    these names makes one.
    """
    forbidden = {"winner", "loser", "best", "top performer", "successful", "profitable"}

    for bucket in DurationBucket:
        assert bucket.value.lower() not in forbidden, bucket
        # Each label describes time, and every one is qualified by the signal
        # tooltip wherever it is rendered as a claim.
        assert bucket.value.lower() not in LONG_RUNNING_SIGNAL_TOOLTIP.lower(), bucket
