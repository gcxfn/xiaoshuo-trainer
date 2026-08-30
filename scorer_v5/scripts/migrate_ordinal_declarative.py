#!/usr/bin/env python3
"""Migrate draft-4 `{branch_key: score}` ordinal_mapping to declarative form.

Run once from the repo root. Each metric's key→score list is converted to
`{score, when}` conditions with thresholds in the YAML. The per-metric mapping
below is the authoritative translation of the frozen v4.0.0 branch semantics
(0/10 verbatim, intermediates refine the 5 branch).
"""
from __future__ import annotations

import sys
from pathlib import Path
import yaml

SPECS_DIR = Path("scorer_v5/specs")

# field aliases used by extractors
FIELDS = {
    "B01": {"F": "q", "hits": "item_hits_count"},
    "B02": {"F": "position_ratio", "hits": "b02_hits"},
    "B03": {"c1": "c1", "c2": "c2", "c3": "c3", "count": "criterion_count"},
    "C01": {"count": "item_count"},
    "B08": {"count": "criterion_count"},
    "B09": {"count": "criterion_count"},
    "B16": {"count": "item_count", "veto": "veto_found"},
    "B23": {"count": "criterion_count"},
    "B30": {"count": "criterion_count"},
    "B34": {"count": "item_count", "item1": "item1", "item4": "item4"},
    "B36": {"count": "criterion_count"},
    "C22": {"count": "item_count", "veto": "veto_found"},
    "N3": {"count": "criterion_count", "peak": "peak_found"},
    "N6": {"F": "F"},
    "B31": {"count": "item_count", "item1": "item1", "item2": "item2"},
    "B33": {"F": "F"},
    "C14": {"count": "item_count", "x1": "x1_ratio", "x2": "x2_ratio", "y": "y_veto"},
    "B18": {"ratio": "invalid_ratio", "consec": "consecutive_invalid"},
    "N7": {"count": "criterion_count"},
}


def cond(field, op, value=None):
    c = {"field": field, "op": op}
    if op not in ("is_true", "is_false"):
        c["value"] = value
    return c


def when_and(*conds):
    return {"and": list(conds)}


def migrate_b01(items):
    # 0=no event or q>10%; 10=q≤10% & P & action; 5=two of P/action; 3=one; 1=none
    return [
        {"score": 0, "when": {"or": [cond("event_count", "eq", 0), cond("q", "gt", 0.10)]}},
        {"score": 10, "when": when_and(cond("q", "lte", 0.10), cond("paragraph_ok", "is_true"), cond("action_in_scene", "is_true"))},
        {"score": 5, "when": when_and(cond("q", "lte", 0.10), cond("paragraph_ok", "is_true"), cond("action_in_scene", "is_false"))},
        {"score": 3, "when": when_and(cond("q", "lte", 0.10), cond("paragraph_ok", "is_false"), cond("action_in_scene", "is_true"))},
        {"score": 1, "when": when_and(cond("q", "lte", 0.10), cond("paragraph_ok", "is_false"), cond("action_in_scene", "is_false"))},
    ]


def migrate_b02(items):
    return [
        {"score": 0, "when": {"or": [cond("qualified", "is_false"), cond("position_ratio", "gt", 0.15)]}},
        {"score": 10, "when": when_and(cond("first_round_le_500", "is_true"), cond("same_lineage", "is_true"))},
        {"score": 1, "when": when_and(cond("qualified", "is_true"), cond("position_ratio", "lte", 0.15), cond("b02_hits", "eq", 0))},
        {"score": 3, "when": when_and(cond("qualified", "is_true"), cond("position_ratio", "lte", 0.15), cond("b02_hits", "eq", 1))},
        {"score": 5, "when": when_and(cond("qualified", "is_true"), cond("position_ratio", "lte", 0.15), cond("b02_hits", "eq", 2))},
        {"score": 5, "when": when_and(cond("qualified", "is_true"), cond("position_ratio", "lte", 0.15), cond("first_round_le_500", "is_false"))},
    ]


