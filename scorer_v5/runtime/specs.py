"""Read-only access to the sole active metric-rule source."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPECS_DIR = PACKAGE_ROOT / "specs"


@dataclass(frozen=True)
class MetricSpec:
    metric_id: str
    version: str
    data: dict[str, Any]
    sha256: str
    path: Path

    @property
    def semantic_outputs(self) -> dict[str, Any]:
        return self.data["semantic_outputs"]

    @property
    def allowed_scores(self) -> frozenset[int]:
        return frozenset(self.data["score_scale"]["allowed"])


def load_metric_spec(metric_id: str, *, specs_dir: Path = DEFAULT_SPECS_DIR) -> MetricSpec:
    path = specs_dir / f"{metric_id}.yaml"
    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    if not isinstance(data, dict) or data.get("metric_id") != metric_id:
        raise ValueError(f"invalid metric spec: {path}")
    return MetricSpec(metric_id, data["version"], data, sha256(raw).hexdigest(), path)


def spec_hash_manifest(*, specs_dir: Path = DEFAULT_SPECS_DIR) -> dict[str, str]:
    """Compute live hashes instead of trusting a stale generated manifest."""
    return {path.stem: sha256(path.read_bytes()).hexdigest() for path in sorted(specs_dir.glob("*.yaml"))}


def combined_spec_hash(*, specs_dir: Path = DEFAULT_SPECS_DIR) -> str:
    pairs = spec_hash_manifest(specs_dir=specs_dir)
    serialized = "".join(f"{metric_id}:{digest}\n" for metric_id, digest in pairs.items())
    return sha256(serialized.encode("ascii")).hexdigest()
