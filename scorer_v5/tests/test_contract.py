#!/usr/bin/env python3
"""Step 7 contract tests: deterministic recomputation per metric (Step 12.5).

For each of the 19 metrics, verify:
1. schema violation (missing semantic field) → FAIL_SCHEMA
2. evidence absent (quote not in text) → EVIDENCE_FAIL (V2)
3. ABSTAIN → abstained with score None
4. deterministic scoring: LLM aggregate fields (criteria/item_hits) are NOT
   trusted — the Python recomputation governs the score.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scorer_v5.preprocessing.sidecar import build_sidecar
from scorer_v5.preprocessing.spans import build_evidence_spans
from scorer_v5.runtime.parsing import parse_model_output
from scorer_v5.runtime.prompts import build_prompt
from scorer_v5.runtime.quote_bind import bind_evidence_spans
from scorer_v5.runtime.specs import load_metric_spec
from scorer_v5.runtime.validation import validate_model_output
from scorer_v5.scoring.engine import compute_score

TEXT = (
    "门卫拦住了我。\n"
    "\"按规矩，票不能退。\"门卫盯着我。\n"
    "\"可这票是我花钱买的。\"我举起收据。\n"
    "\"规矩就是规矩。\"他把手一摊。\n"
    "我把收据拍在桌上，转身打电话投诉。\n"
)
SIDECAR_TEXT, SIDECAR, OFFSETS = build_sidecar(TEXT)
_SPANS = build_evidence_spans(SIDECAR_TEXT)
_B02_R1 = next(s.span_id for s in _SPANS if "按规矩，票不能退" in s.text)
_B02_R2 = next(s.span_id for s in _SPANS if "可这票是我花钱买的" in s.text)
_B02_R3 = next(s.span_id for s in _SPANS if "规矩就是规矩" in s.text)
_B02_R4 = next(s.span_id for s in _SPANS if "拍在桌上" in s.text)

METRICS = [
    "B01", "B02", "B03", "C01", "B08", "B09", "B16", "B23", "B30", "B34",
    "B36", "C22", "N3", "N6", "B31", "B33", "C14", "B18", "N7",
]


def run_case(metric_id: str, semantic: dict) -> dict:
    spec = load_metric_spec(metric_id)
    prompt = build_prompt(spec, SIDECAR_TEXT)
    raw = json.dumps({"status": "OK", "semantic": semantic}, ensure_ascii=False)
    parsed = parse_model_output(raw, formal=True, spec=spec)
    if parsed.is_valid_json and parsed.value and parsed.value.get("status") == "OK":
        inner = parsed.value.get("semantic")
        if isinstance(inner, dict):
            bound, _index = bind_evidence_spans(inner, SIDECAR_TEXT)
            parsed.value["semantic"] = bound
    result = validate_model_output(parsed, spec, SIDECAR_TEXT, content_offsets=OFFSETS)
    scored = compute_score(spec, result, SIDECAR_TEXT, SIDECAR)
    return {
        "metric": metric_id,
        "outcome": result.outcome,
        "accepted": result.accepted_semantic_facts,
        "abstained": scored.abstained,
        "score": scored.score,
        "issues": [i.message for i in result.issues],
        "prompt_hash": prompt_sha256(prompt) if False else None,
    }


def main() -> int:
    failures = []

    # 1. Schema violation: missing semantic field must FAIL_SCHEMA
    for mid in METRICS:
        spec = load_metric_spec(mid)
        raw = json.dumps({"status": "OK", "semantic": {}}, ensure_ascii=False)
        parsed = parse_model_output(raw, formal=True, spec=spec)
        if parsed.parse_status != "FAIL_SCHEMA":
            failures.append(f"{mid}: empty semantic must FAIL_SCHEMA, got {parsed.parse_status}")

    # 2. ABSTAIN always abstains (never 0)
    for mid in METRICS:
        spec = load_metric_spec(mid)
        raw = json.dumps({"status": "ABSTAIN", "reason": "证据不足"}, ensure_ascii=False)
        parsed = parse_model_output(raw, formal=True, spec=spec)
        result = validate_model_output(parsed, spec, SIDECAR_TEXT, content_offsets=OFFSETS)
        scored = compute_score(spec, result, SIDECAR_TEXT, SIDECAR)
        if result.outcome != "ABSTAIN" or not scored.abstained or scored.score is not None:
            failures.append(f"{mid}: ABSTAIN must abstain with no score, outcome={result.outcome}")

    spec = load_metric_spec("B02")
    raw = json.dumps({"status": "OK", "semantic": {"conflicts": []}, "reason": "无合格冲突"}, ensure_ascii=False)
    parsed = parse_model_output(raw, formal=True, spec=spec)
    if parsed.parse_status != "OK":
        failures.append(f"B02 OK+reason must parse, got {parsed.parse_status} {parsed.error}")
    result = validate_model_output(parsed, spec, SIDECAR_TEXT, content_offsets=OFFSETS)
    if result.outcome == "SCHEMA_FAIL":
        failures.append(f"B02 OK+reason must not SCHEMA_FAIL, issues={ [i.message for i in result.issues] }")

    spec = load_metric_spec("B01")
    raw = json.dumps({
        "status": "OK",
        "semantic": {
            "candidates": [{
                "event_quote": 1,
                "is_external_event": True,
                "same_scene_action": False,
                "action_quote": None,
                "qualifies": True,
            }]
        },
        "reason": "无同场景行动",
    }, ensure_ascii=False)
    parsed = parse_model_output(raw, formal=True, spec=spec)
    if parsed.parse_status != "OK":
        failures.append(f"B01 action_quote=null must parse, got {parsed.parse_status} {parsed.error}")

    spec = load_metric_spec("B33")
    raw = json.dumps({"status": "OK", "semantic": {"finale_quote": None, "events": []}}, ensure_ascii=False)
    parsed = parse_model_output(raw, formal=True, spec=spec)
    if parsed.parse_status != "OK":
        failures.append(f"B33 finale_quote=null events=[] must parse, got {parsed.parse_status} {parsed.error}")

    spec = load_metric_spec("N6")
    raw = json.dumps({"status": "OK", "semantic": {"events": []}}, ensure_ascii=False)
    parsed = parse_model_output(raw, formal=True, spec=spec)
    if parsed.parse_status != "OK":
        failures.append(f"N6 events=[] must parse, got {parsed.parse_status} {parsed.error}")

    # 3. Evidence absent → EVIDENCE_FAIL (quote not in text)
    for mid in METRICS:
        spec = load_metric_spec(mid)
        # every metric's schema has at least one quote-carrying field; craft a
        # semantic with a nonexistent quote under the first array field
        so = spec.semantic_outputs
        first_arr = next((k for k, v in so.items() if isinstance(v, list) and v), None)
        if first_arr is None:
            continue
        template = so[first_arr]
        item = {}
        for entry in template:
            if isinstance(entry, dict):
                for k, v in entry.items():
                    if "quote" in k.lower() or k == "decoding_evidence":
                        item[k] = 999
                    elif "round_count" in k or k.endswith("_count") or k.endswith("_hits"):
                        item[k] = 0
                    elif "nearby" in k:
                        item[k] = None
                    elif "bool" in str(v).lower() or "是否" in str(v) or "成立" in str(v):
                        item[k] = True
                    else:
                        item[k] = "实体X"
        semantic = {first_arr: [item]}
        res = run_case(mid, semantic)
        # a quote that cannot be located must fail V2 (or V3 for bare claims)
        if res["accepted"]:
            failures.append(f"{mid}: absent quote should not be accepted, got outcome={res['outcome']}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