def migrate_b03(items):
    return [
        {"score": 0, "when": cond("criterion_count", "eq", 0)},
        {"score": 10, "when": {"or": [when_and(cond("c1", "is_true"), cond("c2", "is_true")), when_and(cond("c1", "is_true"), cond("c3", "is_true"))]}},
        {"score": 7, "when": when_and(cond("c2", "is_true"), cond("c3", "is_true"), cond("c1", "is_false"))},
        {"score": 5, "when": when_and(cond("c1", "is_true"), cond("c2", "is_false"), cond("c3", "is_false"))},
        {"score": 3, "when": when_and(cond("c2", "is_true"), cond("c1", "is_false"), cond("c3", "is_false"))},
        {"score": 1, "when": when_and(cond("c3", "is_true"), cond("c1", "is_false"), cond("c2", "is_false"))},
    ]


def migrate_count(items, field="item_count", veto_field=None):
    """Generic 0/3/5/10 (or 0/5/10 with veto) count mapping."""
    mapping = []
    if veto_field:
        mapping.append({"score": 0, "when": cond(veto_field, "is_true")})
    mapping.append({"score": 0, "when": cond(field, "eq", 0)})
    mapping.append({"score": 3, "when": cond(field, "eq", 1)})
    mapping.append({"score": 5, "when": cond(field, "eq", 2)})
    mapping.append({"score": 10, "when": cond(field, "eq", 3)})
    return mapping


def migrate_c01(items):
    return [
        {"score": 0, "when": cond("item_count", "eq", 0)},
        {"score": 3, "when": cond("item_count", "eq", 1)},
        {"score": 5, "when": cond("item_count", "eq", 2)},
        {"score": 7, "when": cond("item_count", "eq", 3)},
        {"score": 10, "when": cond("item_count", "eq", 4)},
    ]


def migrate_b16(items):
    return [
        {"score": 0, "when": {"or": [cond("veto_found", "is_true"), cond("item_count", "lte", 1)]}},
        {"score": 5, "when": cond("item_count", "eq", 2)},
        {"score": 10, "when": cond("item_count", "eq", 3)},
    ]


def migrate_b34(items):
    return [
        {"score": 0, "when": cond("item_count", "lte", 1)},
        {"score": 5, "when": {"or": [cond("item_count", "eq", 2), when_and(cond("item_count", "gte", 3), cond("item1", "is_false")), when_and(cond("item_count", "gte", 3), cond("item4", "is_false"))]}},
        {"score": 10, "when": when_and(cond("item1", "is_true"), cond("item4", "is_true"), cond("item_count", "gte", 3))},
    ]


def migrate_c22(items):
    return [
        {"score": 0, "when": cond("veto_found", "is_true")},
        {"score": 1, "when": cond("item_count", "lte", 1)},
        {"score": 3, "when": cond("item_count", "eq", 2)},
        {"score": 5, "when": cond("item_count", "eq", 3)},
        {"score": 10, "when": cond("item_count", "eq", 4)},
    ]


def migrate_n3(items):
    return [
        {"score": 0, "when": {"or": [cond("peak_found", "is_false"), cond("criterion_count", "lte", 2)]}},
        {"score": 5, "when": cond("criterion_count", "eq", 3)},
        {"score": 10, "when": cond("criterion_count", "eq", 4)},
    ]


def migrate_n6(items):
    return [
        {"score": 0, "when": cond("F", "lt", 0.20)},
        {"score": 1, "when": when_and(cond("F", "gte", 0.20), cond("F", "lt", 0.30))},
        {"score": 3, "when": when_and(cond("F", "gte", 0.30), cond("F", "lt", 0.40))},
        {"score": 5, "when": when_and(cond("F", "gte", 0.40), cond("F", "lt", 0.50))},
        {"score": 10, "when": cond("F", "gte", 0.50)},
    ]


