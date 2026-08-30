"""Natural-paragraph facts derived from canonical text."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .offsets import content_offsets


@dataclass(frozen=True)
class Paragraph:
    index: int
    canonical_start: int
    canonical_end: int
    content_start: int
    content_end: int


def split_paragraphs(text: str, *, offsets: list[int] | None = None) -> list[Paragraph]:
    """Return non-empty physical paragraphs, keeping canonical coordinates."""
    mapping = offsets if offsets is not None else content_offsets(text)
    paragraphs: list[Paragraph] = []
    cursor = 0
    for line in text.splitlines(keepends=True):
        line_end = cursor + len(line)
        stripped_start = cursor
        while stripped_start < line_end and text[stripped_start].isspace():
            stripped_start += 1
        stripped_end = line_end
        while stripped_end > stripped_start and text[stripped_end - 1].isspace():
            stripped_end -= 1
        if stripped_start < stripped_end:
            paragraphs.append(Paragraph(
                len(paragraphs) + 1,
                stripped_start,
                stripped_end,
                mapping[stripped_start],
                mapping[stripped_end],
            ))
        cursor = line_end
    if cursor < len(text):  # defensive; splitlines normally consumes it
        raise AssertionError("paragraph scan did not consume canonical text")
    return paragraphs


def paragraph_dicts(paragraphs: list[Paragraph]) -> list[dict[str, int]]:
    return [asdict(paragraph) for paragraph in paragraphs]


def paragraph_bodies(text: str, *, offsets: list[int] | None = None) -> dict[int, str]:
    """Map 1-based paragraph index → exact canonical substring (no labels)."""
    return {
        paragraph.index: text[paragraph.canonical_start:paragraph.canonical_end]
        for paragraph in split_paragraphs(text, offsets=offsets)
    }


def format_paragraph_view(text: str, *, offsets: list[int] | None = None) -> str:
    """Display-only numbered view. Labels are not part of canonical text.

    Each block is:
        P001
        <exact paragraph body>
    Copying a P-label into a quote field is forbidden; Python binds by integer id.
    """
    blocks: list[str] = []
    for paragraph in split_paragraphs(text, offsets=offsets):
        body = text[paragraph.canonical_start:paragraph.canonical_end]
        blocks.append(f"P{paragraph.index:03d}")
        blocks.append(body)
    return "\n".join(blocks)
