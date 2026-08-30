"""Derived-feature context: validated semantic facts + sidecar facts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DerivedContext:
    """Flat key/value store fed by the per-metric extractor.

    The ordinal predicates read a small, stable contract:
    - count metrics: ``criterion_count`` (+ per-item booleans), ``item_count``
    - veto metrics: ``veto_found``, ``y_veto``, ``x1_ratio``/``x2_ratio``
    - position metrics: ``q``, ``position_ratio``, ``first_round_le_500``,
      ``same_lineage``, ``qualified``, ``paragraph_ok``, ``action_in_scene``
    - density metrics: ``F``
    """

    values: dict[str, Any] = field(default_factory=dict)

    def set(self, key: str, value: Any) -> None:
        self.values[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)
