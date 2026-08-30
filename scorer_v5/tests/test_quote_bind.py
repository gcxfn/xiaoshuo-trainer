#!/usr/bin/env python3
"""Paragraph-id wire format: model cannot pass quote strings through."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scorer_v5.preprocessing.paragraphs import paragraph_bodies
from scorer_v5.preprocessing.spans import build_evidence_spans, format_span_view
from scorer_v5.preprocessing.sidecar import build_sidecar
from scorer_v5.runtime.parsing import parse_model_output
from scorer_v5.runtime.prompts import PROMPT_VERSION, build_prompt
from scorer_v5.runtime.quote_bind import bind_evidence_spans, bind_paragraph_quotes
from scorer_v5.runtime.specs import load_metric_spec
from scorer_v5.runtime.validation import validate_model_output
from scorer_v5.scoring.engine import compute_score

TEXT = "门卫拦住了我。\n「票不能退。」\n"
CT, SIDECAR, OFFSETS = build_sidecar(TEXT)


def main() -> int:
    failures: list[str] = []
    spans = build_evidence_spans(CT)
    if len(spans) < 2:
        failures.append(f"expected >=2 spans, got {len(spans)}: {[s.text for s in spans]}")
    # Same physical paragraph must yield multiple distinct span ids (issue #2).
    multi = build_evidence_spans("「按规矩，票不能退。」门卫盯着我。\n")
    if len(multi) < 2:
        failures.append(f"same paragraph must split into multiple spans, got {len(multi)}")
    ids = [s.span_id for s in multi]
    if len(ids) != len(set(ids)):
        failures.append(f"span ids must be unique: {ids}")
    view = format_span_view(CT)
    if "S001" not in view or "S002" not in view:
        failures.append("span view must contain S001/S002 labels")

    # Exact span coordinates (issue #1): a later sentence in a paragraph must
    # have a later content_start than the first sentence.
    para = "第一句。第二句。\n"
    pspans = build_evidence_spans(para)
    if len(pspans) != 2:
        failures.append(f"paragraph should split into 2 spans, got {len(pspans)}")
    else:
        if not (pspans[0].content_start < pspans[1].content_start):
            failures.append("span order by content_start must be ascending")

    # Regression (AC2): a bare quoted turn that is NOT the first in its
    # paragraph must still form its own span. `"离职？"我愣住了，"我昨天还在上班啊。"`
    # must yield [「离职？」][我愣住了，][「我昨天还在上班啊。」].
    bare = '我心里一沉："怎么会？我上周还在用。"老张摇头："系统显示你上周五就离职了，工牌已注销。""离职？"我愣住了，"我昨天还在上班啊。"老张叹了口气："人事通知的，你自己去问吧。"\n'
    bspans = build_evidence_spans(bare)
    btexts = [s.text for s in bspans]
    if '"离职？"' not in btexts:
        failures.append(f"bare later turn must be its own span, got {btexts}")
    if '"我昨天还在上班啊。"' not in btexts:
        failures.append(f"later non-initial quoted turn must be its own span, got {btexts}")
    if "我愣住了，" not in btexts:
        failures.append(f"prose between turns must be its own span, got {btexts}")
    if "".join(btexts) != bare.rstrip("\n"):
        failures.append("bare-turn spans must reconstruct the paragraph verbatim")

    spec = load_metric_spec("B01")
    prompt = build_prompt(spec, CT)
    for bit in (
        "证据绑定（程序填原文）",
        "禁止输出引文字符串",
        "S012 → 12",
        "S001",
        "门卫拦住了我。",
    ):
        if bit not in prompt:
            failures.append(f"prompt missing {bit!r}")
    if PROMPT_VERSION != "v5.1-prompt-9":
        failures.append(f"PROMPT_VERSION={PROMPT_VERSION}")

    # Wire format: integer span id binds to exact span body; wire is preserved.
    raw_ok = json.dumps({
        "status": "OK",
        "semantic": {
            "candidates": [{
                "event_quote": 1,
                "is_external_event": True,
                "same_scene_action": False,
                "action_quote": None,
                "qualifies": True,
            }],
        },
    }, ensure_ascii=False)
    parsed = parse_model_output(raw_ok, formal=True, spec=spec)
    if parsed.parse_status != "OK":
        failures.append(f"span id must parse, got {parsed.parse_status} {parsed.error}")
    else:
        wire_before = dict(parsed.value)
        bound, index = bind_evidence_spans(parsed.value["semantic"], CT)
        if bound["candidates"][0]["event_quote"] != spans[0].text:
            failures.append(f"bind did not copy exact span body: {bound['candidates'][0]['event_quote']!r}")
        if parsed.value.get("semantic") is not wire_before.get("semantic"):
            failures.append("parsed.value semantic must not be mutated in place (wire preserved)")
        if 1 not in index:
            failures.append("span index must contain span id 1")
        parsed.value["semantic"] = bound
        result = validate_model_output(parsed, spec, CT, content_offsets=OFFSETS)
        scored = compute_score(spec, result, CT, SIDECAR)
        if not result.accepted_semantic_facts:
            failures.append(f"bound quote should validate, issues={[i.message for i in result.issues]}")
        if scored.score is None and result.outcome != "OK":
            failures.append(f"unexpected outcome {result.outcome} score={scored.score}")

    # Quote string must FAIL_SCHEMA (issue #4).
    raw_str = json.dumps({
        "status": "OK",
        "semantic": {
            "candidates": [{
                "event_quote": "门卫拦住了我。",
                "is_external_event": True,
                "same_scene_action": False,
                "action_quote": None,
                "qualifies": True,
            }],
        },
    }, ensure_ascii=False)
    parsed_str = parse_model_output(raw_str, formal=True, spec=spec)
    if parsed_str.parse_status != "FAIL_SCHEMA":
        failures.append(f"quote string must FAIL_SCHEMA, got {parsed_str.parse_status}")

    # Array element string must FAIL_SCHEMA (issue #4).
    raw_arr = json.dumps({
        "status": "OK",
        "semantic": {
            "events": [{
                "round_quotes": ["按规矩，票不能退。"],
                "nearby_anchor": None,
                "literal_meaning": "拒绝",
                "real_meaning": "施压",
                "decoding_evidence": 1,
                "game_goal": "退票",
                "qualifies": True,
            }],
        },
    }, ensure_ascii=False)
    n6 = load_metric_spec("N6")
    parsed_arr = parse_model_output(raw_arr, formal=True, spec=n6)
    if parsed_arr.parse_status != "FAIL_SCHEMA":
        failures.append(f"quote array string element must FAIL_SCHEMA, got {parsed_arr.parse_status}")

    # Model-written strings are discarded (issue #4 / bind semantics).
    leaked = bind_paragraph_quotes({"event_quote": "她从床边摔下去"}, CT)
    if leaked["event_quote"] != "":
        failures.append("bind must discard model-written strings")

    # Out-of-range id binds empty.
    missing = bind_paragraph_quotes({"event_quote": 99}, CT)
    if missing["event_quote"] != "":
        failures.append("out-of-range id must bind empty")

    # paragraph_bodies still works (paragraph view retained for sidecar).
    bodies = paragraph_bodies(CT)
    if 1 not in bodies or "门卫拦住了我。" not in bodies[1]:
        failures.append(f"paragraph 1 body wrong: {bodies}")

    if failures:
        print("FAIL:")
        for item in failures:
            print(" -", item)
        return 1
    print("PASS: evidence span bind (exact position, wire preserved, string rejected)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
