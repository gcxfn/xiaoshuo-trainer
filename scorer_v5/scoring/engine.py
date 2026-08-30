"""Deterministic scoring orchestration: semantic facts → derived → ordinal."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..preprocessing.sidecar import TextSidecar
from ..runtime.specs import MetricSpec
from ..runtime.validation import ValidationResult
from .derived import DerivedContext
from .extractors import derive_context
from .ordinal import score_from_mapping

SCORING_CODE_VERSION = "v5.1-scoring-1"


@dataclass(frozen=True)
class ScoreResult:
    metric_id: str
    score: int | None
    abstained: bool
    continuous: dict[str, Any]
    derived: dict[str, Any]
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "score": self.score,
            "abstained": self.abstained,
            "continuous": self.continuous,
            "derived": self.derived,
            "error": self.error,
        }


def compute_score(
    spec: MetricSpec,
    validation: ValidationResult,
    canonical_text: str,
    sidecar: TextSidecar,
) -> ScoreResult:
    """Compute the final score strictly from validated semantic facts.

    If the model ABSTAINed, the result is abstained with no score; ABSTAIN is
    never converted to 0. If validation rejected the semantic facts, no score
    is produced (formal runs treat this as FAIL, never a repair).
    """
    if validation.is_abstain:
        return ScoreResult(spec.metric_id, None, True, {}, {}, None)
    if not validation.accepted_semantic_facts:
        issues = [issue.message for issue in validation.issues]
        return ScoreResult(spec.metric_id, None, False, {}, {}, "; ".join(issues) or "validation failed")
    ctx = derive_context(spec, validation, canonical_text, sidecar)
    try:
        score = score_from_mapping(spec, ctx)
    except (KeyError, ValueError) as exc:
        return ScoreResult(spec.metric_id, None, False, {}, ctx.values, str(exc))
    continuous = _continuous_values(spec, ctx)
    return ScoreResult(spec.metric_id, score, False, continuous, ctx.values, None)


def _continuous_values(spec: MetricSpec, ctx: DerivedContext) -> dict[str, Any]:
    """Always preserve raw continuous values alongside the ordinal score."""
    out: dict[str, Any] = {}
    for key in ("F", "N", "K", "q", "position_ratio", "invalid_ratio", "x1_ratio", "x2_ratio", "criterion_count", "item_count"):
        if key in ctx.values:
            out[key] = ctx.values[key]
    return out
