"""Provenance registry: every score is traceable to its exact inputs."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProvenanceRecord:
    run_id: str
    book_id: str
    metric_id: str
    rep: int
    model: str
    provider: str
    model_params: dict[str, Any]
    prompt_hash: str
    spec_hash: str
    text_hash: str
    sidecar_hash: str
    raw_stdout_hash: str | None
    wire_output: dict[str, Any] | None
    bound_semantic: dict[str, Any] | None
    parsed_output: dict[str, Any] | None
    validator_result: dict[str, Any]
    final_score: int | None
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProvenanceRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.records: list[ProvenanceRecord] = []
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                for item in payload.get("records", []):
                    if isinstance(item, dict):
                        self.records.append(ProvenanceRecord(**item))
            except Exception:
                # 旧/损坏 registry 不静默合并；正式调用方可换新路径。
                self.records = []

    def append(self, record: ProvenanceRecord) -> None:
        self.records.append(record)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": "v5.1-provenance-1", "records": [r.to_dict() for r in self.records]}
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
