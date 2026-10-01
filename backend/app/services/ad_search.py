"""Searching ad copy with PostgreSQL, and nothing else.

## The problem this solves

The copy text lives in exactly one place: inside `ad_snapshots.normalized`, a JSONB
column written once by S2.1. There is **no** column holding `primary_text`, and
`AGENTS.md` section 8 makes that column append-only evidence -- so a search feature
cannot promote those strings into columns without either rewriting stored history
or duplicating it.

So search reads the JSONB in place, and an **expression index** on that read is what
makes it fast. The stored document is never touched: `normalized`, `content_hash`,
`copy_hash` and `creative_hash` are exactly as S2.1 and S2.2 left them.

## The four fields, and why only four

`primary_text`, `headline`, `description` and `cta`. These are the words a person
would type to find an ad, and they are the only approved text fields in the product.

Deliberately **not** searched:

- `raw_responses.payload` -- untrusted provider bytes, unbounded, and its searchable
  surface is already covered by `normalized`.
- `provider_metadata` and any other JSONB key -- arbitrary JSON has no contract, and
  indexing "whatever is there" is how a search index becomes a place secrets leak.
- AI `error_type`/`error_message` -- internal diagnostics, not ad content.
- Prompts and raw model responses -- never persisted in the first place.

## `simple`, and why it is not `english`

`'simple'` does no stemming and no stop-word removal. That is the right choice for
this corpus: the mock data is Hindi and Hinglish, and an English stemmer mangles
Devanagari while also discarding short tokens a Hindi phrase depends on. `simple`
also means the index expression is stable -- adding a dictionary later would
silently invalidate every existing tsvector.

## Two strategies, because they answer different questions

**Full text** (`to_tsvector` + `plainto_tsquery`) for word and phrase matching:
"kettle" finds "kettle". It is stemmed-free, so "kettles" will *not* match
"kettle" -- that is what the trigram path is for.

**Trigram** (`gin_trgm_ops`) for partial and fuzzy matching: "kett" finds "kettle",
"kettle" finds "kettles". `pg_trgm` has been installed since migration `0001` and
had never been used until this checkpoint.

## User input is never interpreted as a query

`plainto_tsquery` treats its argument as **plain text**: `&`, `!`, `|`, `:*` and
parentheses are words, not operators. A user cannot type a tsquery, so there is no
tsquery injection to defend against.

The trigram path does take pattern syntax, so `%` and `_` -- which are SQL `LIKE`
wildcards -- are escaped. Without that, a user typing `%` gets a full scan
laundered through an index.

## The projection is written three times on purpose

`database/migrations/versions/0011_api_search_indexes.py` spells the expression out
again rather than importing it, because a migration should record what the rule
*is* rather than depend on a service module. `models/ads.py` declares it a third time,
because `models` must not import from `services`.

Three copies is a real risk, so `test_every_copy_of_the_search_projection_agrees`
compares the SQL all three produce and fails if they drift, and
`test_the_search_query_matches_the_index_expression_exactly` pins every literal in
the query. An index whose expression differs from the query's is silently unused --
the worst possible failure mode for a search feature.
"""

from __future__ import annotations

from typing import Any, Final

from sqlalchemy import func, literal_column
from sqlalchemy.sql.elements import ColumnElement

#: The text configuration. A literal column rather than a bind parameter, because a
#: bind parameter makes the expression non-immutable and an index on it is unusable.
TEXT_CONFIG: Final = "simple"

#: The configuration as an expression rather than a string.
#:
#: Passing `TEXT_CONFIG` as a plain string makes SQLAlchemy bind it, producing
#: `to_tsvector(%(to_tsvector_1)s, ...)` where the index holds `'simple'::regconfig`.
#: Under a generic plan that is a `Param` rather than the constant, so the index stops
#: matching. Inlined as a literal column instead.
_TEXT_CONFIG_EXPR: Final[ColumnElement[Any]] = literal_column(f"'{TEXT_CONFIG}'")

