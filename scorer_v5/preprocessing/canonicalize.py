"""Canonical text representation shared by every v5 model call."""
from __future__ import annotations

import hashlib
import unicodedata

CANONICALIZATION_VERSION = "v5.1-canonical-1"


def canonicalize(text: str) -> str:
    """Return the only text representation accepted by v5 scoring.

    Unicode is NFC-normalized, a leading UTF-8 BOM is removed, and every line
    ending is normalized to ``\n``. All other whitespace is preserved: quote
    evidence must remain directly locatable in the model-visible text.
    """
    if not isinstance(text, str):
        raise TypeError("text must be str")
    if text.startswith("\ufeff"):
        text = text[1:]
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def text_sha256(canonical_text: str) -> str:
    return hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()


def non_whitespace_length(canonical_text: str) -> int:
    return sum(not char.isspace() for char in canonical_text)
