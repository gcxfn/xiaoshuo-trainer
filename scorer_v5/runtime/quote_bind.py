"""Bind model evidence span ids to exact canonical substrings.

The model must not emit quote strings. After JSON parse, every quote-like
field is an integer span id (S012 → 12). This module copies the corresponding
canonical span into the quote field so V2/extractors still see verbatim
evidence. Model-written strings are discarded, not trusted.

``bind_evidence_spans`` returns ``(bound_semantic, span_index)`` where
``span_index`` maps every integer span id to its ``EvidenceSpan`` so
position-sensitive extractors (B01 q, B02 500/15%, N6 round order) consume
the *exact* span start, never a whole-paragraph start.

For provenance, the unmodified wire semantic (raw integer ids) is kept
separately; callers must not overwrite it in place.
"""
from __future__ import annotations

from typing import Any

from ..preprocessing.spans import (
    EvidenceSpan,
    build_evidence_spans,
    evidence_span_index,
)

# Compatibility alias for callers that only need the bound object.
from ..preprocessing.spans import evidence_span_bodies as _span_bodies  # noqa: F401


def is_bind_field(field_name: str) -> bool:
    lowered = field_name.casefold()
    if lowered == "extreme_word_quotes":
        return False
    if "quote" in lowered:
        return True
    return lowered in {"decoding_evidence", "nearby_anchor"}


def bind_evidence_spans(semantic: Any, canonical_text: str) -> tuple[Any, dict[int, EvidenceSpan]]:
    """Replace span-id integers with exact span bodies.

    Invalid ids and leftover strings become empty strings (V2 will fail).
    ``None`` stays ``None`` (optional quotes). Nested lists are bound
    element-wise. The second return value is the span index used by
    extractors for exact positions.
    """
    spans = build_evidence_spans(canonical_text)
    index = evidence_span_index(spans)
    bodies = {s.span_id: s.text for s in spans}
    bound = _bind(semantic, None, bodies)
    return bound, index


def bind_paragraph_quotes(semantic: Any, canonical_text: str) -> Any:
    """Backwards-compatible name: bind and discard the span index."""
    bound, _index = bind_evidence_spans(semantic, canonical_text)
    return bound


def _bind(value: Any, field_name: str | None, bodies: dict[int, str]) -> Any:
    if field_name and is_bind_field(field_name):
        return _bind_ref(value, bodies)
    if isinstance(value, dict):
        return {key: _bind(nested, key, bodies) for key, nested in value.items()}
    if isinstance(value, list):
        return [_bind(item, field_name, bodies) for item in value]
    return value


def _bind_ref(value: Any, bodies: dict[int, str]) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return bodies.get(value, "")
    if isinstance(value, list):
        return [_bind_ref(item, bodies) for item in value]
    # Model-written strings / other types are never copied through.
    return ""
