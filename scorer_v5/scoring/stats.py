"""Formal-run statistics required by Step 10.

A formal run must report, never repair:
- raw_valid_json_rate
- schema_valid_rate   (V1)
- duplicate_key_rate
- evidence_valid_rate (V2)
- abstain_rate

ABSTAIN is counted separately and never converted to 0.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..runtime.validation import ValidationResult


@dataclass(frozen=True)
class FormalRates:
    n: int
    raw_valid_json_rate: float
    schema_valid_rate: float
    duplicate_key_rate: float
    evidence_valid_rate: float
    abstain_rate: float
    parse_fail_rate: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "n": self.n,
            "raw_valid_json_rate": round(self.raw_valid_json_rate, 4),
            "schema_valid_rate": round(self.schema_valid_rate, 4),
            "duplicate_key_rate": round(self.duplicate_key_rate, 4),
            "evidence_valid_rate": round(self.evidence_valid_rate, 4),
            "abstain_rate": round(self.abstain_rate, 4),
            "parse_fail_rate": round(self.parse_fail_rate, 4),
        }


def compute_formal_rates(results: Iterable[ValidationResult]) -> FormalRates:
    results = list(results)
    n = len(results)
    if n == 0:
        raise ValueError("no validation results to aggregate")

    raw_valid = sum(1 for r in results if r.parsed.is_valid_json)
    dup = sum(1 for r in results if r.parsed.parse_status == "FAIL_DUPLICATE_KEY")
    schema_ok = sum(1 for r in results if r.parsed.is_valid_json and r.v1_schema_ok)
    evidence_ok = sum(1 for r in results if r.parsed.is_valid_json and r.v1_schema_ok and r.v2_evidence_ok)
    abstain = sum(1 for r in results if r.is_abstain)

    return FormalRates(
        n=n,
        raw_valid_json_rate=raw_valid / n,
        schema_valid_rate=schema_ok / n,
        duplicate_key_rate=dup / n,
        evidence_valid_rate=evidence_ok / n,
        abstain_rate=abstain / n,
        parse_fail_rate=(n - raw_valid) / n,
    )
