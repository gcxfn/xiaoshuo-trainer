"""Exact quote location and non-whitespace offset utilities."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .canonicalize import canonicalize


@dataclass(frozen=True)
class QuoteLocation:
    """A quote's canonical and non-whitespace coordinate ranges."""

    canonical_start: int
    canonical_end: int
    content_start: int
    content_end: int


def content_offsets(text: str) -> list[int]:
    """Map each canonical index to its preceding non-whitespace count.

    The terminal entry makes ranges half-open and prevents a whitespace-heavy
    source from corrupting ratio calculations defined over non-whitespace L.
    """
    offsets = [0]
    count = 0
    for char in text:
        if not char.isspace():
            count += 1
        offsets.append(count)
    return offsets


def all_quote_starts(text: str, quote: str) -> list[int]:
    quote = canonicalize(quote)
    if not quote:
        return []
    starts: list[int] = []
    start = 0
    while True:
        found = text.find(quote, start)
        if found < 0:
            return starts
        starts.append(found)
        start = found + 1


def locate_quote(
    text: str,
    quote: str,
    *,
    nearby_anchor: str | None = None,
    offsets: list[int] | None = None,
) -> QuoteLocation | None:
    """Resolve an exact quote, rejecting ambiguity unless an anchor resolves it."""
    starts = all_quote_starts(text, quote)
    if not starts:
        return None
    if len(starts) > 1:
        if not nearby_anchor:
            raise ValueError("quote is ambiguous without nearby_anchor")
        anchor_starts = all_quote_starts(text, nearby_anchor)
        if not anchor_starts:
            raise ValueError("nearby_anchor is absent from canonical text")
        anchor_length = len(canonicalize(nearby_anchor))
        # Span-aware distance: from quote start to the nearest point of any
        # anchor occurrence. A tie between equally distant occurrences is a
        # genuine ambiguity and must be rejected, never guessed.
        distances = [
            min(
                min(abs(start - anchor), abs(start - (anchor + anchor_length)))
                for anchor in anchor_starts
            )
            for start in starts
        ]
        best = min(distances)
        starts = [start for start, distance in zip(starts, distances) if distance == best]
        if len(starts) != 1:
            raise ValueError("quote remains ambiguous after nearby_anchor")
    start = starts[0]
    end = start + len(canonicalize(quote))
    mapping = offsets if offsets is not None else content_offsets(text)
    return QuoteLocation(start, end, mapping[start], mapping[end])


def locate_many(text: str, quotes: Iterable[str], *, offsets: list[int] | None = None) -> list[QuoteLocation | None]:
    return [locate_quote(text, quote, offsets=offsets) for quote in quotes]
