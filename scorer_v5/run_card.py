#!/usr/bin/env python3
"""Single-card formal runner.

Executes the full v5 pipeline for one (book, metric, rep) card in strict formal
mode: sidecar → prompt → parse (no repair) → 4-layer validate → derive → score
→ provenance. The caller (staging builder) mounts only this card's canonical
text, the frozen specs, and this card's output directory — never the ledger,
split tables, or any label data.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

from scorer_v5.preprocessing.canonicalize import text_sha256
from scorer_v5.preprocessing.sidecar import build_sidecar
from scorer_v5.provenance.registry import ProvenanceRecord, ProvenanceRegistry, utc_now_iso
from scorer_v5.runtime.parsing import parse_model_output
from scorer_v5.runtime.prompts import build_prompt, prompt_sha256
from scorer_v5.runtime.quote_bind import bind_evidence_spans
from scorer_v5.runtime.specs import combined_spec_hash, load_metric_spec
from scorer_v5.runtime.validation import validate_model_output
from scorer_v5.scoring.engine import compute_score

def run_card(
    *,
    run_id: str,
    book_id: str,
    metric_id: str,
    rep: int,
    text: str,
    raw_model_output: str,
    provenance: ProvenanceRegistry,
    specs_dir: Path,
    provider: str,
    model: str,
    model_params: dict,
) -> dict:
    from hashlib import sha256 as _sha256
    spec = load_metric_spec(metric_id, specs_dir=specs_dir)
    canonical_text, sidecar, offsets = build_sidecar(text)
    prompt = build_prompt(spec, canonical_text)
    parsed = parse_model_output(raw_model_output, formal=True, spec=spec)
    wire_output = None
    bound_semantic = None
    if parsed.is_valid_json and parsed.value and parsed.value.get("status") == "OK":
        # Preserve the model's raw wire output (integer span ids) untouched.
        wire_output = copy.deepcopy(parsed.value)
        semantic = parsed.value.get("semantic")
        if isinstance(semantic, dict):
            bound_semantic, span_index = bind_evidence_spans(semantic, canonical_text)
            # parsed_output (used by V2/scoring) sees the bound semantic; the
            # wire copy above keeps the model's original integers.
            parsed.value["semantic"] = bound_semantic
    validation = validate_model_output(parsed, spec, canonical_text, content_offsets=offsets)
    scored = compute_score(spec, validation, canonical_text, sidecar)

    record = ProvenanceRecord(
        run_id=run_id,
        book_id=book_id,
        metric_id=metric_id,
        rep=rep,
        model=model,
        provider=provider,
        model_params=model_params,
        prompt_hash=prompt_sha256(prompt),
        spec_hash=combined_spec_hash(specs_dir=specs_dir),
        text_hash=text_sha256(canonical_text),
        sidecar_hash=sidecar.sha256(),
        raw_stdout_hash=_sha256(raw_model_output.encode("utf-8")).hexdigest(),
        wire_output=wire_output,
        bound_semantic=bound_semantic,
        parsed_output=parsed.value,
        validator_result=validation.as_dict(),
        final_score=scored.score,
        timestamp=utc_now_iso(),
    )
    provenance.append(record)
    return {
        "metric_id": metric_id,
        "score": scored.score,
        "abstained": scored.abstained,
        "continuous": scored.continuous,
        "validation": validation.as_dict(),
        "error": scored.error,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="v5 formal single-card runner")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--book-id", required=True)
    parser.add_argument("--metric", required=True)
    parser.add_argument("--rep", type=int, required=True)
    parser.add_argument("--text", required=True, help="path to canonical text file")
    parser.add_argument("--model-output", required=True, help="path to raw model stdout")
    parser.add_argument("--provenance", required=True, help="output provenance JSON path")
    parser.add_argument("--specs-dir", default="scorer_v5/specs")
    parser.add_argument("--provider", required=True, help="actual provider used to generate --model-output")
    parser.add_argument("--model", required=True, help="actual model used to generate --model-output")
    parser.add_argument("--model-params-json", default="{}", help="actual generation params as JSON object")
    args = parser.parse_args(argv)

    text = Path(args.text).read_text(encoding="utf-8")
    raw = Path(args.model_output).read_text(encoding="utf-8")
    try:
        model_params = json.loads(args.model_params_json)
        if not isinstance(model_params, dict):
            raise ValueError
    except Exception:
        raise SystemExit("--model-params-json must be a JSON object")
    registry = ProvenanceRegistry(args.provenance)
    result = run_card(
        run_id=args.run_id,
        book_id=args.book_id,
        metric_id=args.metric,
        rep=args.rep,
        text=text,
        raw_model_output=raw,
        provenance=registry,
        specs_dir=Path(args.specs_dir),
        provider=args.provider,
        model=args.model,
        model_params=model_params,
    )
    registry.save()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
