#!/usr/bin/env python3
"""Pipeline smoke test: sidecar → parse → validate → derive → score.

Runs against the frozen specs to prove the deterministic engine produces the
documented 0/5/10 branch semantics for representative metrics. Formal-frozen
behaviour: a malformed or unverifiable output is a hard failure, never repaired.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scorer_v5.preprocessing.sidecar import build_sidecar
from scorer_v5.preprocessing.spans import build_evidence_spans
from scorer_v5.runtime.parsing import parse_model_output
from scorer_v5.runtime.prompts import build_prompt, prompt_sha256
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
SPANS = build_evidence_spans(SIDECAR_TEXT)
SPAN_TEXT = {s.span_id: s.text for s in SPANS}
# Map the fixture sentences to span ids by exact body.
_B02_R1 = next(s.span_id for s in SPANS if "按规矩，票不能退" in s.text)
_B02_R2 = next(s.span_id for s in SPANS if "可这票是我花钱买的" in s.text)
_B02_R3 = next(s.span_id for s in SPANS if "规矩就是规矩" in s.text)
_B02_R4 = next(s.span_id for s in SPANS if "拍在桌上" in s.text)


def make_output(spec, semantic: dict) -> str:
    return json.dumps({"status": "OK", "semantic": semantic}, ensure_ascii=False)


def run_case(metric_id: str, semantic: dict) -> dict:
    spec = load_metric_spec(metric_id)
    prompt = build_prompt(spec, SIDECAR_TEXT)
    raw = make_output(spec, semantic)
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
        "accepted": result.accepted_semantic_facts,
        "abstained": scored.abstained,
        "score": scored.score,
        "derived": scored.derived,
        "issues": [i.message for i in result.issues],
        "prompt_hash": prompt_sha256(prompt),
    }


def main() -> int:
    failures = []

    # B02: two-complete-exchange conflict at ≤500 and same-lineage → 10
    b02 = run_case("B02", {
        "conflicts": [{
            "entity_a": "我", "entity_b": "门卫", "issue": "退票",
            "round1_quote": _B02_R1, "round2_quote": _B02_R2,
            "round3_quote": _B02_R3, "round4_quote": _B02_R4,
            "round_count": 4, "nearby_anchor": None,
            "same_lineage": True, "qualifies": True,
        }],
    })
    print("B02:", b02["score"], b02["accepted"])
    if b02["score"] != 10:
        failures.append(f"B02 expected 10, got {b02['score']}")

    # B02: single A→B exchange (round_count 2) must NOT be a qualified conflict → 0
    b02_short = run_case("B02", {
        "conflicts": [{
            "entity_a": "我", "entity_b": "门卫", "issue": "退票",
            "round1_quote": _B02_R1, "round2_quote": _B02_R2,
            "round3_quote": None, "round4_quote": None, "round_count": 2,
            "nearby_anchor": None, "same_lineage": True, "qualifies": True,
        }],
    })
    print("B02 short:", b02_short["score"], b02_short["accepted"])
    if b02_short["score"] != 0:
        failures.append(f"B02 short expected 0, got {b02_short['score']}")

    # N6: three qualified events → F = 3 / (L/1000); L≈76 → F≈39.5 ≥ 0.50 → 10
    n6 = run_case("N6", {
        "events": [
            {"round_quotes": [_B02_R1, _B02_R2],
             "nearby_anchor": _B02_R1, "literal_meaning": "拒绝", "real_meaning": "施压",
             "decoding_evidence": _B02_R2, "game_goal": "退票", "qualifies": True},
            {"round_quotes": [_B02_R2, _B02_R3],
             "nearby_anchor": _B02_R2, "literal_meaning": "坚持", "real_meaning": "挑衅",
             "decoding_evidence": _B02_R3, "game_goal": "赔偿", "qualifies": True},
            {"round_quotes": [_B02_R3, _B02_R4],
             "nearby_anchor": _B02_R1, "literal_meaning": "主张", "real_meaning": "反击",
             "decoding_evidence": _B02_R4, "game_goal": "道歉", "qualifies": True},
        ],
    })
    print("N6:", n6["score"], n6["derived"].get("F"), n6["accepted"])
    if n6["score"] != 10:
        failures.append(f"N6 expected 10, got {n6['score']}")

    # ABSTAIN must produce abstained=True and score=None (never 0)
    spec = load_metric_spec("B02")
    raw = json.dumps({"status": "ABSTAIN", "reason": "无法确认回合边界"}, ensure_ascii=False)
    parsed = parse_model_output(raw, formal=True, spec=spec)
    result = validate_model_output(parsed, spec, SIDECAR_TEXT, content_offsets=OFFSETS)
    scored = compute_score(spec, result, SIDECAR_TEXT, SIDECAR)
    print("ABSTAIN:", scored.abstained, scored.score)
    if not scored.abstained or scored.score is not None:
        failures.append("ABSTAIN must be abstained with no score")

    # Malformed JSON must hard-fail in formal mode (no repair)
    bad = parse_model_output('{"status": "OK",', formal=True, spec=spec)
    print("FAIL_PARSE:", bad.parse_status)
    if bad.parse_status != "FAIL_PARSE":
        failures.append("malformed JSON must FAIL_PARSE")

    # Duplicate key must hard-fail (no last-write-wins)
    dup = parse_model_output('{"status":"OK","status":"ABSTAIN"}', formal=True, spec=spec)
    print("DUP:", dup.parse_status)
    if dup.parse_status != "FAIL_DUPLICATE_KEY":
        failures.append("duplicate key must FAIL_DUPLICATE_KEY")

    # Schema violation must hard-fail with FAIL_SCHEMA (missing semantic field)
    bad_schema = parse_model_output('{"status":"OK","semantic":{}}', formal=True, spec=spec)
    print("SCHEMA:", bad_schema.parse_status)
    if bad_schema.parse_status != "FAIL_SCHEMA":
        failures.append("missing semantic fields must FAIL_SCHEMA")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
