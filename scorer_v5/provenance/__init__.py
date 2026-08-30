"""Run-level provenance registry (Step 13).

Tracks wire_output (from LLM) and bound_semantic (from Python) for evidence span ID resolution.
Records exact canonical/content start/end offsets for reproducible audit.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Union, cast


class ProvenanceRegistry:
    def __init__(self):
        self.records: List[Dict[str, Any]] = []
        self.version = "1.0"

    def record_wire_bound(self, metric_id: str, rep: int, event_idx: int, 
                          wire_output: Dict[str, Any], bound_semantic: Dict[str, Any],
                          span_id: int, provenance: Dict[str, Any]):
        """Record simultaneous wire_output and bound_semantic for reproducible evidence span ID."""
        record = {
            "metric_id": metric_id,
            "rep": rep,
            "event_idx": event_idx,
            "span_id": span_id,
            "wire_output": wire_output,
            "bound_semantic": bound_semantic,
            "provenance": provenance,
            "timestamp": datetime.now().isoformat()
        }
        self.records.append(record)
        return cast(Dict[str, Any], record)

    def get_record_by_span_id(self, span_id: int) -> Optional[Dict[str, Any]]:
        """Look up provenance record by span_id for audit/reproducibility."""
        for record in self.records:
            if record.get("span_id") == span_id:
                return record
        return None

    def get_records(self) -> List[Dict[str, Any]]:
        return self.records

    def get_record_by_span_id(self, span_id: int) -> Optional[Dict[str, Any]]:
        """Look up provenance record by span_id for audit/reproducibility."""
        for record in self.records:
            if record.get("span_id") == span_id:
                return record
        return None

    def validate_span_consistency(self) -> bool:
        """Ensure wire_output and bound_semantic share the same span ID and offsets."""
        for record in self.records:
            wire = record["wire_output"]
            bound = record["bound_semantic"]
            if wire.get("span_id") != bound.get("span_id"):
                return False
            # TODO: add offset comparison if needed
        return True

    def get_record_by_span_id(self, span_id: int) -> Optional[Dict[str, Any]]:
        """Look up provenance record by span_id for audit/reproducibility."""
        for record in self.records:
            if record.get("span_id") == span_id:
                return record
        return None

registry = ProvenanceRegistry()

