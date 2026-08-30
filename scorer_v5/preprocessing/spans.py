"""Deterministic evidence-span facts derived from canonical text.

A paragraph is a physical line. An *evidence span* is a finer-grained unit:
sentences / quoted utterances / clause segments inside one paragraph. The
model emits integer ``span_id`` values; Python binds them back to the exact
canonical substring so position-sensitive metrics (B01 q, B02 500-codepoint /
15%, N6 round ordering) use real span starts instead of whole-paragraph
starts.

Rules (deterministic, no fuzzy matching):

- Split each non-empty paragraph into spans by the canonical sentence
  terminators ``。！？…`` followed by optional closing quote/brace ``"」』”’〉》]）``.
- A bare quoted utterance that carries no terminator (e.g. ``「不行」`` at the
  end of a line) still forms its own span so two dialogue rounds in one
  paragraph receive different span IDs.
- Spans never merge across paragraphs and never overlap.
- span_id is a global 1-based integer in reading order; P012 becomes
  ``S<global>`` for wire display and the integer itself for JSON.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .offsets import content_offsets

# ASCII " and ' are excluded from the terminator's closing-quote suffix: they
# double as opening quotes, and absorbing them would split an immediately
# following turn (…。"离职？") into a lone quote char.
_SENTENCE_TERMINATOR = re.compile(r"[。！？…]+[”』」’〉》）\]]*")


@dataclass(frozen=True)
class EvidenceSpan:
    span_id: int
    paragraph_index: int
    canonical_start: int
    canonical_end: int
    content_start: int
    content_end: int
    text: str

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _split_span_ranges(paragraph: "Paragraph", text: str) -> list[tuple[int, int]]:
    """Return (canonical_start, canonical_end) sub-ranges inside *paragraph*.

    Strategy: quoted turns come FIRST. Every complete paired quote
    (``"…"`` / ``“…”`` / ``「…」`` / ``『…』`` / ``'…'`` / ``‘…’``) is its own
    span regardless of interior sentence terminators. The prose between quotes
    is then split on sentence terminators so a single dialogue exchange like
    ``"离职？"我愣住了，"我昨天还在上班啊。"`` yields three spans:
    ``["离职？"] [我愣住了，] ["我昨天还在上班啊。"]``.
    """
    ranges: list[tuple[int, int]] = []
    cursor = paragraph.canonical_start
    end = paragraph.canonical_end
    body = text[cursor:end]

    _PAIRED_QUOTE = re.compile(
        r'("[^"\n]*?"|“[^”\n]*?”|「[^」\n]*?」|『[^』\n]*?』|\'[^\'\n]*?\'|‘[^’\n]*?’)'
    )
    quotes = [(m.start(), m.end()) for m in _PAIRED_QUOTE.finditer(body)]
    if not quotes:
        # No quotes: plain sentence split.
        terminator_ends = [m.end() for m in _SENTENCE_TERMINATOR.finditer(body)]
        cut = sorted(c for c in terminator_ends if 0 < c < len(body))
        prev = 0
        for c in cut:
            if c > prev:
                ranges.append((cursor + prev, cursor + c))
                prev = c
        if prev < len(body):
            ranges.append((cursor + prev, cursor + len(body)))
        return ranges

    # Walk through the paragraph, emitting a quote span or a prose sub-range.
    pos = 0
    for qs, qe in quotes:
        if qs > pos:
            # prose segment before this quote
            prose = body[pos:qs]
            terminator_ends = [m.end() for m in _SENTENCE_TERMINATOR.finditer(prose)]
            cut = sorted(c for c in terminator_ends if 0 < c < len(prose))
            prev = 0
            for c in cut:
                if c > prev:
                    ranges.append((cursor + pos + prev, cursor + pos + c))
                    prev = c
            if prev < len(prose):
                ranges.append((cursor + pos + prev, cursor + pos + len(prose)))
        # quote span itself
        ranges.append((cursor + qs, cursor + qe))
        pos = qe
    if pos < len(body):
        # trailing prose after the last quote
        prose = body[pos:]
        terminator_ends = [m.end() for m in _SENTENCE_TERMINATOR.finditer(prose)]
        cut = sorted(c for c in terminator_ends if 0 < c < len(prose))
        prev = 0
        for c in cut:
            if c > prev:
                ranges.append((cursor + pos + prev, cursor + pos + c))
                prev = c
        if prev < len(prose):
            ranges.append((cursor + pos + prev, cursor + pos + len(prose)))
    return ranges


def build_evidence_spans(text: str, *, offsets: list[int] | None = None) -> list[EvidenceSpan]:
    """Build the deterministic span table in reading order."""
    from .paragraphs import split_paragraphs

    mapping = offsets if offsets is not None else content_offsets(text)
    spans: list[EvidenceSpan] = []
    for paragraph in split_paragraphs(text, offsets=mapping):
        for cs, ce in _split_span_ranges(paragraph, text):
            if cs >= ce:
                continue
            spans.append(
                EvidenceSpan(
                    span_id=len(spans) + 1,
                    paragraph_index=paragraph.index,
                    canonical_start=cs,
                    canonical_end=ce,
                    content_start=mapping[cs],
                    content_end=mapping[ce],
                    text=text[cs:ce],
                )
            )
    return spans


def evidence_span_index(spans: list[EvidenceSpan]) -> dict[int, EvidenceSpan]:
    return {s.span_id: s for s in spans}


def evidence_span_bodies(spans: list[EvidenceSpan]) -> dict[int, str]:
    return {s.span_id: s.text for s in spans}


def format_span_view(text: str, *, offsets: list[int] | None = None) -> str:
    """Display-only numbered view: one line per span with ``S<id>`` labels."""
    blocks: list[str] = []
    for span in build_evidence_spans(text, offsets=offsets):
        blocks.append(f"S{span.span_id:03d}")
        blocks.append(span.text)
    return "\n".join(blocks)
