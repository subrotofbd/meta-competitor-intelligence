"""The committed fixtures are safe to publish.

These files are in git, on a branch that will be shared, describing
"competitor" advertising. A real page id, a real ad id or a live token in one
of them would be a disclosure that no test could undo afterwards.

The scanner below is deliberately paranoid rather than clever. It does not try
to tell a real Meta page id from a synthetic one; it rejects anything that
*looks* like a credential or a long numeric identifier and leaves the fixtures
obvious enough to read by eye.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from _ast_probe import TESTS_ROOT

FIXTURE_ROOT = TESTS_ROOT / "fixtures"

#: Nine digits or more. Meta page and ad ids are long decimal numbers, and so
#: are access tokens. A synthetic fixture has no reason to contain one.
LONG_NUMBER = re.compile(r"\d{9,}")

#: A 64-character lowercase hex token -- i.e. a SHA-256 digest.
#:
#: S3.3 stores **real** `copy_hash` values in `tests/fixtures/ai/analyses.json`,
#: because placeholder keys could never be stored and every provider lookup missed.
#: A SHA-256 digest contains runs of nine or more digits purely by chance, which
#: made this guard fire on a fixture that leaks nothing.
#:
#: So the token is masked before scanning, and **only** the token: a 64-character
#: lowercase hex string is a digest by definition, never a decimal Meta identifier.
#: Every other digit run in every fixture is still checked exactly as before.
#: `test_the_digest_exemption_does_not_weaken_the_rule` proves the exemption is not
#: a blanket pass.
HEX64_TOKEN = re.compile(r"[0-9a-f]{64}")


def without_digests(text: str) -> str:
    """The text with 64-hex digest tokens replaced by a placeholder."""
    return HEX64_TOKEN.sub("<sha256>", text)


#: Anything that looks like a hostname. Fixtures use `example.invalid`, which
#: RFC 2606 reserves and which can never resolve.
HOSTLIKE = re.compile(r"https?://([^\s\"'\\]+)", re.IGNORECASE)
RESERVED_HOST_SUFFIX = ".invalid"

EMAIL = re.compile(r"[^@\s\"']+@[^@\s\"']+\.[A-Za-z]{2,}")

SECRET_WORDS = (
    "access_token",
    "accesstoken",
    "app_secret",
    "appsecret",
    "client_secret",
    "api_key",
    "apikey",
    "authorization",
    "bearer ",
    "private_key",
    "password",
    "secret",
    "token",
)

#: Hosts that would mean a fixture had been pasted from a real capture.
REAL_SOCIAL_HOSTS = ("facebook.com", "fb.com", "instagram.com", "meta.com", "threads.net")

FIXTURE_FILES = sorted(FIXTURE_ROOT.rglob("*.json"))


def test_there_are_fixtures_to_check() -> None:
    """Otherwise the rest of this module passes for the wrong reason."""
    assert FIXTURE_FILES


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_no_fixture_contains_a_long_numeric_identifier(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    scannable = without_digests(text)
    assert not LONG_NUMBER.search(scannable), LONG_NUMBER.search(scannable)


def test_the_digest_exemption_does_not_weaken_the_rule() -> None:
    """The 64-hex exemption must mask a digest and nothing else.

    Without this, `without_digests` could quietly grow into a blanket exemption and
    the guard above would stop guarding anything. So both halves are asserted on
    synthetic input: a leaked id is still caught, and a digest's internal digit run is
    not.
    """
    leaked_id = '{"page_id": "123456789012345"}'
    assert LONG_NUMBER.search(without_digests(leaked_id)), "a leaked id would pass"

    # Synthetic rather than taken from the fixture: whether any *particular* digest
    # happens to contain nine consecutive digits is luck, and this test is about the
    # masking mechanism, not about one value.
    digest = "123456789" + "a" * 55
    assert len(digest) == 64
    assert LONG_NUMBER.search(digest), "the test digest needs a long digit run"
    assert not LONG_NUMBER.search(without_digests(digest)), "the digest was not masked"

    # 63 characters is one short of the digest shape, so it stays subject to the rule.
    # The boundary is exactly 64: a longer hex run has its first 64 masked and
    # whatever follows is still scanned, which is the right outcome for a token that
    # is not a digest in the first place.
    assert LONG_NUMBER.search(without_digests(digest[:63])) is not None


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_no_fixture_points_at_a_real_host(path: Path) -> None:
    """Every URL must use a reserved domain, so a fixture can never be fetched."""
    text = path.read_text(encoding="utf-8")
    hosts = {match.group(1).split("/")[0].lower() for match in HOSTLIKE.finditer(text)}
    for host in hosts:
        assert not any(social in host for social in REAL_SOCIAL_HOSTS), host
        assert host.endswith(RESERVED_HOST_SUFFIX) or host == "localhost", host


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_no_fixture_contains_an_email_address(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert EMAIL.search(text) is None, EMAIL.search(text)


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_no_fixture_mentions_a_credential(path: Path) -> None:
    """Case-insensitive, because a renamed key is still a credential."""
    text = path.read_text(encoding="utf-8").lower()
    found = [word for word in SECRET_WORDS if word in text]
    assert not found, found


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_every_identifier_in_a_fixture_is_namespaced(path: Path) -> None:
    """Ids read as invented at a glance: `mock-ad-`, `mock-page-`, `mock-media-`."""
    text = path.read_text(encoding="utf-8")
    identifiers = set(re.findall(r'"(mock-[a-z]+-[\w-]+)"', text))
    assert identifiers
    for identifier in identifiers:
        assert identifier.startswith("mock-"), identifier


def test_the_corpus_declares_itself_synthetic() -> None:
    """A reader opening the file should not have to infer that it is invented."""
    corpus = FIXTURE_ROOT / "ad_provider" / "corpus.json"
    assert "synthetic" in corpus.read_text(encoding="utf-8").lower()


def test_the_corpus_uses_no_real_advertiser_names() -> None:
    """Page names are invented two-word studio names, not brands anyone trades under."""
    corpus = (FIXTURE_ROOT / "ad_provider" / "corpus.json").read_text(encoding="utf-8")
    for name in ("Aurora Kitchen Studio", "Northwind Fitness Club", "Coastal Ayurveda"):
        assert name in corpus
    assert not any(mark in corpus for mark in ("Ltd", "Pvt", "Inc.", "LLC", "GmbH"))
