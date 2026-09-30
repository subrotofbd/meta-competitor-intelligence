"""A provider payload becomes a `RawAdRecord` here, and nowhere else.

S1.3 is normalizer-only. The normalised ad itself is not persisted yet: the
repository assigns `ads` and `ad_snapshots` to S2.1, so this module stops at
the value object. What it owns is the *reading* -- the one place that decides
which provider key is the ad id, that a naive timestamp is a provider bug
rather than something to assume a timezone for, and that a URL we would not
fetch is not quietly kept.

## Where this sits in the collection flow

`ARCHITECTURE.md` gives the order as collect -> keep raw -> normalize, and this
module is the second step. `CollectionOrchestrator` writes the provider response
to `raw_responses` and commits it *before* calling anything here, so a parser
mistake is a re-runnable opinion about evidence that is already durable. A
reading that refuses a record costs that record, not the response it arrived in.

This module never opens a session, writes a file, or reaches the network, which
is what `test_architecture_boundaries` checks for every provider package. That
is not a style preference: it is what makes re-reading a stored payload during a
replay possible, and what keeps a parser out of the position of deciding what is
worth keeping.

## What "deterministic" means here

The same payload maps to the same records, in the same order, on every call.
There is no clock, no randomness, and no dependence on anything outside the
payload -- so a normalisation can be re-run against a stored raw response
during a replay and produce exactly what it produced the first time.

## Absence is never filled in

A field the provider did not report stays `None`. It is never `""`, never `0`,
never a plausible-looking stand-in. The three absences the product has to tell
apart are kept apart rather than flattened:

    key absent      -> the field's own default (`None`, or `()` for a list)
    key present, null -> `None` / `()`
    key present, ""   -> `""`  -- the provider really did send an empty string

## Failures are structured, and a batch is not all-or-nothing

`normalize_record` raises `RecordRejectedError` carrying a `NormalizationError` that
names the field and what was wrong with it. `normalize_payload` collects those
across a batch instead of stopping, so one unreadable ad costs one ad: the valid
records still come back and the failure is still reported rather than swallowed.
Which of the two a caller wants is a policy decision, and the module offers both
without having to guess on its behalf.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

from pydantic import ValidationError

from app.providers.data.models import AdFormat, MediaRef, RawAdRecord, RawPayload

#: Record-level keys this module reads. Anything else the provider sent is kept
#: in `provider_metadata` rather than dropped, so a field nobody modelled yet is
#: still available when someone does.
MAPPED_RECORD_KEYS: Final = frozenset(
    {
        "ad_id",
        "ad_creative_bodies",
        "ad_delivery_start_time",
        "format",
        "page_id",
        "page_name",
        "platforms",
        "status",
        "targeted_countries",
    }
)

#: The same one level down, inside a creative body. A body carries more text
#: slots than `RawAdRecord` models -- the link card's own title has nowhere to
#: go -- and the leftovers are kept rather than dropped.
MAPPED_BODY_KEYS: Final = frozenset(
    {
        "body",
        "call_to_action",
        "link_description",
        "link_url",
        "media",
        "title",
    }
)

#: The one creative shape a record can carry. A carousel is a single body
#: holding several media entries, which is how a real feed reports it too.
CREATIVE_BODY_KEY: Final = "ad_creative_bodies"

#: Where a batch of records lives inside a provider payload.
ADS_KEY: Final = "ads"


class NormalizationErrorKind(StrEnum):
    """Why a record could not be read.

    Kept as distinct kinds rather than one "invalid" because the fix differs: a
    missing identity means the provider omitted something we require, a bad URL
    means it sent something we will not fetch, and a malformed payload means the
    shape is not one this product can read.

    A kind says *what class of problem* this is. It does not say whether one
    record or the whole response is affected -- `NormalizationError.index` does
    that, being `None` for the response envelope and a position within the
    batch for a single ad. A caller that wants "stop the run" watches for the
    envelope, not for a particular kind.
    """

    MALFORMED_PAYLOAD = "malformed_payload"
    MISSING_IDENTITY = "missing_identity"
    INVALID_TYPE = "invalid_type"
    INVALID_URL = "invalid_url"
    INVALID_DATE = "invalid_date"


@dataclass(frozen=True, slots=True)
class NormalizationError:
    """One reason a record was not produced.

    Attributes:
        kind: Which class of problem this is.
        field: The provider key at fault, as the provider spelled it.
        detail: What was received, in words safe to log. Provider text reaches
            this string only through `_safe`, so it cannot carry a newline and
            forge a log record, and it cannot flood one.
        index: Where the record sat in the batch, or `None` when the failure is
            about the payload envelope rather than one ad inside it.
    """

    kind: NormalizationErrorKind
    field: str
    detail: str
    index: int | None = None


class RecordRejectedError(Exception):
    """One provider record could not be read into a `RawAdRecord`.

    Carries the structured error rather than only a message, so a caller can
    map it onto whatever error vocabulary it already speaks.
    """

    def __init__(self, error: NormalizationError) -> None:
        super().__init__(f"{error.kind} at {error.field!r}: {error.detail}")
        self.error = error


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    """What a payload yielded: the readable records, and what could not be read.

    Both are returned together on purpose. Dropping the errors would make a
    malformed ad disappear silently, and returning nothing on the first failure
    would let one bad record cost every good one.

    Attributes:
        records: Records read from the payload, in payload order.
        errors: Every record that could not be read, with its batch index.
    """

    records: tuple[RawAdRecord, ...]
    errors: tuple[NormalizationError, ...]


#: How much of an offending value a `detail` may quote. A provider that sends a
#: megabyte-long timestamp should not be able to write a megabyte into a log.
DETAIL_LIMIT: Final = 120


def _safe(value: Any, limit: int = DETAIL_LIMIT) -> str:
    """Render untrusted provider input as a single safe log line.

    `detail` is documented as safe to log, and it is going to be: a provider
    that returns a body of `"x\\n[INFO] collection finished"` would otherwise be
    able to forge a log record, and a provider that returns ten kilobytes of
    junk would otherwise be able to bury the run it is failing.

    `repr` is what does the work, not an allowlist: it escapes newlines and
    other control characters, and it distinguishes an empty string from the
    string `"None"`, which matters when the whole point is reporting what was
    actually received.
    """
    rendered = repr(value)
    if len(rendered) > limit:
        return f"{rendered[:limit]}... ({len(rendered)} characters)"
    return rendered


def _reject(
    kind: NormalizationErrorKind,
    field: str,
    detail: str,
    index: int | None = None,
) -> RecordRejectedError:
    """Build the one exception type callers are expected to catch."""
    return RecordRejectedError(NormalizationError(kind, field, detail, index))


# ============================================================
# Field readers. Each one preserves absence rather than filling it.
# ============================================================


def _read_identity(raw: Mapping[str, Any]) -> str:
    """The provider's ad id: the one field a record cannot exist without.

    An ad we cannot identify cannot be tracked, ever, so there is no fallback.
    A blank or non-string id is rejected rather than coerced -- `"12345"` would
    be indistinguishable from an id the provider actually issued.

    A padded id is rejected too, and the padding is not trimmed off. Trimming
    would mean the stored identity is not the identity the provider sent, and
    accepting both spellings would mean one ad can be two rows of history
    depending on which response a run happened to read.
    """
    value = raw.get("ad_id")
    if value is None:
        raise _reject(NormalizationErrorKind.MISSING_IDENTITY, "ad_id", "absent")
    if not isinstance(value, str):
        raise _reject(
            NormalizationErrorKind.MISSING_IDENTITY, "ad_id", f"got {type(value).__name__}"
        )
    if not value.strip():
        raise _reject(NormalizationErrorKind.MISSING_IDENTITY, "ad_id", "blank")
    if value != value.strip():
        raise _reject(
            NormalizationErrorKind.MISSING_IDENTITY,
            "ad_id",
            f"padded: {_safe(value)}",
        )
    return value


def _read_text(raw: Mapping[str, Any], key: str) -> str | None:
    """Copy fields verbatim. No trimming, no rewriting, no case folding.

    An empty string stays an empty string: the provider said there was no text,
    which is not the same claim as saying nothing at all.
    """
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _reject(NormalizationErrorKind.INVALID_TYPE, key, f"got {type(value).__name__}")
    return value


def _read_string_tuple(raw: Mapping[str, Any], key: str) -> tuple[str, ...]:
    """A provider's list of labels.

    Both the container and its contents are checked, and neither is coerced.
    Reading a bare string as a list is the corruption that produces
    `('f', 'a', 'c')` and calls it a platform; reading an arbitrary object with
    `str()` is the same corruption one level down, where `{"a": 1}` becomes the
    observed label `"{'a': 1}"`. A label nobody can explain is worse than a
    record that was refused, because it is stored and displayed as fact.
    """
    value = raw.get(key)
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise _reject(
            NormalizationErrorKind.INVALID_TYPE, key, f"expected a list, got {type(value).__name__}"
        )
    for position, item in enumerate(value):
        if not isinstance(item, str):
            raise _reject(
                NormalizationErrorKind.INVALID_TYPE,
                f"{key}[{position}]",
                f"expected a string, got {type(item).__name__}",
            )
    return tuple(value)


def _read_datetime(raw: Mapping[str, Any], key: str) -> datetime | None:
    """Parse a provider timestamp without ever supplying a missing timezone.

    A naive timestamp is refused rather than assumed to be UTC: guessing shifts
    a delivery start by up to a day, and a delivery start is the field the
    duration display is built from.

    An empty string reads as "not reported". `""` is the usual spelling of an
    absent value in a feed that also uses `null`, and it is not a timestamp --
    so this is the one place an empty value collapses into absence, because
    `datetime | None` has no other honest answer to give.
    """
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _reject(
            NormalizationErrorKind.INVALID_TYPE,
            key,
            f"expected an ISO timestamp string, got {type(value).__name__}",
        )
    if not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        # The interpreter's wording is worth keeping -- it is why the value was
        # refused -- but it is passed through `_safe` first, because the value
        # it quotes came from the provider and is going into a log line.
        raise _reject(NormalizationErrorKind.INVALID_DATE, key, _safe(str(error))) from error
    if parsed.tzinfo is None:
        raise _reject(NormalizationErrorKind.INVALID_DATE, key, "timestamp carries no UTC offset")
    return parsed


def _has_host(value: str) -> bool:
    """Whether a URL names something to connect to.

    A deliberate non-parser: `urllib` is on the offline guard's blocklist for
    this package, and a provider package that cannot open a socket has no
    business importing one even to read a string. This takes the authority
    section between the scheme and the first path, query or fragment, drops any
    `user:password@` prefix, and asks whether a host is left.

    It answers "is there a host", not "is this a well-formed URL". Anything
    richer -- ports, IPv6 literals, percent-encoding, IDN -- is left to a later
    checkpoint that actually requests one, which belongs where a request is
    being made rather than here.
    """
    _, _, remainder = value.partition("://")
    authority = remainder.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    host = authority.rsplit("@", 1)[-1].split(":", 1)[0]
    # `://:8443`, `:// ` and `://.` all leave an authority with nothing in it
    # that could be connected to, and none of them is a host.
    return bool(host.strip().strip("."))


def _read_url(raw: Mapping[str, Any], key: str) -> str | None:
    """Keep a URL only if we would actually be willing to fetch it.

    http(s) only, and otherwise the provider's exact string -- no scheme
    case-folding, no trailing-slash repair, no percent-encoding cleanup. A URL
    later checkpoints fetch is untrusted input, and quietly editing it is how a
    malformed value comes to look like a valid one.

    An empty string reads as "not reported", for the same reason an empty
    timestamp does. A blank field is a blank field, not a broken URL, and
    reporting it as a broken one would send someone hunting a fetch problem
    that does not exist.

    ## What passing this is not

    A pass on scheme, control characters and host presence is not a fetch-safety
    policy. Whether a URL may be *requested* at all -- loopback, link-local,
    cloud-metadata addresses, redirects -- belongs to whoever requests it, and
    can only be decided there, because only the requester knows the network it
    is on. What this module guarantees is the narrower thing the record depends
    on: a stored URL is a syntactically whole http(s) URL, not a fragment that
    looked plausible enough to keep.
    """
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _reject(
            NormalizationErrorKind.INVALID_TYPE,
            key,
            f"expected a URL string, got {type(value).__name__}",
        )
    if not value.strip():
        return None
    lowered = value.lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        raise _reject(NormalizationErrorKind.INVALID_URL, key, "scheme must be http or https")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        # A CR or LF inside a stored URL is a request-splitting payload aimed at
        # whatever HTTP client a later checkpoint adds. Refused, not stripped:
        # stripping it would mean storing a URL the provider did not send.
        raise _reject(NormalizationErrorKind.INVALID_URL, key, "contains a control character")
    if not _has_host(value):
        raise _reject(NormalizationErrorKind.INVALID_URL, key, "no host")
    return value


def _read_display_format(raw: Mapping[str, Any]) -> AdFormat | None:
    """The creative shape, or `None` when the provider named one we do not model.

    `None` rather than a guess. The original wording is not lost: it is kept in
    `provider_metadata`, so widening `AdFormat` later is a display decision
    rather than a re-collection.
    """
    value = raw.get("format")
    if value is None:
        return None
    try:
        return AdFormat(value)
    except ValueError:
        return None


#: Which Python types a media dimension may be. A provider that reports its
#: width as `"1080"` is refused rather than read, because a measurement we
#: converted is a measurement we can no longer say the provider reported.
#: `bool` is excluded on purpose: Python says a boolean *is* an `int`, so
#: without this `true` would quietly become a height of one pixel.
_MEDIA_INTEGERS: Final = (int,)
_MEDIA_NUMBERS: Final = (int, float)


def _read_typed(
    entry: Mapping[str, Any],
    key: str,
    types: tuple[type, ...],
) -> Any:
    """One media dimension, refused rather than coerced.

    A model in lax mode will happily turn `"1080"` into `1080` and `true` into
    `1`. Convenient, and exactly the invention this module exists to prevent: a
    stored measurement has to be one the provider reported in a shape we read.
    """
    value = entry.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, types):
        raise _reject(
            NormalizationErrorKind.INVALID_TYPE,
            key,
            f"expected {' or '.join(t.__name__ for t in types)}, got {type(value).__name__}",
        )
    return value


def _read_media(body: Mapping[str, Any]) -> tuple[MediaRef, ...]:
    """Every asset the body references. An absent list yields none, not a guess.

    Each entry needs a usable `key`: it is the asset's identity until the bytes
    are downloaded and hashed, and a placeholder would silently compare equal
    across unrelated creatives.

    `MediaRef` owns the remaining constraints -- a width of at least one pixel,
    a non-negative duration -- and a rejection by it is converted into the same
    structured error every other failure uses, so a caller never has to know
    which fields this function policed and which the model did.
    """
    entries = body.get("media")
    if entries is None:
        return ()
    if not isinstance(entries, (list, tuple)):
        raise _reject(
            NormalizationErrorKind.INVALID_TYPE,
            "media",
            f"expected a list, got {type(entries).__name__}",
        )

    media: list[MediaRef] = []
    for position, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise _reject(
                NormalizationErrorKind.INVALID_TYPE, f"media[{position}]", "entry is not an object"
            )
        key = entry.get("key")
        if not isinstance(key, str) or not key.strip():
            raise _reject(
                NormalizationErrorKind.MISSING_IDENTITY, f"media[{position}].key", "absent or blank"
            )
        try:
            media.append(
                MediaRef(
                    provider_key=key,
                    source_url=_read_url(entry, "url"),
                    mime=_read_typed(entry, "mime", (str,)),
                    width=_read_typed(entry, "width", _MEDIA_INTEGERS),
                    height=_read_typed(entry, "height", _MEDIA_INTEGERS),
                    duration_seconds=_read_typed(entry, "duration_seconds", _MEDIA_NUMBERS),
                )
            )
        except ValidationError as error:
            raise _reject(
                NormalizationErrorKind.INVALID_TYPE,
                f"media[{position}].{_first_field(error)}",
                _safe(_first_message(error)),
            ) from error
    return tuple(media)


def _read_body(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    """The single creative body a record carries.

    A carousel is one body holding several media entries, not several bodies.
    A record with no body at all is a payload we cannot read rather than an ad
    with no copy, so it is refused instead of being written out as a row of
    nulls that would read as "the provider reported nothing".
    """
    bodies = raw.get(CREATIVE_BODY_KEY)
    if bodies is None:
        raise _reject(NormalizationErrorKind.MALFORMED_PAYLOAD, CREATIVE_BODY_KEY, "absent")
    if not isinstance(bodies, (list, tuple)) or not bodies:
        raise _reject(
            NormalizationErrorKind.MALFORMED_PAYLOAD,
            CREATIVE_BODY_KEY,
            f"expected a non-empty list, got {_safe(bodies)}",
        )
    body = bodies[0]
    if not isinstance(body, Mapping):
        raise _reject(
            NormalizationErrorKind.MALFORMED_PAYLOAD,
            CREATIVE_BODY_KEY,
            "first entry is not an object",
        )
    return body


def _unmapped_fields(
    raw: Mapping[str, Any],
    body: Mapping[str, Any],
    format_value: Any,
    display_format: AdFormat | None,
) -> dict[str, Any]:
    """Everything the provider sent that this product does not model.

    Collected rather than dropped. The unrecognised creative shape is included
    too: it was read, just not understood, and losing it would make a `None`
    look like a provider that said nothing rather than one we could not read.

    One flat namespace holds both levels, because a nested one would be a
    breaking change to a field the S0.3 contract already defined. Where a record
    key and a body key collide, the **record** key wins: it is the less
    specific of the two, so the more specific one is the likelier to be a
    provider's own naming of something we have not modelled yet, and the
    collision is a decision rather than an accident.

    These keys and values are untrusted provider data. They are never
    identifiers, never column names, never path segments, and never anything
    that is interpolated into a query, a URL or a prompt.
    """
    fields: dict[str, Any] = {
        key: value for key, value in body.items() if key not in MAPPED_BODY_KEYS
    }
    fields.update((key, value) for key, value in raw.items() if key not in MAPPED_RECORD_KEYS)
    if format_value is not None and display_format is None:
        fields["format"] = format_value
    return fields


def _read_cta(body: Mapping[str, Any]) -> str | None:
    """The call to action, as the provider labelled it.

    Provider wording, never translated: our own status vocabulary is a different
    thing and is decided from our runs, not from the provider's label.
    """
    action = body.get("call_to_action")
    if action is None:
        return None
    if not isinstance(action, Mapping):
        raise _reject(
            NormalizationErrorKind.INVALID_TYPE,
            "call_to_action",
            f"expected an object, got {type(action).__name__}",
        )
    return _read_text(action, "type")


# ============================================================
# The two entry points
# ============================================================


def normalize_record(raw: Mapping[str, Any]) -> RawAdRecord:
    """Read one provider record into a `RawAdRecord`.

    Args:
        raw: A single record, exactly as the provider sent it.

    Returns:
        The normalised record. Every field the provider did not report is `None`
        or `()`, never a substitute value.

    Raises:
        RecordRejectedError: The record cannot be read without inventing something.
            Carries a `NormalizationError` naming the field and the problem.
    """
    if not isinstance(raw, Mapping):
        raise _reject(
            NormalizationErrorKind.MALFORMED_PAYLOAD,
            "record",
            f"expected an object, got {type(raw).__name__}",
        )

    external_ad_id = _read_identity(raw)
    body = _read_body(raw)
    display_format = _read_display_format(raw)

    fields: dict[str, Any] = {
        "external_ad_id": external_ad_id,
        "page_id": _read_text(raw, "page_id"),
        "page_name": _read_text(raw, "page_name"),
        "platforms": _read_string_tuple(raw, "platforms"),
        "countries": _read_string_tuple(raw, "targeted_countries"),
        "ad_status": _read_text(raw, "status"),
        "meta_delivery_start": _read_datetime(raw, "ad_delivery_start_time"),
        "primary_text": _read_text(body, "body"),
        "headline": _read_text(body, "title"),
        "description": _read_text(body, "link_description"),
        "cta": _read_cta(body),
        "destination_url": _read_url(body, "link_url"),
        "media": _read_media(body),
        "display_format": display_format,
        "provider_metadata": _unmapped_fields(raw, body, raw.get("format"), display_format),
    }

    try:
        return RawAdRecord(**fields)
    except ValidationError as error:
        # The readers above cover the shapes we choose to police; this catches
        # anything a model constraint rejects, so a caller never has to know
        # whether a given field was checked here or by the model.
        raise _reject(
            NormalizationErrorKind.INVALID_TYPE,
            _first_field(error),
            _safe(_first_message(error)),
        ) from error


def normalize_payload(payload: RawPayload) -> NormalizationResult:
    """Read every record in a provider payload.

    Partial success is the default. A record that cannot be read is reported in
    `errors` with the index it sat at, and the records around it are still
    returned -- one unreadable ad must not cost every good ad in the response.

    Duplicate ad ids are *not* merged or rejected. A provider may legitimately
    serve the same ad twice within one walk with different copy, and collapsing
    that here would throw away an observation before anything downstream has had
    a chance to decide what it means.

    Args:
        payload: The provider response, exactly as stored in `raw_responses`.

    Returns:
        The readable records in payload order, plus every failure encountered.
    """
    if not isinstance(payload, Mapping):
        return NormalizationResult(
            (),
            (
                NormalizationError(
                    NormalizationErrorKind.MALFORMED_PAYLOAD,
                    "payload",
                    f"expected an object, got {type(payload).__name__}",
                ),
            ),
        )

    ads = payload.get(ADS_KEY)
    if ads is None:
        # A provider that reports no ads reports an empty list. Not a failure.
        return NormalizationResult((), ())
    if isinstance(ads, str) or not isinstance(ads, (list, tuple)):
        return NormalizationResult(
            (),
            (
                NormalizationError(
                    NormalizationErrorKind.MALFORMED_PAYLOAD,
                    ADS_KEY,
                    f"expected a list, got {type(ads).__name__}",
                ),
            ),
        )

    records: list[RawAdRecord] = []
    errors: list[NormalizationError] = []
    for index, ad in enumerate(ads):
        try:
            records.append(normalize_record(ad))
        except RecordRejectedError as rejected:
            error = rejected.error
            errors.append(NormalizationError(error.kind, error.field, error.detail, index=index))

    return NormalizationResult(tuple(records), tuple(errors))


def _first_field(error: ValidationError) -> str:
    """The provider-facing name of the first field a model constraint rejected."""
    first = error.errors()[0]
    location = first.get("loc") or ()
    return ".".join(str(part) for part in location) or "record"


def _first_message(error: ValidationError) -> str:
    """A model's rejection text, which is already written to be safe to log."""
    return str(error.errors()[0].get("msg", "rejected by the record model"))
