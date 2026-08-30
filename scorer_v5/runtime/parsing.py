"""Strict model-output parsing; formal mode never repairs JSON."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Literal

from .output_schema import derive_output_schema
from .specs import MetricSpec


class DuplicateKeyError(ValueError):
    pass


class StrictObject(dict):
    """Marker type used only while rejecting duplicate JSON object keys."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> StrictObject:
    result = StrictObject()
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


@dataclass(frozen=True)
class ParsedModelOutput:
    raw: str
    value: dict[str, Any] | None
    parse_status: Literal["OK", "FAIL_PARSE", "FAIL_DUPLICATE_KEY", "FAIL_SCHEMA"]
    error: str | None
    repair_attempted: bool = False

    @property
    def is_valid_json(self) -> bool:
        return self.parse_status == "OK"


def unwrap_complete_json_fence(raw: str) -> str:
    """If *raw* is exactly one complete markdown JSON fence, return the inner
    text unchanged. Otherwise return *raw* unchanged.

    Allowed envelopes (leading/trailing whitespace only)::

        ```json\\n{...}\\n```
        ```\\n{...}\\n```

    Not unwrap (caller then json.loads the original, typically FAIL_PARSE):
    extra prose before/after, truncated fence, inner `````, non-json language
    tag, multiple fences. This is envelope stripping, not JSON repair.
    """
    if not isinstance(raw, str):
        return raw
    s = raw.strip()
    if not s.startswith("```"):
        return raw
    first_nl = s.find("\n")
    if first_nl < 0:
        return raw
    lang = s[3:first_nl].strip().lower()
    if lang not in ("", "json"):
        return raw
    rest = s[first_nl + 1 :]
    close = rest.rfind("```")
    if close < 0:
        return raw
    inner = rest[:close]
    after = rest[close + 3 :]
    if after.strip() or "```" in inner:
        return raw
    return inner


def parse_model_output(raw: str, *, formal: bool, spec: MetricSpec | None = None) -> ParsedModelOutput:
    """Parse and schema-check exactly one JSON object.

    Formal mode never repairs JSON: duplicate keys and schema violations are
    hard failures (``FAIL_DUPLICATE_KEY`` / ``FAIL_SCHEMA``). A complete
    single markdown JSON code fence may be unwrapped first; the inner bytes
    are not edited. The schema is derived from the spec's
    ``semantic_outputs`` so prompt/validator/extractor share one definition
    (Step 12.5 Step 2).
    """
    if not isinstance(raw, str):
        raise TypeError("raw model output must be str")
    payload = unwrap_complete_json_fence(raw)
    try:
        value = json.loads(payload, object_pairs_hook=_reject_duplicate_keys)
    except DuplicateKeyError as exc:
        return ParsedModelOutput(raw, None, "FAIL_DUPLICATE_KEY", str(exc))
    except (json.JSONDecodeError, TypeError) as exc:
        return ParsedModelOutput(raw, None, "FAIL_PARSE", str(exc))
    if not isinstance(value, dict):
        return ParsedModelOutput(raw, None, "FAIL_PARSE", "top-level JSON value must be an object")

    if spec is not None:
        schema = derive_output_schema(spec.semantic_outputs)
        error = _validate_against_schema(value, schema)
        if error:
            return ParsedModelOutput(raw, None, "FAIL_SCHEMA", error)

    return ParsedModelOutput(raw, dict(value), "OK", None)


def _validate_against_schema(value: Any, schema: dict[str, Any], path: str = "$") -> str | None:
    """Hand-rolled JSON-Schema subset check (no external dependency in the
    scoring path; jsonschema is only used by tests)."""
    # oneOf with status consts: OK requires semantic, ABSTAIN requires reason.
    if "oneOf" in schema:
        status = value.get("status") if isinstance(value, dict) else None
        if status == "OK":
            branch = next(b for b in schema["oneOf"] if b["properties"]["status"]["const"] == "OK")
            return _validate_against_schema(value, branch, path)
        if status == "ABSTAIN":
            branch = next(b for b in schema["oneOf"] if b["properties"]["status"]["const"] == "ABSTAIN")
            return _validate_against_schema(value, branch, path)
        return f"{path}: status must be OK or ABSTAIN"

    if schema.get("type") == "object" or (schema.get("properties") or schema.get("required")):
        required = schema.get("required", [])
        missing = [k for k in required if k not in value]
        if missing:
            return f"{path}: missing required fields {missing}"
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(props)
            if extra:
                return f"{path}: unexpected fields {sorted(extra)}"
        for key, sub in props.items():
            if key in value:
                err = _validate_against_schema(value[key], sub, f"{path}.{key}")
                if err:
                    return err
        return None
    return _check_node(value, schema, path)


def _check_node(value: Any, schema: dict[str, Any], path: str) -> str | None:
    t = schema.get("type")
    if isinstance(t, list):
        if not any(_type_matches(value, tt) for tt in t):
            return f"{path}: expected type {t}, got {type(value).__name__}"
    elif t and not _type_matches(value, t):
        return f"{path}: expected type {t}, got {type(value).__name__}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path}: value {value!r} not in {schema['enum']}"
    if t == "object":
        # required 检查（数组项走 _check_node，漏关键字段必须 FAIL_SCHEMA）
        required = schema.get("required", [])
        missing = [k for k in required if k not in value]
        if missing:
            return f"{path}: missing required fields {missing}"
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(props)
            if extra:
                return f"{path}: unexpected fields {sorted(extra)}"
        for key, sub in props.items():
            if key in value:
                err = _check_node(value[key], sub, f"{path}.{key}")
                if err:
                    return err
    elif t == "array":
        items = schema.get("items", {})
        for i, item in enumerate(value):
            err = _check_node(item, items, f"{path}[{i}]")
            if err:
                return err
    return None


def _type_matches(value: Any, t: str) -> bool:
    if t == "string":
        return isinstance(value, str)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "array":
        return isinstance(value, list)
    if t == "object":
        return isinstance(value, dict)
    if t == "null":
        return value is None
    return False
