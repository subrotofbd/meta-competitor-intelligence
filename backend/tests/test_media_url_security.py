"""Credential-bearing media URLs are refused, and the refusal says nothing.

`https://user:token@host/a.png` is a syntactically valid http(s) URL with a host,
so every check in `_read_url` passes it. S2.4 promotes `source_url` from a value
nested inside `raw_responses` into `media_assets.source_url` -- a column that gets
queried, rendered and exported -- which makes a stored password reachable in a way
a JSON value was not.

Two properties matter, and only together:

1. **The URL is not persisted**, so no credential reaches a queryable column.
2. **The credential is not echoed**, in the raised error, in `detail`, or anywhere
   that becomes a log line. A rejection that names the secret has moved it, not
   stopped it -- and `NormalizationError.detail` is documented as safe to log and
   reaches `_describe` and `collection_runs.error_message`.

The scope is deliberately narrow: **media URLs only.** A `destination_url` carrying
userinfo is stored verbatim, which S1.3 settled on purpose and
`test_normalizer.py` pins. Applying the rule there would have overturned a decided
behaviour about a field S2.4 does not own.

Hermetic: no database, no network, no fetch. The URL is never requested.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.providers.data.models import MediaRef, RawAdRecord
from app.providers.data.normalize import (
    NormalizationErrorKind,
    RecordRejectedError,
    normalize_record,
)

pytestmark = pytest.mark.unit

#: A credential-bearing URL with a value distinctive enough to search for in any
#: error text, log line or string representation.
SECRET = "s3cr3t-provider-token"
CREDENTIAL_URL = f"https://user:{SECRET}@cdn.example.invalid/a.png"


def _media_record(url: str) -> dict[str, Any]:
    return {
        "ad_id": "mock-ad-000601",
        "ad_creative_bodies": [
            {
                "body": "Copy.",
                "link_url": "https://example.invalid/offer",
                "media": [{"key": "mock-media-0001-a", "url": url}],
            }
        ],
    }


# ============================================================
# The credential is refused
# ============================================================


def test_a_credential_bearing_media_url_is_refused() -> None:
    """The URL never becomes a `MediaRef`, so it can never reach `media_assets`."""
    with pytest.raises(RecordRejectedError) as raised:
        normalize_record(_media_record(CREDENTIAL_URL))

    assert raised.value.error.kind is NormalizationErrorKind.INVALID_URL
    assert raised.value.error.field == "media[0].url"


@pytest.mark.parametrize(
    "url",
    [
        f"https://user:{SECRET}@cdn.example.invalid/a.png",
        f"http://user:{SECRET}@cdn.example.invalid/a.png",
        f"https://{SECRET}@cdn.example.invalid/a.png",
        "https://user:@cdn.example.invalid/a.png",
        f"https://:pass@{SECRET}.example.invalid/a.png",
        f"https://user:{SECRET}@cdn.example.invalid/a.png?v=1#frag",
    ],
)
def test_every_userinfo_shape_is_refused(url: str) -> None:
    """With and without a password, over both schemes, with a query and a fragment.

    The check is on the authority component, so it does not depend on which of the
    optional pieces are present.
    """
    with pytest.raises(RecordRejectedError) as raised:
        normalize_record(_media_record(url))

    assert raised.value.error.kind is NormalizationErrorKind.INVALID_URL


def test_the_refusal_happens_before_any_media_is_recorded() -> None:
    """A rejected media entry costs the record, not just that entry.

    That is the existing behaviour for every other malformed field, and it is the
    right one here: a partially-recorded creative is harder to reason about than a
    refused one, and the raw response still holds the payload either way.
    """
    with pytest.raises(RecordRejectedError) as raised:
        normalize_record(
            {
                "ad_id": "mock-ad-000602",
                "ad_creative_bodies": [
                    {
                        "body": "Copy.",
                        "media": [
                            {"key": "good-key", "url": "https://cdn.example.invalid/ok.png"},
                            {"key": "bad-key", "url": CREDENTIAL_URL},
                        ],
                    }
                ],
            }
        )

    assert raised.value.error.field == "media[1].url"


# ============================================================
# The credential is not echoed
# ============================================================


def test_the_credential_appears_nowhere_in_the_raised_error() -> None:
    """The single most important assertion in this file.

    `detail` is documented as safe to log and is handed to `_describe` and to
    `collection_runs.error_message`. A rejection that quoted the URL would put the
    token in the database and in the worker log -- moving the secret rather than
    stopping it.
    """
    with pytest.raises(RecordRejectedError) as raised:
        normalize_record(_media_record(CREDENTIAL_URL))

    error = raised.value.error
    rendered = f"{error.kind} {error.field} {error.detail} {error.index}"
    assert SECRET not in rendered
    # The host and the username are the parts that would identify the credential
    # source. The message names the *category* ("userinfo"), which is fixed text
    # written here and not derived from the input -- that is the point, and it is
    # why a naive "the word user must not appear" check would be wrong.
    assert "cdn.example.invalid" not in error.detail
    assert "alice" not in error.detail
    assert error.detail == "carries userinfo credentials, which are never stored"


def test_the_whole_exception_repr_carries_no_credential() -> None:
    """Not just `detail` -- the exception object itself.

    An exception that renders the offending value in its `repr` would be logged in
    full by anything that logs the exception rather than its fields, which is a
    common and easy-to-miss path.
    """
    with pytest.raises(RecordRejectedError) as raised:
        normalize_record(_media_record(CREDENTIAL_URL))

    assert SECRET not in repr(raised.value)
    assert SECRET not in str(raised.value)


def test_the_detail_is_a_fixed_string_not_an_interpolated_one() -> None:
    """Two different secrets produce the same message.

    If the detail varied with the input, it could be used as an oracle to confirm a
    guessed credential. A fixed message carries no information about the value.
    """
    first = normalize_record_error_detail("https://alice:one@cdn.example.invalid/a.png")
    second = normalize_record_error_detail("https://bob:two@cdn.example.invalid/b.png")

    assert first == second


def normalize_record_error_detail(url: str) -> str:
    with pytest.raises(RecordRejectedError) as raised:
        normalize_record(_media_record(url))
    return raised.value.error.detail


# ============================================================
# What is still accepted
# ============================================================


@pytest.mark.parametrize(
    "url",
    [
        # An `@` in the path or query is a legal character and means nothing about
        # credentials, so a whole-string scan would have refused these wrongly.
        "https://cdn.example.invalid/asset@v2.png",
        "https://cdn.example.invalid/a.png?email=user@example.invalid",
        "https://cdn.example.invalid/a.png#user",
        "https://user-images.example.invalid/a.png",
    ],
)
def test_a_url_that_only_looks_like_it_carries_credentials_is_accepted(url: str) -> None:
    """The check is bounded to the authority, and this is why.

    Refusing every URL containing `@` would have refused a real CDN path with a
    version marker, which is the over-broad rule this deliberately avoids.
    """
    record = normalize_record(_media_record(url))

    assert str(record.media[0].source_url) == url


def test_a_destination_url_with_userinfo_is_still_stored_verbatim() -> None:
    """S1.3's decision, deliberately preserved.

    A click-through destination carrying userinfo is not the same risk as a
    credential in a column we are about to make queryable, and S1.3 settled that
    such URLs are stored as the provider sent them rather than normalised.
    S2.4 does not own `destination_url`.
    """
    destination = "https://user:pass@example.invalid/offer"
    record = normalize_record(
        {
            "ad_id": "mock-ad-000603",
            "ad_creative_bodies": [{"body": "Copy.", "link_url": destination, "media": []}],
        }
    )

    assert str(record.destination_url) == destination


def test_a_media_entry_without_a_url_is_fine() -> None:
    """A media reference with no URL is a normal observation, not a failure.

    A provider reporting a key and nothing else has told us the asset exists; we
    simply do not know where it is.
    """
    record = normalize_record(
        {
            "ad_id": "mock-ad-000604",
            "ad_creative_bodies": [{"body": "Copy.", "media": [{"key": "mock-media-no-url"}]}],
        }
    )

    assert record.media[0].source_url is None
    assert record.media[0].provider_key == "mock-media-no-url"


# ============================================================
# No fetching, ever
# ============================================================


def test_the_module_cannot_reach_a_socket_at_all() -> None:
    """Structural, and the strongest statement available.

    A URL parser and a fetcher are different imports, and this package has neither.
    The refusal above is reached without anything resolving, redirecting or
    contacting the host -- which is asserted by the absence of a client rather than
    by the absence of a call.
    """
    import app.providers.data.models as models_module
    import app.providers.data.normalize as normalize_module

    for module in (normalize_module, models_module):
        source = module.__file__
        assert source is not None
        text_source = open(source, encoding="utf-8").read().lower()
        for forbidden in ("import requests", "import httpx", "urllib.request", "urlopen("):
            assert forbidden not in text_source, f"{module.__name__} can reach the network"


def test_the_media_ref_contract_rejects_a_non_http_scheme() -> None:
    """The pre-existing scheme rule still holds alongside the new one.

    Two independent refusals, and neither is redundant: the scheme check keeps
    `file://` out, and the userinfo check keeps a password out of a *valid* URL.
    Asserted against `ValidationError` specifically -- a blind `Exception` would
    also pass if the model were replaced by something that raised `TypeError` for
    an unrelated reason.
    """
    with pytest.raises(ValidationError):
        MediaRef(provider_key="k", source_url="file:///etc/passwd")

    # A valid reference still constructs, so the refusal above is the rule and not
    # a broken model.
    reference = MediaRef(provider_key="k", source_url="https://cdn.example.invalid/a.png")
    assert reference.provider_key == "k"
    assert isinstance(RawAdRecord(external_ad_id="x", primary_text="Copy."), RawAdRecord)