def migrate_b31(items):
    return [
        {"score": 0, "when": cond("item_count", "lte", 1)},
        {"score": 5, "when": {"or": [cond("item_count", "eq", 2), when_and(cond("item_count", "gte", 3), cond("item1", "is_false")), when_and(cond("item_count", "gte", 3), cond("item2", "is_false"))]}},
        {"score": 10, "when": when_and(cond("item1", "is_true"), cond("item2", "is_true"), cond("item_count", "gte", 3))},
    ]


def migrate_b33(items):
    return [
        {"score": 0, "when": cond("F", "lt", 0.60)},
        {"score": 1, "when": when_and(cond("F", "gte", 0.60), cond("F", "lt", 0.80))},
        {"score": 3, "when": when_and(cond("F", "gte", 0.80), cond("F", "lt", 1.00))},
        {"score": 5, "when": when_and(cond("F", "gte", 1.00), cond("F", "lt", 1.20))},
        {"score": 10, "when": cond("F", "gte", 1.20)},
    ]


def migrate_c14(items):
    return [
        {"score": 0, "when": {"or": [cond("y_veto", "is_true"), cond("x1_ratio", "gt", 0.30), cond("x2_ratio", "gt", 0.30)]}},
        {"score": 1, "when": cond("item_count", "eq", 0)},
        {"score": 3, "when": cond("item_count", "eq", 1)},
        {"score": 5, "when": cond("item_count", "eq", 2)},
        {"score": 10, "when": cond("item_count", "eq", 3)},
    ]


def migrate_b18(items):
    return [
        {"score": 0, "when": {"or": [cond("invalid_ratio", "gte", 0.50), cond("consecutive_invalid", "gte", 3)]}},
        {"score": 5, "when": when_and(cond("invalid_ratio", "gte", 0.40), cond("invalid_ratio", "lt", 0.50), cond("consecutive_invalid", "lt", 3))},
        {"score": 7, "when": when_and(cond("invalid_ratio", "gte", 0.25), cond("invalid_ratio", "lt", 0.40), cond("consecutive_invalid", "lt", 3))},
        {"score": 9, "when": when_and(cond("invalid_ratio", "gte", 0.10), cond("invalid_ratio", "lt", 0.25))},
        {"score": 10, "when": cond("invalid_ratio", "lt", 0.10)},
    ]


def migrate_n7(items):
    return [
        {"score": 0, "when": cond("criterion_count", "eq", 0)},
        {"score": 3, "when": cond("criterion_count", "eq", 1)},
        {"score": 5, "when": cond("criterion_count", "eq", 2)},
        {"score": 10, "when": cond("criterion_count", "eq", 3)},
    ]


MIGRATORS = {
    "B01": migrate_b01,
    "B02": migrate_b02,
    "B03": migrate_b03,
    "C01": migrate_c01,
    "B08": lambda it: migrate_count(it, "criterion_count"),
    "B09": lambda it: migrate_count(it, "criterion_count"),
    "B16": migrate_b16,
    "B23": lambda it: migrate_count(it, "criterion_count"),
    "B30": lambda it: migrate_count(it, "criterion_count"),
    "B34": migrate_b34,
    "B36": lambda it: migrate_count(it, "criterion_count"),
    "C22": migrate_c22,
    "N3": migrate_n3,
    "N6": migrate_n6,
    "B31": migrate_b31,
    "B33": migrate_b33,
    "C14": migrate_c14,
    "B18": migrate_b18,
    "N7": migrate_n7,
}


def main() -> int:
    for path in sorted(SPECS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        mid = data["metric_id"]
        migrator = MIGRATORS[mid]
        new_mapping = migrator(data.get("ordinal_mapping", []))
        data["ordinal_mapping"] = new_mapping
        allowed = sorted({item["score"] for item in new_mapping})
        data["score_scale"]["allowed"] = allowed
        note = data.get("mapping_note", "")
        data["mapping_note"] = note + (
            "\n（draft-4 Step 12.5 Step 4：ordinal_mapping 为声明式条件，阈值/断点全部在 YAML 中，"
            "ordinal.py 为通用解释器，不再硬编码阈值。）"
        )
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(f"{mid}: {allowed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
