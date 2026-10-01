"""The shared base for every response model.

## One definition, not two

`schemas/ads.py` grew its own `_Response` when S3.2 had no other response file. This
module exists so the S3.3 competitor schemas adopt the **same** rule instead of
copying it -- a duplicated base class is one that eventually drifts, and the two
files would then disagree about whether an unexpected field is an error.

`_Response` is private in `ads.py` precisely because nothing else could import it
without reaching into a private name. It is public here.

## The rule itself

`frozen` and `extra="forbid"`.

**`extra="forbid"`** is the point. Every response is built by explicit field
selection in the router, so a field that appears in a payload but not in the schema
is a bug -- an internal identifier leaking, or a column added to a table and
published by accident. Rejecting it turns that class of mistake into a test failure
instead of a disclosure.

**`frozen`** because these are transport shapes. Nothing downstream should be
mutating a response after validation, and immutability makes that a type error
rather than a subtle bug somewhere in a component tree.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Response(BaseModel):
    """Frozen and closed: an unexpected field in a response is a bug, not a feature."""

    model_config = ConfigDict(frozen=True, extra="forbid")
