"""Four-layer v5 output validation with evidence-first failure semantics."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from ..preprocessing.offsets import QuoteLocation, locate_quote
from .parsing import ParsedModelOutput
from .specs import MetricSpec

_FORBIDDEN_MODEL_KEYS = frozenset({"score", "final_score", "offset", "l", "k", "f", "ratio", "比例"})


@dataclass(frozen=True)
class ValidationIssue:
    layer: str
    path: str
    message: str


@dataclass
class ValidationResult:
    parsed: ParsedModelOutput
    issues: list[ValidationIssue] = field(default_factory=list)
    evidence_locations: dict[str, QuoteLocation] = field(default_factory=dict)

    @property
    def v1_schema_ok(self) -> bool:
        return not any(issue.layer == "V1" for issue in self.issues)

    @property
    def v2_evidence_ok(self) -> bool:
        return not any(issue.layer == "V2" for issue in self.issues)

    @property
    def v3_logic_ok(self) -> bool:
        return not any(issue.layer == "V3" for issue in self.issues)

    @property
    def is_abstain(self) -> bool:
        return self.parsed.value is not None and self.parsed.value.get("status") == "ABSTAIN"

    @property
    def accepted_semantic_facts(self) -> bool:
        return self.parsed.is_valid_json and self.v1_schema_ok and self.v2_evidence_ok and self.v3_logic_ok

    @property
    def outcome(self) -> str:
        """Explicit outcome: SCHEMA_FAIL / EVIDENCE_FAIL / LOGIC_FAIL / ABSTAIN / OK."""
        if self.parsed.parse_status != "OK":
            return self.parsed.parse_status if self.parsed.parse_status.startswith("FAIL") else "SCHEMA_FAIL"
        if self.is_abstain:
            return "ABSTAIN"
        if not self.v1_schema_ok:
            return "SCHEMA_FAIL"
        if not self.v2_evidence_ok:
            return "EVIDENCE_FAIL"
        if not self.v3_logic_ok:
            return "LOGIC_FAIL"
        return "OK"

    def as_dict(self) -> dict[str, Any]:
        return {
            "parse_status": self.parsed.parse_status,
            "v1_schema_ok": self.v1_schema_ok,
            "v2_evidence_ok": self.v2_evidence_ok,
            "v3_logic_ok": self.v3_logic_ok,
            "outcome": self.outcome,
            "accepted_semantic_facts": self.accepted_semantic_facts,
            "is_abstain": self.is_abstain,
            "issues": [issue.__dict__ for issue in self.issues],
            "evidence_locations": {path: location.__dict__ for path, location in self.evidence_locations.items()},
        }


def _contains_forbidden_key(value: Any, path: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).casefold()
            if normalized in _FORBIDDEN_MODEL_KEYS or normalized.endswith("_offset"):
                yield path, str(key)
            yield from _contains_forbidden_key(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _contains_forbidden_key(nested, f"{path}[{index}]")


def _check_semantic_shape(value: Any, template: Any, path: str, issues: list[ValidationIssue]) -> None:
    if isinstance(template, list):
        if not isinstance(value, list):
            issues.append(ValidationIssue("V1", path, "must be an array"))
            return
        if len(template) == 1 and isinstance(template[0], dict):
            item_template = template[0]
            for index, item in enumerate(value):
                if not isinstance(item, dict):
                    issues.append(ValidationIssue("V1", f"{path}[{index}]", "must be an object"))
                    continue
                expected = set(item_template)
                actual = set(item)
                if missing := expected - actual:
                    issues.append(ValidationIssue("V1", f"{path}[{index}]", f"missing fields: {sorted(missing)}"))
                if extra := actual - expected:
                    issues.append(ValidationIssue("V1", f"{path}[{index}]", f"unexpected fields: {sorted(extra)}"))
        return
    # Scalar descriptions in the active YAML define semantic meaning, not a
    # JSON primitive. Preserve that flexibility while still rejecting missing
    # fields at the enclosing object.


def _iter_evidence(value: Any, path: str = "$", anchor: str | None = None) -> Iterable[tuple[str, str, str | None]]:
    if isinstance(value, dict):
        local_anchor = value.get("nearby_anchor") if isinstance(value.get("nearby_anchor"), str) else anchor
        for key, nested in value.items():
            nested_path = f"{path}.{key}"
            lowered = key.casefold()
            # 只把真正承载引文的字段当 evidence 定位：字段名含 quote；或含 evidence
            # 但排除语义分类值（primary_evidence='fact'、extreme_word_quotes 裸词）
            is_quote = "quote" in lowered and lowered != "extreme_word_quotes"
            if is_quote:
                if isinstance(nested, str):
                    yield nested_path, nested, local_anchor
                elif isinstance(nested, list):
                    for index, item in enumerate(nested):
                        if isinstance(item, str):
                            yield f"{nested_path}[{index}]", item, local_anchor
                elif nested is not None and not isinstance(nested, (dict, list)):
                    yield nested_path, "", local_anchor
            yield from _iter_evidence(nested, nested_path, local_anchor)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _iter_evidence(nested, f"{path}[{index}]", anchor)


def validate_model_output(
    parsed: ParsedModelOutput,
    spec: MetricSpec,
    canonical_text: str,
    *,
    content_offsets: list[int],
) -> ValidationResult:
    result = ValidationResult(parsed)
    if not parsed.is_valid_json:
        result.issues.append(ValidationIssue("V1", "$", parsed.error or parsed.parse_status))
        return result
    assert parsed.value is not None
    value = parsed.value
    status = value.get("status")
    if status not in {"OK", "ABSTAIN"}:
        result.issues.append(ValidationIssue("V1", "$.status", "must be OK or ABSTAIN"))
        return result
    for path, key in _contains_forbidden_key(value):
        result.issues.append(ValidationIssue("V1", path, f"model must not output deterministic field {key!r}"))
    if status == "ABSTAIN":
        if set(value) != {"status", "reason"} or not isinstance(value.get("reason"), str) or not value["reason"].strip():
            result.issues.append(ValidationIssue("V1", "$", "ABSTAIN requires exactly non-empty status and reason"))
        return result
    if status == "OK":
        extra = set(value) - {"status", "semantic", "reason"}
        if extra or "semantic" not in value or not isinstance(value.get("semantic"), dict):
            result.issues.append(ValidationIssue("V1", "$", "OK requires status and semantic; optional reason only"))
            return result
        if "reason" in value and (not isinstance(value.get("reason"), str) or not str(value["reason"]).strip()):
            result.issues.append(ValidationIssue("V1", "$.reason", "optional reason must be a non-empty string"))
            return result
    semantic = value["semantic"]
    # *note / selection_note / boundary_note keys are prompt guidance, not
    # model-output fields; the model must only fill the LLM-output fields.
    _GUIDANCE_KEYS = ("_note", "selection_note", "boundary_note", "exclude_notes", "criteria")
    expected = {key for key in spec.semantic_outputs if not str(key).endswith(_GUIDANCE_KEYS)}
    if missing := expected - set(semantic):
        result.issues.append(ValidationIssue("V1", "$.semantic", f"missing fields: {sorted(missing)}"))
    if extra := set(semantic) - expected:
        result.issues.append(ValidationIssue("V1", "$.semantic", f"unexpected fields: {sorted(extra)}"))
    for key in expected & set(semantic):
        _check_semantic_shape(semantic[key], spec.semantic_outputs[key], f"$.semantic.{key}", result.issues)
    if not result.v1_schema_ok:
        return result
    for path, quote, anchor in _iter_evidence(semantic, "$.semantic"):
        if not quote.strip():
            result.issues.append(ValidationIssue("V2", path, "evidence quote must be a non-empty string"))
            continue
        try:
            location = locate_quote(canonical_text, quote, nearby_anchor=anchor, offsets=content_offsets)
        except ValueError as exc:
            result.issues.append(ValidationIssue("V2", path, str(exc)))
            continue
        if location is None:
            result.issues.append(ValidationIssue("V2", path, "quote is absent from canonical text"))
        else:
            result.evidence_locations[path] = location
    # V3 semantic contradictions: item_hits/criteria booleans must be supported
    # by at least one located quote in the same object subtree (else the claim
    # is a bare assertion with no observable evidence).
    for path, value in _walk_objects(semantic, "$.semantic"):
        if not isinstance(value, dict):
            continue
        claims_true = value.get("qualifies") is True
        hits = value.get("item_hits")
        if isinstance(hits, list):
            claims_true = claims_true or any(h is True for h in hits)
        if claims_true:
            subtree_has_evidence = any(
                loc_path.startswith(path + ".") or loc_path == path
                for loc_path in result.evidence_locations
            )
            if not subtree_has_evidence:
                result.issues.append(
                    ValidationIssue("V3", path, "semantic claim (qualifies/item_hits=true) has no located quote evidence in subtree")
                )
    return result


def _walk_objects(value: Any, path: str) -> Iterable[tuple[str, dict[str, Any]]]:
    if isinstance(value, dict):
        yield path, value
        for key, nested in value.items():
            yield from _walk_objects(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _walk_objects(nested, f"{path}[{index}]")
