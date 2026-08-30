#!/usr/bin/env python3
"""Envelope unwrap: complete single JSON fence only; inner JSON never edited."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scorer_v5.runtime.parsing import parse_model_output, unwrap_complete_json_fence
from scorer_v5.runtime.specs import load_metric_spec


INNER = '{"status":"ABSTAIN","reason":"x"}'


def main() -> int:
    failures: list[str] = []
    spec = load_metric_spec("B02")

    fenced = "```json\n" + INNER + "\n```"
    if unwrap_complete_json_fence(fenced) != INNER + "\n":
        # inner keeps the newline before closing fence; json.loads still works
        un = unwrap_complete_json_fence(fenced)
        try:
            json.loads(un)
        except Exception:
            failures.append(f"unwrap inner not JSON: {un!r}")
    parsed = parse_model_output(fenced, formal=True, spec=spec)
    if parsed.parse_status != "OK":
        failures.append(f"fenced ABSTAIN must parse OK, got {parsed.parse_status} {parsed.error}")
    if parsed.value != {"status": "ABSTAIN", "reason": "x"}:
        failures.append(f"inner JSON mutated: {parsed.value}")
    if parsed.repair_attempted:
        failures.append("fence unwrap must not set repair_attempted")

    bare = parse_model_output(INNER, formal=True, spec=spec)
    if bare.parse_status != "OK":
        failures.append("bare JSON still OK")

    prose = "如下：\n```json\n" + INNER + "\n```"
    bad = parse_model_output(prose, formal=True, spec=spec)
    if bad.parse_status != "FAIL_PARSE":
        failures.append("prose+fence must FAIL_PARSE")

    trunc = "```json\n" + INNER
    bad2 = parse_model_output(trunc, formal=True, spec=spec)
    if bad2.parse_status != "FAIL_PARSE":
        failures.append("truncated fence must FAIL_PARSE")

    after = "```json\n" + INNER + "\n```\n解释如上"
    bad3 = parse_model_output(after, formal=True, spec=spec)
    if bad3.parse_status != "FAIL_PARSE":
        failures.append("fence+trailing prose must FAIL_PARSE")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