#: The copy fields searched, in the order they are concatenated. Order is irrelevant
#: to matching but it fixes the expression text, and a stable text is what lets the
#: index and the query agree.
COPY_FIELDS: Final[tuple[str, ...]] = ("primary_text", "headline", "description", "cta")

#: The longest search term accepted. Bounded because a trigram scan over a very long
#: pattern is a full table walk wearing an index as a disguise.
MAX_QUERY_CHARS: Final = 200


#: The `coalesce` default, as an expression, for the same reason as the separator:
#: a bound `''` is a parameter, not the constant the index expression stores.
_EMPTY: Final[ColumnElement[str]] = literal_column("''")


def _field(name: str) -> ColumnElement[str]:
    """One copy field out of the JSONB document, `''` when absent.

    `coalesce` matters: a NULL from `->>` would make `||` NULL and collapse the whole
    projection to NULL for any ad with an empty description, which is most of them.

    **`literal_column`, not `normalized[name].astext`, and the reason is index usage.**
    The ordinary accessor renders the JSON key as a *bind parameter*:

        coalesce(CAST(normalized ->> %(normalized_1)s AS VARCHAR), '')

    An expression index is only used when the query's expression matches the index's.
    Verified against the live schema, both forms behave differently:

    - **custom plan** (first few executions): PostgreSQL substitutes the parameter and
      the index matches. Search looks fine.
    - **generic plan** (`plan_cache_mode`, which PostgreSQL switches to after five
      executions of a prepared statement -- the normal steady state for a hot search):
      the key is a `Param`, not the constant `'primary_text'`, the expressions do not
      match, and the query falls back to a sequential scan.

    So the failure is not "search is broken" but "search quietly stopped using its
    index once it got warm" -- correct results, no error, no signal. `literal_column`
    inlines the key so both plans match:

        coalesce(normalized ->> 'primary_text', '')

    which is byte-for-byte the expression migration `0011` creates.

    The field names are Python literals from `COPY_FIELDS`, never user input, so
    inlining them injects nothing.
    """
    return func.coalesce(literal_column(f"normalized ->> '{name}'"), _EMPTY)


#: The separator between fields, as an expression.
#:
#: Inlined for the same reason as the keys above: under a generic plan a bound
#: separator is a `Param`, not the constant `' '` the index stores, and the
#: expressions stop matching.
_SEPARATOR: Final[ColumnElement[str]] = literal_column("' '")


def copy_projection() -> ColumnElement[str]:
    """The four copy fields as one text, in the fixed order above."""
    parts = [_field(name) for name in COPY_FIELDS]
    combined = parts[0]
    for part in parts[1:]:
        combined = combined.concat(_SEPARATOR).concat(part)
    return combined


def copy_tsvector() -> ColumnElement[str]:
    """The projection as a `tsvector`. Used by both the query and the index."""
    return func.to_tsvector(_TEXT_CONFIG_EXPR, copy_projection())


def plainto_tsquery(term: str) -> ColumnElement[str]:
    """A `tsquery` built from user text, which cannot contain operators."""
    return func.plainto_tsquery(_TEXT_CONFIG_EXPR, term)


def trigram_pattern(term: str) -> str:
    """A LIKE pattern that matches `term` as a substring, literally.

    `%` and `_` are escaped so a user typing them searches for those characters
    instead of every row. Without this a single `%` turns an index-assisted lookup
    into a sequential scan, and the request still returns successfully -- which is
    the worst combination.
    """
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def trigram_match(term: str) -> ColumnElement[bool]:
    """Whether the projection contains `term` as a substring."""
    return copy_projection().like(trigram_pattern(term), escape="\\")


def normalise_query(raw: str | None) -> str | None:
    """Trim a user search term, or return `None` when there is nothing to search.

    An empty or whitespace-only `q` is *no filter*, not a filter that matches
    nothing. Treating it as the latter would make `?q=` return zero ads, which reads
    as "this search engine found nothing" rather than "you did not ask a question".
    """
    if raw is None:
        return None
    trimmed = raw.strip()
    if not trimmed:
        return None
    return trimmed[:MAX_QUERY_CHARS]
