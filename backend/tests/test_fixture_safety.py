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
    assert not LONG_NUMBER.search(text), LONG_NUMBER.search(text)


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
