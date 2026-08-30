#!/usr/bin/env python3
"""Boundary unit tests for the Step 5 deterministic fact layer.

任务 07 requires these: every downstream step (score engine, N6/B33, validator)
depends on the exact boundary semantics: 10%/15%/33%/85% cutoffs, quote
ambiguity rejection, and K=L/1000.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scorer_v5.preprocessing.canonicalize import canonicalize, non_whitespace_length
from scorer_v5.preprocessing.offsets import content_offsets, locate_quote
from scorer_v5.preprocessing.paragraphs import split_paragraphs
from scorer_v5.preprocessing.sidecar import build_sidecar
from scorer_v5.preprocessing.windows import canonical_index_for_content_offset, percentage_boundaries

FAILURES: list[str] = []


def check(cond: bool, label: str) -> None:
    if not cond:
        FAILURES.append(label)


def test_canonicalize() -> None:
    # BOM stripped, CRLF → LF, NFC normalized
    c = canonicalize("\ufeffa\r\nb\r\n")
    check(c == "a\nb\n", "canonicalize BOM/CRLF")
    check(canonicalize("e\u0301") == "\u00e9", "canonicalize NFC")
    check(non_whitespace_length("a  b\nc") == 3, "non_whitespace_length")


def test_percentage_boundaries() -> None:
    # L=1000 → 10%=100, 15%=150, 33%=333, 85% start=850
    b = percentage_boundaries(1000)
    check(b["first_10pct_end"] == 100, "10pct end=100")
    check(b["first_15pct_end"] == 150, "15pct end=150")
    check(b["first_third_end"] == 333, "third end=333")
    check(b["last_15pct_start"] == 850, "85pct start=850")
    # L=999 → 85% start must be ceil so the window is never under 15%
    b999 = percentage_boundaries(999)
    check(b999["last_15pct_start"] == 850, "85pct ceil=850 for 999")


def test_content_offsets() -> None:
    text = "ab c\nd"
    off = content_offsets(text)
    # indices: a0 b1 ' ' c2 \n d3; terminal = 4
    check(off[0] == 0, "offset start 0")
    check(off[3] == 2, "offset before c = 2")
    check(off[-1] == 4, "offset terminal = L")


def test_locate_quote() -> None:
    text = "甲说：你好。乙说：你好。\n"
    # ambiguous quote without anchor → ValueError
    try:
        locate_quote(text, "你好。")
        check(False, "ambiguous quote must raise")
    except ValueError:
        pass
    # unambiguous quote resolves
    loc = locate_quote(text, "乙说：你好。")
    check(loc is not None, "unique quote resolves")
    check(loc.content_start < loc.content_end, "quote content range valid")
    # absent quote → None
    check(locate_quote(text, "不存在") is None, "absent quote None")
    # anchor disambiguates: "甲说" touches only the first occurrence
    loc2 = locate_quote(text, "你好。", nearby_anchor="甲说")
    check(loc2 is not None and loc2.content_start == 3, "anchor disambiguates to first")
    # a symmetric anchor cannot disambiguate and must raise (tie rejected)
    try:
        locate_quote(text, "你好。", nearby_anchor="乙说：你好。")
        check(False, "symmetric anchor tie must raise")
    except ValueError:
        pass


def test_sidecar() -> None:
    text = "第一段\n\n第二段内容。\n第三段。\n"
    ct, sidecar, offsets = build_sidecar(text)
    check(sidecar.L == non_whitespace_length(ct), "sidecar L matches")
    check(sidecar.K == sidecar.L / 1000, "sidecar K = L/1000")
    check(sidecar.paragraph_count == 3, "sidecar paragraph_count")
    check(sidecar.text_sha256 == __import__("scorer_v5.preprocessing.canonicalize", fromlist=["text_sha256"]).text_sha256(ct), "text hash")
    # paragraph offsets must be ascending and bounded
    starts = [p.content_start for p in sidecar.paragraphs]
    check(starts == sorted(starts), "paragraph offsets ascending")
    check(sidecar.paragraphs[-1].content_end <= sidecar.L, "paragraph end <= L")
    # sidecar hash deterministic
    check(sidecar.sha256() == sidecar.sha256(), "sidecar hash deterministic")
    # empty text rejected
    try:
        build_sidecar("   \n ")
        check(False, "empty text must raise")
    except ValueError:
        pass


def test_windows() -> None:
    text = "a" * 100 + "b" * 100
    off = content_offsets(text)
    # content window 0..50 maps to canonical 0..50
    s, e = __import__("scorer_v5.preprocessing.windows", fromlist=["content_window"]).content_window(off, 0, 50)
    check(s == 0 and e == 50, "content window start/end")
    idx = canonical_index_for_content_offset(off, 100)
    check(idx == 100, "canonical index for content offset")


def test_paragraphs() -> None:
    text = "第一行\n\n\n第二行\n"
    paras = split_paragraphs(text)
    check(len(paras) == 2, "blank lines do not count as paragraphs")
    check(paras[0].index == 1 and paras[1].index == 2, "paragraph indexes 1-based")


if __name__ == "__main__":
    test_canonicalize()
    test_percentage_boundaries()
    test_content_offsets()
    test_locate_quote()
    test_sidecar()
    test_windows()
    test_paragraphs()
    if FAILURES:
        print("FAILURES:")
        for f in FAILURES:
            print(" -", f)
        sys.exit(1)
    print("ALL PASS")
