"""Media storage: the `MediaStore` seam and a local-filesystem implementation.

S0.3 stores no media. This module exists because the seam has to be right
before anything writes to it: byte downloads are a later checkpoint, and the
decision of *where* bytes land should not be revisited then.

## Content addressing

A key is the SHA-256 of the bytes it names, and nothing else. Two uploads of
the same file are one stored object, and a key is stable across storage
backends -- which is what lets a `creative_hash` be compared across a
migration from local disk to object storage.

`LocalFsStore` is the development store. S3 arrives in a later checkpoint and
implements the same protocol; nothing above this file changes when it does.

## The path rule

A key is validated as 64 lowercase hex characters *before* it is used to build
a path, so `..`, absolute paths, drive letters and URL schemes cannot reach the
filesystem. This is the single check, and it lives in `content_key` -- the only
place a caller-supplied string turns into a path. There is no second
resolve-and-compare pass, because there is no way for an unvalidated key to
reach one.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

#: Exactly what a SHA-256 hex digest looks like, and nothing more.
_CONTENT_KEY = re.compile(r"[0-9a-f]{64}")


def content_key(digest: str) -> str:
    """Return `digest` as a storage key, or refuse.

    Args:
        digest: A 64-character lowercase hex SHA-256 digest.

    Returns:
        The same string, validated.

    Raises:
        ValueError: The string is not a content digest. Traversal attempts,
            paths and URL-shaped values are rejected here and nowhere else.
    """
    if _CONTENT_KEY.fullmatch(digest) is None:
        raise ValueError(
            "storage key must be a 64-character lowercase hex SHA-256 digest; "
            f"got {digest[:16]!r}..."
        )
    return digest


def content_key_for(data: bytes) -> str:
    """The content key for `data`."""
    return content_key(hashlib.sha256(data).hexdigest())


class StoredAsset(BaseModel):
    """What a store reports after accepting bytes.

    Attributes:
        key: The content key the bytes are stored under.
        size_bytes: Bytes written.
        content_type: Reported content type, when the caller knew it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=0)
    content_type: str | None = None


@runtime_checkable
class MediaStore(Protocol):
    """Content-addressed storage for creative assets.

    Bytes go in and come out. Nothing here fetches: a store is handed data by
    the caller that obtained it, so no store can become a way for the product
    to reach a remote host on its own.
    """

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> StoredAsset:
        """Store `data` under `key`.

        Idempotent: storing the same bytes under the same key writes identical
        content and reports an identical result.

        Args:
            key: A content key from `content_key` or `content_key_for`.
            data: The bytes to store.
            content_type: Recorded with the asset when known.

        Raises:
            ValueError: `key` is not a content key, or it is not the key those
                bytes hash to. The second check is what makes the key mean
                something: without it a caller could file different bytes under
                an existing key and every later comparison would be a
                comparison of lies.
        """
        ...

    def get(self, key: str) -> bytes:
        """Return the bytes stored under `key`.

        Raises:
            ValueError: `key` is not a content key.
            FileNotFoundError: Nothing is stored under `key`.
        """
        ...

    def exists(self, key: str) -> bool:
        """Whether anything is stored under `key`.

        Raises:
            ValueError: `key` is not a content key.
        """
        ...


class LocalFsStore:
    """A `MediaStore` on the local filesystem, for development.

    Assets fan out over two levels of two hex characters. One flat directory
    would eventually hold more files than a filesystem handles comfortably,
    and the cost of the fix afterwards is a migration of every stored path.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> StoredAsset:
        validated = content_key(key)
        if content_key_for(data) != validated:
            raise ValueError(
                f"content key {validated} is not the key these bytes hash to; "
                "a key is derived from content, so this means the caller hashed "
                "something other than what it is storing"
            )
        path = self._path_for(validated)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredAsset(key=validated, size_bytes=len(data), content_type=content_type)

    def get(self, key: str) -> bytes:
        path = self._path_for(key)
        if not path.is_file():
            raise FileNotFoundError(f"no asset stored under key {key!r}")
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path_for(key).is_file()

    def _path_for(self, key: str) -> Path:
        """Turn a content key into a path, validating on the way.

        The key is checked here rather than at each call site, so there is
        exactly one place where a caller-supplied string becomes a path and
        exactly one place that can reject one.
        """
        validated = content_key(key)
        return self._root / validated[:2] / validated[2:4] / validated
