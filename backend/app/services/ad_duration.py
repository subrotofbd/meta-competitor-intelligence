"""How long an ad has been running, in words that do not overclaim.

## The one rule this module exists to enforce

A duration is a **public proxy, never a performance claim**. An ad that has run
for 90 days tells you it has run for 90 days. It does not tell you the ad worked,
that it beat a competitor, or that anyone bought anything -- and no metric in this
product may imply otherwise. `AGENTS.md` section 7 forbids labelling longevity a
verdict, and section 12 forbids the words outright: never "winner", "loser",
"best", or "top performer".

So the labels here are deliberately dull. `Established` is not `Successful`.
`Evergreen` is not `Evergreen performer`. The bucket names describe elapsed time
and nothing else, and the one signal this product does surface has an exact
documented wording: **`LONG-RUNNING SIGNAL`** with the tooltip *"duration is a
public proxy, not performance"*.

## Two start timestamps, and saying which one was used

`meta_delivery_start` is the provider's claim about when the ad began.
`first_seen_at` is when *we* first observed it. For a commercial ad those can be
months apart, and `AGENTS.md` section 8 forbids merging them.

The provider's date is preferred when present because it is the earlier and more
complete claim, but using it is not free: it is a provider assertion, so
`Duration.source` reports which timestamp the number came from and any display
**must state it**. A reader seeing "Evergreen" is entitled to know whether that is
90 days of the ad's life or 90 days of our observation.

## No clock is called here

Every function takes `now` explicitly. A duration that read the system clock would
make a report unreproducible, and would make the boundary tests impossible to
write -- which is why the thresholds are a pure function of (elapsed days, now)
rather than something a test has to freeze time around.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

#: The exact label this product uses for a long-running ad, and the exact tooltip.
#:
#: Both are constants rather than literals at a call site because `AGENTS.md`
#: section 7 constrains the wording itself: the badge and its qualification ship
#: together or not at all, and a caller that wrote "long-running ad" instead would
#: have dropped the word "signal" -- which is the part that keeps it a proxy.
LONG_RUNNING_SIGNAL_LABEL: Final = "LONG-RUNNING SIGNAL"
LONG_RUNNING_SIGNAL_TOOLTIP: Final = "duration is a public proxy, not performance"

#: The day count at and above which an ad is a long-running signal. Approved, not
#: assumed: `ARCHITECTURE.md` originally marked these boundaries as "my
#: assumption", which is why they are pinned here with a test on every edge.
LONG_RUNNING_SIGNAL_DAYS: Final = 60

#: One day as this module counts it. Calendar-aware arithmetic would make
#: "89 days" depend on the month lengths between two dates, and a bucket boundary
#: that moves with the calendar is a boundary nobody can explain.
_DAY: Final = timedelta(days=1)


class DurationSource(StrEnum):
    """Which timestamp a duration was measured from.

    Reported alongside every duration so a display can state it. `AGENTS.md`
    section 8 requires any duration display to say which one it used.
    """

    META_DELIVERY_START = "meta_delivery_start"
    """The provider's reported start date. Earlier and more complete, but it is
    the provider's claim rather than our observation."""

    FIRST_SEEN_AT = "first_seen_at"
    """Our own first observation. Always available, and the honest fallback when
    the provider reported nothing."""


class DurationBucket(StrEnum):
    """Elapsed time, described without judgement.

    The names describe how long, not how well. `ESTABLISHED` means "30-59 days",
    full stop -- it is not a claim that the ad is working.
    """

    NEW = "New"
    TESTING = "Testing"
    ESTABLISHED = "Established"
    LONG_RUNNING = "Long-running"
    EVERGREEN = "Evergreen"


#: Inclusive lower bound in days for each bucket, highest first, so the first
#: match wins and no bucket can be reached by two rules.
_BUCKET_BOUNDS: Final[tuple[tuple[int, DurationBucket], ...]] = (
    (90, DurationBucket.EVERGREEN),
    (60, DurationBucket.LONG_RUNNING),
    (30, DurationBucket.ESTABLISHED),
    (7, DurationBucket.TESTING),
    (0, DurationBucket.NEW),
)


@dataclass(frozen=True, slots=True)
class Duration:
    """One ad's elapsed running time, and where it was measured from.

    Attributes:
        days: Whole days elapsed. Negative values are clamped to zero, because a
            provider-reported start date in the future is a provider bug and must
            not render as a negative age.
        bucket: Which of the five bands this falls in.
        source: Which timestamp was used, so a display can say so.
        is_long_running_signal: Whether this crosses the documented 60-day signal
            threshold. A convenience over `bucket`, named for the constant rather
            than the band so a reader cannot mistake it for a quality judgement.
    """

    days: int
    bucket: DurationBucket
    source: DurationSource
    is_long_running_signal: bool


def elapsed_days(*, start: datetime, now: datetime) -> int:
    """Whole days from `start` to `now`, never negative.

    Both must be timezone-aware; a naive value would raise on the subtraction
    rather than silently producing a plausible-looking number, which is the
    behaviour this project prefers everywhere else.
    """
    delta: timedelta = now - start
    return max(0, delta // _DAY)


def bucket_for_days(days: int) -> DurationBucket:
    """The band a whole day count falls into.

    The boundaries are 0, 7, 30, 60 and 90, each inclusive at its lower edge.
    Below zero is clamped into `New` rather than raising, because a duration is a
    display value and a bad start date should not take a report down with it.
    """
    for threshold, bucket in _BUCKET_BOUNDS:
        if days >= threshold:
            return bucket
    return DurationBucket.NEW


def duration_of(
    *,
    meta_delivery_start: datetime | None,
    first_seen_at: datetime,
    now: datetime,
) -> Duration:
    """One ad's duration, preferring the provider's start date when it reported one.

    Args:
        meta_delivery_start: The provider-reported start, or `None` when the
            provider did not report one.
        first_seen_at: Our own first observation. Always used as the fallback.
        now: The instant to measure to, passed in rather than read from a clock.

    Returns:
        The duration, with the source it was measured from. `first_seen_at` is
        used whenever the provider reported nothing, and saying so is the point:
        the two figures can be months apart for a commercial ad.
    """
    source = (
        DurationSource.META_DELIVERY_START
        if meta_delivery_start is not None
        else DurationSource.FIRST_SEEN_AT
    )
    start = meta_delivery_start if meta_delivery_start is not None else first_seen_at
    days = elapsed_days(start=start, now=now)

    return Duration(
        days=days,
        bucket=bucket_for_days(days),
        source=source,
        is_long_running_signal=days >= LONG_RUNNING_SIGNAL_DAYS,
    )
