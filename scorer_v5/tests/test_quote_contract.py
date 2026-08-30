#!/usr/bin/env python3
"""draft-9: generated prompts must carry span-id wire quote-output rules."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scorer_v5.runtime.prompts import build_prompt
from scorer_v5.runtime.specs import load_metric_spec

METRICS = [
    "B01", "B02", "B03", "C01", "B08", "B09", "B16", "B23", "B30", "B34",
    "B36", "C22", "N3", "N6", "B31", "B33", "C14", "B18", "N7",
]

UNIVERSAL = "通用 *_quote 输出规则"
B01_RULE = "B01 短引文约束"
B33_RULE = "B33 短引文约束"
B36_RULE = "B36 短引文约束"
REQUIRED_BITS = (
    "canonical text 连续逐字子串",
    "优先最短且足以证明判定的片段",
    "禁止跨位置拼接",
    "禁止用 …… 或 ... 省略",
    "禁止改写、概括、纠正标点或更换中文/英文引号",
    "必须单行、禁止换行",
    "分放不同 quote 字段或数组项",
)
WIRE_BITS = (
    "证据绑定（程序填原文）",
    "禁止输出引文字符串",
    "S001",
    "S012 → 12",
    "evidence span 的整数编号",
)


def main() -> int:
    failures: list[str] = []
    for mid in METRICS:
        spec = load_metric_spec(mid)
        if spec.version != "spec-v5.1-draft-9":
            failures.append(f"{mid}: version {spec.version!r} != spec-v5.1-draft-9")
        er = spec.data.get("evidence_rule") or ""
        if UNIVERSAL not in er:
            failures.append(f"{mid}: spec evidence_rule missing universal quote contract")
        for bit in REQUIRED_BITS:
            if bit not in er:
                failures.append(f"{mid}: spec evidence_rule missing {bit!r}")
        prompt = build_prompt(spec, "门卫拦住了我。")
        if UNIVERSAL not in prompt:
            failures.append(f"{mid}: generated prompt missing universal quote contract")
        for bit in WIRE_BITS:
            if bit not in prompt:
                failures.append(f"{mid}: generated prompt missing wire bit {bit!r}")
        # Issue #3: no leftover "输出逐字引文" instruction in the wire section.
        if "输出逐字引文" in prompt or "给出逐字引文" in prompt:
            failures.append(f"{mid}: prompt still asks model to emit verbatim quotes")
        for bit in REQUIRED_BITS:
            if bit not in prompt:
                failures.append(f"{mid}: generated prompt missing {bit!r}")
        if mid == "B01":
            if B01_RULE not in er or B01_RULE not in prompt:
                failures.append("B01 missing metric-level short-quote constraint in spec/prompt")
        if mid == "B33":
            if B33_RULE not in er or B33_RULE not in prompt:
                failures.append("B33 missing metric-level short-quote constraint in spec/prompt")
        if mid == "B36":
            if B36_RULE not in er or B36_RULE not in prompt:
                failures.append("B36 missing metric-level short-quote constraint in spec/prompt")
        if mid not in ("B01", "B33", "B36"):
            if B01_RULE in prompt or B33_RULE in prompt or B36_RULE in prompt:
                failures.append(f"{mid}: must not carry B01/B33/B36-specific quote constraints")

    specs_dir = Path(__file__).resolve().parents[1] / "specs"
    manifest = json.loads((specs_dir / "spec_hashes.json").read_text(encoding="utf-8"))
    expected_ver = "spec-v5.1-draft-9"
    if manifest.get("schema") != expected_ver:
        failures.append(
            f"spec_hashes.json schema {manifest.get('schema')!r} != {expected_ver}"
        )
    for mid in METRICS:
        yaml_path = specs_dir / f"{mid}.yaml"
        live = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
        stored = (manifest.get("specs_sha256") or {}).get(mid)
        if stored != live:
            failures.append(f"spec_hashes.json mismatch {mid}")

    if failures:
        print("FAIL:")
        for f in failures:
            print("  -", f)
        return 1
    print(f"PASS: {len(METRICS)} specs and generated prompts carry span-id wire contract")
    return 0


if __name__ == "__main__":
    sys.exit(main())
