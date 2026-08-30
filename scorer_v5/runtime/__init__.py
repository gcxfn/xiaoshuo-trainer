"""Strict v5 prompt, validation, scoring, and provenance runtime."""
from .parsing import DuplicateKeyError, ParsedModelOutput, parse_model_output
from .prompts import build_prompt
from .specs import MetricSpec, combined_spec_hash, load_metric_spec, spec_hash_manifest

__all__ = [
    "DuplicateKeyError",
    "MetricSpec",
    "ParsedModelOutput",
    "build_prompt",
    "combined_spec_hash",
    "load_metric_spec",
    "parse_model_output",
    "spec_hash_manifest",
]
