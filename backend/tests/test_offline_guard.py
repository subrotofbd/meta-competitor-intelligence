"""The offline guarantee, enforced rather than asserted.

`no_network` replaces the socket constructors with functions that raise. Every
mock surface then runs underneath it, so "the MockProvider made no network
call" is a fact the suite established, not a claim about what the provider
probably does.

The guard is deliberately blunt. It does not know which libraries might reach
for a socket, and it does not care: the whole point is that nothing in S0.3
should be able to, and anything that tries says so immediately.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from app.providers.ai.base import AIProvider
from app.providers.ai.models import CopyAnalysisRequest
from app.providers.data.base import AdDataProvider
from app.providers.data.models import PageRef
from app.services.media import LocalFsStore, content_key_for


def test_the_guard_actually_blocks_sockets(no_network: None) -> None:
    """A guard that does not block anything is worse than no guard at all."""
    with pytest.raises(AssertionError, match="must not touch the network"):
        socket.socket()
    with pytest.raises(AssertionError, match="must not touch the network"):
        socket.create_connection(("example.invalid", 443))
    with pytest.raises(AssertionError, match="must not touch the network"):
        socket.getaddrinfo("example.invalid", 443)


def test_the_ad_provider_works_with_sockets_blocked(
    ad_provider: AdDataProvider, no_network: None
) -> None:
    page = PageRef(provider_page_id="mock-page-0001", page_name="Aurora Kitchen Studio")
    result = ad_provider.fetch_page_ads(page, "IN")
    assert result.records
    assert ad_provider.canary().ok is True
    assert ad_provider.capabilities().serves_commercial_ads is True


def test_a_full_cursor_walk_works_with_sockets_blocked(
    ad_provider: AdDataProvider, no_network: None
) -> None:
    page = PageRef(provider_page_id="mock-page-0001", page_name="Aurora Kitchen Studio")
    cursor: str | None = None
    seen = 0
    while True:
        result = ad_provider.fetch_page_ads(page, "IN", cursor=cursor)
        seen += len(result.records)
        cursor = result.next_cursor
        if cursor is None:
            break
    assert seen == 4


def test_the_ai_provider_works_with_sockets_blocked(
    ai_provider: AIProvider, no_network: None
) -> None:
    analysis = ai_provider.analyze_copy(
        CopyAnalysisRequest(copy_hash="mock-copy-hash-en-001", analysis_version="mock-v1")
    )
    assert analysis.language == "en"


def test_the_media_store_works_with_sockets_blocked(tmp_path: Path, no_network: None) -> None:
    store = LocalFsStore(tmp_path)
    payload = b"synthetic-creative-bytes"
    store.put(content_key_for(payload), payload)
    assert store.get(content_key_for(payload)) == payload


def test_the_mocks_import_no_network_library() -> None:
    """The guard proves a call did not happen. This proves there is no code to call."""
    from _ast_probe import APP_ROOT, NETWORK_MODULES, imported_modules, top_level

    for relative in (
        "providers/data/mock.py",
        "providers/ai/mock.py",
        "services/media.py",
        "composition.py",
    ):
        assert not top_level(imported_modules(APP_ROOT / relative)) & NETWORK_MODULES, relative
