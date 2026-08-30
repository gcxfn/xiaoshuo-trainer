"""Per-metric JSON output schemas (Step 12.5 Step 2).

The prompt, the validator, and the extractor all read the SAME schema, derived
deterministically from the spec's ``semantic_outputs``. This removes the loose
"list of single-key dicts" shape: the model emits one object with exactly the
declared fields; anything else fails V1.

Evidence quote fields use a wire format: the model emits integer span ids
(S012 → 12). Python binds the exact canonical span afterwards. Strings are
rejected by the schema. ``ABSTAIN`` is a first-class status: when ``status``
is ``ABSTAIN`` the object carries only ``status`` + ``reason`` and no
``semantic``.
"""
from __future__ import annotations

from typing import Any

# Fields that are prompt guidance, not model-output fields. The model never
# emits them and the schema never requires them.
_GUIDANCE_SUFFIXES = ("_note", "selection_note", "boundary_note", "exclude_notes", "criteria")


def _is_guidance(key: str) -> bool:
    return key.endswith(_GUIDANCE_SUFFIXES)


def _is_quote_wire_field(field_name: str, description: str = "") -> bool:
    """Model emits span-id integers for evidence quotes; Python fills text."""
    lowered = field_name.casefold()
    if lowered == "extreme_word_quotes":
        return False
    if "quote" in lowered:
        return True
    if lowered in {"decoding_evidence", "nearby_anchor"}:
        return True
    text = str(description)
    return "逐字引文" in text


def _field_type(description: str, field_name: str = "") -> dict[str, Any]:
    """Infer JSON type from the spec description and field name.

    Explicit bool/array/object hints win; quote-like fields are integer
    (wire span id). Numeric field names (round_count, *_count, *_hits) infer
    integer.
    """
    low = description.lower()
    if field_name == "a_code":
        return {"type": "string", "enum": ["A1", "A2", "A3", "A4"]}
    if field_name == "block_type":
        return {"type": "string", "enum": ["直接感知", "想法", "笼统叙述", "全知旁白", "抽象总结", "对话", "其他"]}
    if "bool" in low or "是否" in low or "（bool）" in low or "成立（bool" in low:
        return {"type": "boolean"}
    if _is_quote_wire_field(field_name, description):
        if field_name.endswith(("_quotes", "round_quotes", "core_scene_quotes", "block_quotes")):
            return {"type": "array", "items": {"type": "integer"}}
        if field_name.endswith(("_quotes",)) and field_name != "extreme_word_quotes":
            return {"type": "array", "items": {"type": "integer"}}
        if _is_optional_field(field_name, description):
            return {"type": ["integer", "null"]}
        return {"type": "integer"}
    # array：字段名明确是清单/引文数组，或描述以"清单"结尾且字段名含 quote/list/item
    if field_name.endswith(("_quotes", "_list", "_segments", "_states", "_block_quotes", "_actions")):
        return {"type": "array"}
    if "数组" in low:
        return {"type": "array"}
    # 对象：证据结构（code+quote）、端点结构等
    if field_name in ("endpoints",) or low.startswith("{"):
        return {"type": "object"}
    if "或 null" in low or "（若有" in low or "可选" in low or "若存在" in low or "null=" in low or "时为 null" in low or "为 null" in low:
        return {"type": ["string", "null"]}
    if field_name in ("round_count",) or field_name.endswith(("_count", "_hits", "_number")):
        return {"type": "integer"}
    return {"type": "string"}


def _is_optional_field(field_name: str, description: str) -> bool:
    """可选字段不进 required：nearby_anchor 锚点、条件字段（"…时必填"）、含可选/若有/null 提示。"""
    if field_name == "nearby_anchor" or field_name.endswith(("_note", "_ref")):
        return True
    low = str(description)
    return any(mark in low for mark in ("可选", "（若有", "若存在", "为 null", "时为 null", "时必填", "（若存在）", "或 null"))


def _semantic_properties(semantic_outputs: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for key, template in semantic_outputs.items():
        if _is_guidance(key):
            continue
        required.append(key)
        if isinstance(template, list):
            if template and isinstance(template[0], dict):
                # spec 用 list of single-key dicts 表达项字段（可能跨多个 dict）
                item_properties = {}
                item_required: list[str] = []
                for item in template:
                    if isinstance(item, dict):
                        for item_key, item_desc in item.items():
                            item_properties[item_key] = _field_type(str(item_desc), item_key)
                            if not _is_optional_field(item_key, item_desc):
                                item_required.append(item_key)
                properties[key] = {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": item_properties,
                        "required": item_required,
                        "additionalProperties": False,
                    },
                }
            else:
                properties[key] = {"type": "array", "items": {"type": "integer"}}
        else:
            properties[key] = _field_type(str(template), key)
    return properties, required


def derive_output_schema(semantic_outputs: dict[str, Any]) -> dict[str, Any]:
    """The complete model-output schema (status + semantic or status + reason)."""
    semantic_props, semantic_required = _semantic_properties(semantic_outputs)
    semantic_schema = {
        "type": "object",
        "properties": semantic_props,
        "required": semantic_required,
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "status": {"enum": ["OK", "ABSTAIN"]},
            "semantic": semantic_schema,
            "reason": {"type": "string"},
        },
        "required": ["status"],
        "additionalProperties": False,
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "status": {"const": "OK"},
                    "semantic": semantic_schema,
                    "reason": {"type": "string"},
                },
                "required": ["status", "semantic"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {"status": {"const": "ABSTAIN"}, "reason": {"type": "string", "minLength": 1}},
                "required": ["status", "reason"],
                "additionalProperties": False,
            },
        ],
    }


def full_output_schema(semantic_outputs: dict[str, Any]) -> dict[str, Any]:
    return derive_output_schema(semantic_outputs)
