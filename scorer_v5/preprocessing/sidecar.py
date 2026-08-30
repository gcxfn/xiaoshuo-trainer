"""Versioned, hashable sidecar for deterministic text facts."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json

from .canonicalize import CANONICALIZATION_VERSION, canonicalize, non_whitespace_length, text_sha256
from .offsets import content_offsets
from .paragraphs import Paragraph, split_paragraphs
from .windows import percentage_boundaries

SIDECAR_VERSION = "v5.1-sidecar-1"


@dataclass(frozen=True)
class TextSidecar:
    version: str
    canonicalization_version: str
    text_sha256: str
    L: int
    K: float
    paragraph_count: int
    paragraphs: tuple[Paragraph, ...]
    first_10pct_end: int
    first_15pct_end: int
    first_third_end: int
    last_15pct_start: int

    def to_dict(self) -> dict[str, object]:
        """JSON-ready sidecar. Coordinates are non-whitespace codepoint offsets."""
        return {
            "version": self.version,
            "canonicalization_version": self.canonicalization_version,
            "text_sha256": self.text_sha256,
            "L": self.L,
            "K": self.K,
            "paragraph_count": self.paragraph_count,
            "paragraph_offsets": [asdict(paragraph) for paragraph in self.paragraphs],
            "first_10pct_end": self.first_10pct_end,
            "first_15pct_end": self.first_15pct_end,
            "first_third_end": self.first_third_end,
            "last_15pct_start": self.last_15pct_start,
        }

    def sha256(self) -> str:
        payload = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode("utf-8")).hexdigest()


def build_sidecar(text: str) -> tuple[str, TextSidecar, list[int]]:
    """Canonicalize once and calculate every shared fact once.

    ``offsets`` is intentionally returned only to Python callers. It is never
    serialized into or exposed through an LLM prompt.
    """
    canonical_text = canonicalize(text)
    offsets = content_offsets(canonical_text)
    length = non_whitespace_length(canonical_text)
    if not length:
        raise ValueError("canonical text has no non-whitespace codepoints")
    bounds = percentage_boundaries(length)
    paragraphs = tuple(split_paragraphs(canonical_text, offsets=offsets))
    return canonical_text, TextSidecar(
        version=SIDECAR_VERSION,
        canonicalization_version=CANONICALIZATION_VERSION,
        text_sha256=text_sha256(canonical_text),
        L=length,
        K=length / 1000,
        paragraph_count=len(paragraphs),
        paragraphs=paragraphs,
        **bounds,
    ), offsets
