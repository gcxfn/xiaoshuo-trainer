#!/usr/bin/env python3
"""B31/B34/B18 seven-band reachability test (Step 12.5 二次修订).

For each metric, drive the full pipeline (parse → validate → derive → score)
with schema-valid semantic fixtures and assert each of the seven allowed bands
(0/1/3/5/7/9/10) is reachable.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scorer_v5.preprocessing.sidecar import build_sidecar
from scorer_v5.preprocessing.spans import build_evidence_spans
from scorer_v5.runtime.parsing import parse_model_output
from scorer_v5.runtime.quote_bind import bind_evidence_spans, is_bind_field
from scorer_v5.runtime.specs import load_metric_spec
from scorer_v5.runtime.validation import validate_model_output
from scorer_v5.scoring.engine import compute_score

# Longer synthetic text: 14 distinct sentences so B18 can build ≥10 middle scenes.
_LINES = [
    "门卫拦住了我。",
    "「按规矩，票不能退。」门卫盯着我。",
    "「可这票是我花钱买的。」我举起收据。",
    "「规矩就是规矩。」他把手一摊。",
    "我把收据拍在桌上，转身打电话投诉。",
    "电话那头传来值班经理的声音。",
    "经理说可以退票，但要扣除手续费。",
    "门卫依然拦在门口，不肯让开。",
    "我拿出手机，开始录像留证。",
    "门卫伸手挡住了镜头。",
    "这时队长赶到了现场。",
    "队长问清楚情况，让门卫放行。",
    "我顺利通过了闸机。",
    "回头望去，门卫还在原地发呆。",
]
TEXT = "\n".join(_LINES) + "\n"
SIDECAR_TEXT, SIDECAR, OFFSETS = build_sidecar(TEXT)

C1 = _LINES[1]
C2 = _LINES[2]
C3 = _LINES[3]
C4 = _LINES[4]


def _wire_encode(value, text: str):
    """Test-only: replace quote-like string values with span ids.

    Quote strings resolve to the unique span whose body contains them. For
    ambiguous or multi-span strings (e.g. a fixture line that spans several
    spans), prefer the span nearest to any other bind value in the same object,
    or the span containing the longest leading prefix.
    """
    spans = build_evidence_spans(text)
    spans_by_text = {}
    for s in spans:
        spans_by_text.setdefault(s.text, []).append(s.span_id)

    def resolve(quote: str, context_ids: set[int]) -> int:
        if quote in spans_by_text and len(spans_by_text[quote]) == 1:
            return spans_by_text[quote][0]
        candidates = []
        for s in spans:
            if quote in s.text:
                candidates.append(s.span_id)
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            prefix = quote
            while len(prefix) >= 2:
                prefix = prefix[:-1]
                cand = [s.span_id for s in spans if prefix and prefix in s.text]
                if len(cand) == 1:
                    return cand[0]
                if cand:
                    candidates = cand
                    break
        if context_ids:
            nearest = min(candidates, key=lambda sid: min((abs(sid - c) for c in context_ids), default=10**9))
            return nearest
        raise ValueError(f"fixture quote not uniquely resolvable: {quote!r} (candidates={candidates})")

    def rec(node, context: set[int]):
        if isinstance(node, dict):
            ctx = set(context)
            out = {}
            for k, v in node.items():
                if is_bind_field(k) and isinstance(v, str) and v != "":
                    sid = resolve(v, ctx)
                    out[k] = sid
                    ctx.add(sid)
                elif is_bind_field(k) and isinstance(v, list):
                    ids = []
                    for item in v:
                        if isinstance(item, str) and item:
                            sid = resolve(item, ctx)
                            ids.append(sid)
                            ctx.add(sid)
                        else:
                            ids.append(item)
                    out[k] = ids
                elif isinstance(v, dict):
                    out[k] = rec(v, ctx)
                elif isinstance(v, list):
                    out[k] = [rec(item, ctx) for item in v]
                else:
                    out[k] = v
            return out
        if isinstance(node, list):
            return [rec(item, context) for item in node]
        return node

    return rec(value, set())


def run(mid: str, semantic: dict) -> tuple[int | None, dict, list[str]]:
    spec = load_metric_spec(mid)
    semantic = _wire_encode(semantic, SIDECAR_TEXT)
    raw = json.dumps({"status": "OK", "semantic": semantic}, ensure_ascii=False)
    parsed = parse_model_output(raw, formal=True, spec=spec)
    if parsed.parse_status != "OK":
        return None, {}, [parsed.parse_status + ": " + (parsed.error or "")]
    bound, _index = bind_evidence_spans(parsed.value["semantic"], SIDECAR_TEXT)
    parsed.value["semantic"] = bound
    result = validate_model_output(parsed, spec, SIDECAR_TEXT, content_offsets=OFFSETS)
    if not result.accepted_semantic_facts:
        return None, {}, [i.message for i in result.issues]
    scored = compute_score(spec, result, SIDECAR_TEXT, SIDECAR)
    return scored.score, scored.derived, []


# ---- B31 ----
# item1 = round3+round4 locatable & round_count≥4; item2/3/4 = quote locatable.
# Quotes nullable → item_count can be 1..4.
def b31_sem(irr: str | None, sensory: str | None, foresh: str | None,
            has_r3r4: bool, llm_rc: int) -> dict:
    return {"candidates": [{
        "scene_quote": C1, "round1_quote": C1, "round2_quote": C2,
        "round3_quote": C3 if has_r3r4 else None, "round4_quote": C4 if has_r3r4 else None,
        "round_count": llm_rc, "irrevocable_quote": irr, "sensory_quote": sensory,
        "foreshadow_quote": foresh, "item_hits": True,
    }]}


# ---- B34 ----
def b34_sem(pub: str | None, defeat: str | None, trigger: str | None,
            cost: str | None, ents: str) -> dict:
    return {"candidates": [{
        "scene_quote": C1, "entities_present": ents,
        "public_quote": pub, "defeat_quote": defeat, "trigger_quote": trigger,
        "cost_quote": cost, "is_realtime": True, "determines_mainline": True,
        "item_hits": True,
    }]}


# ---- B18 ----
def b18_sem(n_scenes: int, invalid_indices: list[int], consecutive: bool) -> dict:
    """Explicit invalid indices; `consecutive` forces a 3-run at the front instead."""
    pool = _LINES[5:]
    scenes = []
    if consecutive:
        for i in range(n_scenes):
            scenes.append({"scene_quote": pool[i % len(pool)], "state_before": "before", "state_after": "after", "state_axis": "新信息", "valid": i >= 3})
    else:
        for i in range(n_scenes):
            scenes.append({"scene_quote": pool[i % len(pool)], "state_before": "before", "state_after": "after", "state_axis": "新信息", "valid": i not in invalid_indices})
    return {"endpoints": [{"hook_quote": C1, "climax_quote": C4}], "middle_scenes": scenes}


def main() -> int:
    failures = []

    # B31: all seven bands.
    b31_cases = [
        # 0: ≤1 项 (只有②)
        ("B31 0: 1项", b31_sem(C2, None, None, False, 2), 0),
        # 1: 2项缺① (②③, 无r3r4)
        ("B31 1: 2项缺①", b31_sem(C2, C3, None, False, 2), 1),
        # 3: 2项含①② (①②, 无③④) — item1需要r3r4, item2=irr
        ("B31 3: 2项含①②", b31_sem(C2, None, None, True, 4), 3),
        # 5: 3项缺① (②③④, 无r3r4)
        ("B31 5: 3项缺①", b31_sem(C2, C3, C4, False, 2), 5),
        # 5: 4项缺②
        ("B31 5: 4项缺②", b31_sem(None, C3, C4, True, 4), 5),
        # 7: 3项含①② (①+②+③, 无④)
        ("B31 7: 3项含①②", b31_sem(C2, C3, None, True, 4), 7),
        # 9: 4项含①② rc<6
        ("B31 9: 4项 rc4", b31_sem(C2, C3, C4, True, 4), 9),
        # 10: 4项含①② rc≥6
        ("B31 10: 4项 rc6", b31_sem(C2, C3, C4, True, 6), 10),
    ]
    print("=== B31 ===")
    for label, sem, expect in b31_cases:
        s, d, iss = run("B31", sem)
        print(f"  {label}: score={s} count={d.get('item_count')} rc={d.get('round_count')}")
        if s != expect:
            failures.append(f"{label}: expected {expect}, got {s} {iss}")

    # B34: all seven bands.
    b34_cases = [
        # 0: 1项 (仅④)
        ("B34 0: 1项", b34_sem(None, None, None, C4, "门卫"), 0),
        # 1: 2项缺①④ (②③)
        ("B34 1: 2项缺①④", b34_sem(None, C2, C3, None, "门卫"), 1),
        # 3: 2项含①④
        ("B34 3: 2项含①④", b34_sem(C1, None, None, C4, "门卫"), 3),
        # 5: 3项缺④ (①②③)
        ("B34 5: 3项缺④", b34_sem(C1, C2, C3, None, "门卫"), 5),
        # 5: 4项缺①
        ("B34 5: 4项缺①", b34_sem(None, C2, C3, C4, "门卫"), 5),
        # 7: 3项含①④ (①+②+④, 无③)
        ("B34 7: 3项含①④", b34_sem(C1, C2, None, C4, "门卫"), 7),
        # 9: 4项 ent<5
        ("B34 9: 4项 ent<5", b34_sem(C1, C2, C3, C4, "门卫、我"), 9),
        # 10: 4项 ent≥5（用唯一出现称谓避免歧义）
        ("B34 10: 4项 ent>=5", b34_sem(C1, C2, C3, C4, "值班经理、手机、镜头、闸机、现场"), 10),
    ]
    print("=== B34 ===")
    for label, sem, expect in b34_cases:
        s, d, iss = run("B34", sem)
        print(f"  {label}: score={s} count={d.get('item_count')} ent={d.get('entity_count')}")
        if s != expect:
            failures.append(f"{label}: expected {expect}, got {s} {iss}")

    # B18: intervals; consecutive≥3 → 0.
    b18_cases = [
        # 0: ratio ≥50% (2 scenes, 0 valid → 1.0)
        ("B18 0: ratio 1.0", b18_sem(2, [0, 1], False), 0),
        # 0: consecutive 3
        ("B18 0: consec 3", b18_sem(6, [0, 1, 2], True), 0),
        # 1: [40,50): 4 invalid / 10
        ("B18 1: [40,50)", b18_sem(10, [0, 2, 4, 6], False), 1),
        # 3: [30,40): 3 invalid / 10
        ("B18 3: [30,40)", b18_sem(10, [0, 3, 6], False), 3),
        # 5: [25,30): 2 invalid / 8
        ("B18 5: [25,30)", b18_sem(8, [0, 4], False), 5),
        # 7: [15,25): 2 invalid / 10
        ("B18 7: [15,25)", b18_sem(10, [0, 5], False), 7),
        # 9: [5,15): 1 invalid / 10
        ("B18 9: [5,15)", b18_sem(10, [0], False), 9),
        # 10: <5%: 0 invalid / 10
        ("B18 10: <5%", b18_sem(10, [], False), 10),
    ]
    print("=== B18 ===")
    for label, sem, expect in b18_cases:
        s, d, iss = run("B18", sem)
        print(f"  {label}: score={s} ratio={d.get('invalid_ratio')} consec={d.get('consecutive_invalid')}")
        if s != expect:
            failures.append(f"{label}: expected {expect}, got {s} {iss}")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
