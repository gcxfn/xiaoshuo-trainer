"""Deterministic canonical text and sidecar construction."""

from .canonicalize import CANONICALIZATION_VERSION, canonicalize, non_whitespace_length, text_sha256
from .offsets import QuoteLocation, locate_many, locate_quote
from .paragraphs import Paragraph, split_paragraphs
from .sidecar import SIDECAR_VERSION, TextSidecar, build_sidecar
from .windows import canonical_index_for_content_offset, content_window, percentage_boundaries

__all__ = [
    "CANONICALIZATION_VERSION",
    "SIDECAR_VERSION",
    "Paragraph",
    "QuoteLocation",
    "TextSidecar",
    "build_sidecar",
    "canonical_index_for_content_offset",
    "canonicalize",
    "content_window",
    "locate_many",
    "locate_quote",
    "non_whitespace_length",
    "percentage_boundaries",
    "split_paragraphs",
    "text_sha256",
]
