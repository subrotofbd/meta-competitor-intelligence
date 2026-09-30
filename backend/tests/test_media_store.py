"""`MediaStore` and the local-filesystem store.

The store writes bytes and never fetches them. That is a structural property
with a real reason: a store that could take a URL would be a way for the
product to reach a remote host without a provider saying so.

The path tests matter more than the storage tests. A content key is the only
thing allowed to become a path, and the checks below confirm that a traversal
attempt, an absolute path and a URL-shaped key are all refused at the boundary
rather than somewhere downstream.
"""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

import pytest

from app.services.media import (
    LocalFsStore,
    MediaStore,
    StoredAsset,
    content_key,
    content_key_for,
)

PAYLOAD = b"synthetic-creative-bytes"
OTHER_PAYLOAD = b"a different creative"


# ============================================================
# Content keys
# ============================================================


def test_a_content_key_is_the_sha256_of_the_bytes() -> None:
    key = content_key_for(PAYLOAD)
    assert key == hashlib.sha256(PAYLOAD).hexdigest()
    assert content_key(key) == key


def test_identical_bytes_produce_one_key() -> None:
    """Content addressing is what makes a `creative_hash` comparable later."""
    assert content_key_for(PAYLOAD) == content_key_for(bytes(bytearray(PAYLOAD)))


def test_different_bytes_produce_different_keys() -> None:
    assert content_key_for(PAYLOAD) != content_key_for(OTHER_PAYLOAD)


@pytest.mark.parametrize(
    "hostile",
    [
        "../../etc/passwd",
        "..\\..\\windows\\system32",
        "/absolute/path",
        "C:\\windows",
        "https://cdn.example.invalid/asset.png",
        "not-a-digest",
        "",
        "A" * 64,
        "g" * 64,
        "0" * 63,
        "0" * 65,
    ],
)
def test_only_a_lowercase_hex_digest_is_a_key(hostile: str) -> None:
    """Uppercase hex is refused too, so one payload has exactly one key."""
    with pytest.raises(ValueError):
        content_key(hostile)


# ============================================================
# The protocol
# ============================================================


def test_the_local_store_satisfies_the_protocol(tmp_path: Path) -> None:
    assert isinstance(LocalFsStore(tmp_path), MediaStore)


def test_a_class_without_get_does_not_satisfy_the_protocol() -> None:
    class HalfStore:
        def put(self, key: str, data: bytes, *, content_type: str | None = None) -> StoredAsset:
            raise NotImplementedError

        def exists(self, key: str) -> bool:
            raise NotImplementedError

    assert not isinstance(HalfStore(), MediaStore)


def test_the_protocol_has_no_method_that_could_fetch() -> None:
    """No URL parameter anywhere: a store cannot become a fetcher."""
    parameters = {
        name
        for name, method in inspect.getmembers(MediaStore, inspect.isfunction)
        for parameter in inspect.signature(method).parameters
    }
    assert not {"url", "source_url", "href", "uri"} & parameters


# ============================================================
# Storing
# ============================================================


def test_bytes_round_trip(tmp_path: Path) -> None:
    store = LocalFsStore(tmp_path)
    key = content_key_for(PAYLOAD)
    stored = store.put(key, PAYLOAD, content_type="image/png")
    assert stored.key == key
    assert stored.size_bytes == len(PAYLOAD)
    assert stored.content_type == "image/png"
    assert store.get(key) == PAYLOAD
    assert store.exists(key)


def test_storing_the_same_bytes_twice_is_stable(tmp_path: Path) -> None:
    store = LocalFsStore(tmp_path)
    key = content_key_for(PAYLOAD)
    assert store.put(key, PAYLOAD) == store.put(key, PAYLOAD)
    assert store.get(key) == PAYLOAD


def test_bytes_filed_under_the_wrong_key_are_refused(tmp_path: Path) -> None:
    """Content addressing has to be enforced, not merely intended.

    Otherwise a caller can overwrite an existing key with different bytes, and
    every later `creative_hash` comparison quietly becomes a comparison of
    whatever was written last.
    """
    store = LocalFsStore(tmp_path)
    key = content_key_for(PAYLOAD)
    store.put(key, PAYLOAD)
    with pytest.raises(ValueError):
        store.put(key, OTHER_PAYLOAD)
    assert store.get(key) == PAYLOAD


def test_reading_a_missing_asset_says_so(tmp_path: Path) -> None:
    store = LocalFsStore(tmp_path)
    assert store.exists(content_key_for(PAYLOAD)) is False
    with pytest.raises(FileNotFoundError):
        store.get(content_key_for(PAYLOAD))


def test_assets_fan_out_over_two_directory_levels(tmp_path: Path) -> None:
    """One flat directory would eventually hold more files than a filesystem likes."""
    store = LocalFsStore(tmp_path)
    key = content_key_for(PAYLOAD)
    store.put(key, PAYLOAD)
    written = next(path for path in tmp_path.rglob("*") if path.is_file())
    assert written.parent.name == key[2:4]
    assert written.parent.parent.name == key[:2]
    assert written.name == key


# ============================================================
# The path rule
# ============================================================


@pytest.mark.parametrize(
    "hostile", ["../../escape", "/etc/passwd", "https://cdn.example.invalid/a.png"]
)
def test_a_hostile_key_never_becomes_a_path(tmp_path: Path, hostile: str) -> None:
    store = LocalFsStore(tmp_path)
    for call in (
        lambda: store.put(hostile, PAYLOAD),
        lambda: store.get(hostile),
        lambda: store.exists(hostile),
    ):
        with pytest.raises(ValueError):
            call()
    assert list(tmp_path.rglob("*")) == []


def test_a_key_is_validated_even_when_the_root_is_a_relative_path(tmp_path: Path) -> None:
    """The root is trusted; the key is not, and is checked on every call."""
    store = LocalFsStore(Path("relative-root"))
    with pytest.raises(ValueError):
        store.exists("../outside")
