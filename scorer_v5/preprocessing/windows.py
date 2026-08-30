"""Content-coordinate windows shared by metrics."""
from __future__ import annotations

from bisect import bisect_left


def percentage_boundaries(length: int) -> dict[str, int]:
    if length <= 0:
        raise ValueError("canonical text has no non-whitespace codepoints")
    return {
        "first_10pct_end": length * 10 // 100,
        "first_15pct_end": length * 15 // 100,
        "first_third_end": length // 3,
        "last_15pct_start": (length * 85 + 99) // 100,
    }


def canonical_index_for_content_offset(content_offsets: list[int], target: int) -> int:
    """Find the earliest canonical boundary at a non-whitespace offset."""
    if target < 0 or target > content_offsets[-1]:
        raise ValueError("target is outside canonical content range")
    return bisect_left(content_offsets, target)


def content_window(content_offsets: list[int], start: int, end: int) -> tuple[int, int]:
    if start < 0 or end < start or end > content_offsets[-1]:
        raise ValueError("invalid content window")
    return (
        canonical_index_for_content_offset(content_offsets, start),
        canonical_index_for_content_offset(content_offsets, end),
    )
