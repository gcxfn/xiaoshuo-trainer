#!/usr/bin/env python3
"""Preflight + provenance + formal-rate smoke test."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scorer_v5.preprocessing.sidecar import build_sidecar
from scorer_v5.preflight import run_preflight
from scorer_v5.provenance.registry import ProvenanceRecord, ProvenanceRegistry, utc_now_iso
from scorer_v5.runtime.parsing import parse_model_output
from scorer_v5.runtime.prompts import build_prompt, prompt_sha256
from scorer_v5.runtime.specs import load_metric_spec, combined_spec_hash, spec_hash_manifest
from scorer_v5.runtime.validation import validate_model_output
from scorer_v5.scoring.engine import compute_score
from scorer_v5.preprocessing.canonicalize import text_sha256

ROOT = Path(__file__).resolve().parents[2]
TEXT = "门卫拦住了我。\n\"按规矩，票不能退。\"\n我把收据拍在桌上。\n"
CT, SIDECAR, OFFSETS = build_sidecar(TEXT)


def main() -> int:
    failures = []

    # Preflight must PASS against the current experiment config and specs
    pre = run_preflight(canonical_text=CT, config_path=ROOT / "scorer_v5/config/formal_model.yaml", specs_dir=ROOT / "scorer_v5/specs")
    print("preflight:", pre.ok, pre.errors)
    if not pre.ok:
        failures.append(f"preflight failed: {pre.errors}")

    # Preflight must FAIL on declared config-version mismatch
    broken = run_preflight(
        canonical_text=CT,
        config_path=ROOT / "scorer_v5/config/formal_model.yaml",
        specs_dir=ROOT / "scorer_v5/specs",
        expected_config_version="wrong",
    )
    print("preflight mismatch:", broken.ok, broken.errors[:1])
    if broken.ok:
        failures.append("preflight must fail on config version mismatch")

    # Provenance record round-trip
    spec = load_metric_spec("B01")
    prompt = build_prompt(spec, CT)
    raw = json.dumps({"status": "ABSTAIN", "reason": "无法确认事件边界"}, ensure_ascii=False)
    parsed = parse_model_output(raw, formal=True, spec=spec)
    result = validate_model_output(parsed, spec, CT, content_offsets=OFFSETS)
    scored = compute_score(spec, result, CT, SIDECAR)
    record = ProvenanceRecord(
        run_id="smoke-1",
        book_id="276",
        metric_id="B01",
        rep=1,
        model="deepseek/deepseek-v4-flash",
        provider="commandcode",
        model_params={"temperature": 0.0, "top_p": 1.0, "seed": 0, "reasoning_mode": "low"},
        prompt_hash=prompt_sha256(prompt),
        spec_hash=combined_spec_hash(specs_dir=ROOT / "scorer_v5/specs"),
        text_hash=text_sha256(CT),
        sidecar_hash=SIDECAR.sha256(),
        raw_stdout_hash=None,
        wire_output=parsed.value,
        bound_semantic=None,
        parsed_output=parsed.value,
        validator_result=result.as_dict(),
        final_score=scored.score,
        timestamp=utc_now_iso(),
    )
    registry = ProvenanceRegistry(ROOT / "scorer_v5/tests/_tmp_provenance.json")
    registry.append(record)
    registry.save()
    loaded = json.loads((ROOT / "scorer_v5/tests/_tmp_provenance.json").read_text(encoding="utf-8"))
    print("provenance records:", len(loaded["records"]), "score:", loaded["records"][0]["final_score"])
    if len(loaded["records"]) != 1 or loaded["records"][0]["final_score"] is not None:
        failures.append("provenance round-trip broken")
    (ROOT / "scorer_v5/tests/_tmp_provenance.json").unlink(missing_ok=True)

    # Regression (AC4): run_card must preserve the model's raw wire integers
    # in ProvenanceRecord.wire_output, while bound_semantic holds the exact
    # span bodies. The wire ids must NOT be overwritten by bound text.
    from scorer_v5.run_card import run_card
    raw_ok = json.dumps({
        "status": "OK",
        "semantic": {
            "candidates": [{
                "event_quote": 1,
                "is_external_event": True,
                "same_scene_action": False,
                "action_quote": None,
                "qualifies": True,
            }],
        },
    }, ensure_ascii=False)
    card_registry = ProvenanceRegistry(ROOT / "scorer_v5/tests/_tmp_provenance_card.json")
    run_card(
        run_id="smoke-wire",
        book_id="276",
        metric_id="B01",
        rep=1,
        text=TEXT,
        raw_model_output=raw_ok,
        provenance=card_registry,
        specs_dir=ROOT / "scorer_v5/specs",
        provider="commandcode",
        model="deepseek/deepseek-v4-flash",
        model_params={"temperature": 0.0, "top_p": 1.0, "seed": 0, "reasoning_mode": "low"},
    )
    card_registry.save()
    loaded_card = json.loads((ROOT / "scorer_v5/tests/_tmp_provenance_card.json").read_text(encoding="utf-8"))
    rec = loaded_card["records"][0]
    wire = rec.get("wire_output") or {}
    bound = rec.get("bound_semantic") or {}
    wire_quote = (wire.get("semantic") or {}).get("candidates", [{}])[0].get("event_quote")
    bound_quote = (bound.get("candidates") or [{}])[0].get("event_quote")
    if wire_quote != 1:
        failures.append(f"wire_output must keep integer span id, got {wire_quote!r}")
    if not (isinstance(bound_quote, str) and bound_quote):
        failures.append(f"bound_semantic must hold exact span body, got {bound_quote!r}")
    # Third reference: parsed_output must carry the BOUND semantic (used by
    # V2/scoring), distinct from wire_output's raw integers.
    parsed_out = rec.get("parsed_output") or {}
    parsed_quote = (parsed_out.get("semantic") or {}).get("candidates", [{}])[0].get("event_quote")
    if parsed_quote != bound_quote:
        failures.append(
            f"parsed_output must use bound semantic, got {parsed_quote!r}, expected {bound_quote!r}"
        )
    (ROOT / "scorer_v5/tests/_tmp_provenance_card.json").unlink(missing_ok=True)

    # Spec hash manifest integrity: spec_hashes.json must match live files
    manifest = json.loads((ROOT / "scorer_v5/specs/spec_hashes.json").read_text(encoding="utf-8"))
    live = spec_hash_manifest(specs_dir=ROOT / "scorer_v5/specs")
    mismatched = [mid for mid in live if manifest.get("specs_sha256", {}).get(mid) != live[mid]]
    print("spec hash mismatches:", mismatched)
    if mismatched:
        failures.append(f"spec_hashes.json out of date for {mismatched}")
    spec_versions = {mid: load_metric_spec(mid).version for mid in live}
    unique_spec_versions = set(spec_versions.values())
    if len(unique_spec_versions) != 1:
        failures.append(f"mixed active spec versions: {sorted(unique_spec_versions)}")
    elif manifest.get("schema") not in unique_spec_versions:
        failures.append(
            f"spec_hashes.json schema {manifest.get('schema')!r} != unique spec version {unique_spec_versions}"
        )

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
