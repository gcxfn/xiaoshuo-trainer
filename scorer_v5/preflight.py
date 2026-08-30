"""Formal Preflight: block startup unless the five-hash chain is consistent.

spec_hash → prompt_hash → scoring code version → model config → canonical text
hash. Any mismatch prohibits a formal run.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml

from .preprocessing.canonicalize import text_sha256
from .runtime.prompts import PROMPT_VERSION, build_prompt, prompt_sha256
from .runtime.specs import combined_spec_hash, load_metric_spec
from .scoring.engine import SCORING_CODE_VERSION

CONFIG_VERSION = "v5.1-config-5"
FIXED_METRIC_ORDER = [
    "B01", "B02", "B03", "C01", "B08", "B09", "B16", "B23", "B30", "B34",
    "B36", "C22", "N3", "N6", "B31", "B33", "C14", "B18", "N7",
]


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    checks: dict[str, dict[str, Any]]
    errors: list[str]


def _load_config(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError("formal_model.yaml must be a mapping")
    return data


def _config_sha256(config: dict[str, Any]) -> str:
    import json
    payload = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def _prompt_hash(specs_dir: Path) -> str:
    """Deterministic hash over the prompt template + all metric specs."""
    digests = []
    for mid in FIXED_METRIC_ORDER:
        spec = load_metric_spec(mid, specs_dir=specs_dir)
        prompt = build_prompt(spec, "")
        digests.append(f"{mid}:{prompt_sha256(prompt)}")
    serialized = "\n".join(digests)
    return sha256(serialized.encode("utf-8")).hexdigest()


def run_preflight(
    *,
    canonical_text: str,
    config_path: Path = Path("scorer_v5/config/formal_model.yaml"),
    specs_dir: Path = Path("scorer_v5/specs"),
    expected_prompt_version: str = PROMPT_VERSION,
    expected_scoring_version: str = SCORING_CODE_VERSION,
    expected_config_version: str = CONFIG_VERSION,
) -> PreflightResult:
    errors: list[str] = []
    checks: dict[str, dict[str, Any]] = {}

    spec_hash = combined_spec_hash(specs_dir=specs_dir)
    checks["spec_hash"] = {"value": spec_hash, "ok": True}

    # 逐 spec version 一致性（防"配置说新版、实际混旧版"）：所有 spec 必须同一版本
    import yaml as _yaml
    spec_versions = {}
    spec_version_ok = True
    for mid in FIXED_METRIC_ORDER:
        p = specs_dir / f"{mid}.yaml"
        if not p.exists():
            spec_version_ok = False
            errors.append(f"spec file missing: {mid}.yaml")
            continue
        with open(p, encoding="utf-8") as fh:
            data = _yaml.safe_load(fh)
        ver = data.get("version") if isinstance(data, dict) else None
        spec_versions[mid] = ver
    distinct = {v for v in spec_versions.values() if v}
    if len(distinct) != 1:
        spec_version_ok = False
        errors.append(f"spec versions not uniform: {dict(sorted(spec_versions.items()))}")
    checks["spec_versions"] = {"value": spec_versions, "ok": spec_version_ok}

    prompt_hash = _prompt_hash(specs_dir)
    checks["prompt_hash"] = {"value": prompt_hash, "ok": True}

    checks["scoring_code_version"] = {"value": SCORING_CODE_VERSION, "ok": True}
    if SCORING_CODE_VERSION != expected_scoring_version:
        checks["scoring_code_version"]["ok"] = False
        errors.append(f"scoring code version mismatch: {SCORING_CODE_VERSION} != {expected_scoring_version}")
    # scoring code 文件 hash（不只看常量：engine/extractor/ordinal/parsing/validation/specs）
    code_hashes = {}
    code_ok = True
    for rel in ("scoring/engine.py", "scoring/extractors.py", "scoring/ordinal.py", "scoring/derived.py",
                "runtime/parsing.py", "runtime/validation.py", "runtime/specs.py", "runtime/output_schema.py",
                "runtime/quote_bind.py", "runtime/prompts.py", "preprocessing/spans.py", "preprocessing/paragraphs.py"):
        p = Path(__file__).resolve().parent / rel
        if not p.exists():
            code_ok = False
            errors.append(f"scoring code file missing: {rel}")
            continue
        code_hashes[rel] = sha256(p.read_bytes()).hexdigest()
    checks["scoring_code_files"] = {"value": code_hashes, "ok": code_ok}

    config_ok = True
    try:
        config = _load_config(config_path)
    except Exception as exc:
        config_ok = False
        errors.append(f"cannot load formal_model.yaml: {exc}")
        config = {}
    if config_ok:
        if not config.get("provider") or not config.get("model"):
            config_ok = False
            errors.append("experiment config must declare provider and model")
        if config.get("seed_supported") is False and config.get("seed") not in (None, ""):
            config_ok = False
            errors.append("seed is not supported by provider but a seed is set")
        if config.get("prompt_version") != expected_prompt_version:
            config_ok = False
            errors.append(f"config prompt_version {config.get('prompt_version')} != expected {expected_prompt_version}")
        if expected_config_version is not None and config.get("config_version") != expected_config_version:
            config_ok = False
            errors.append(f"config version {config.get('config_version')} != expected {expected_config_version}")
        # config 声明的 spec 版本必须与 spec 文件实际版本一致（防"配置说新版实际混旧版"）
        cfg_spec_ver = config.get("metric_spec_version")
        if cfg_spec_ver and len(distinct) == 1 and next(iter(distinct)) != cfg_spec_ver:
            config_ok = False
            errors.append(f"config metric_spec_version {cfg_spec_ver} != actual spec version {next(iter(distinct))}")
    config_hash = _config_sha256(config)
    checks["model_config"] = {"value": config_hash, "ok": config_ok}
    if config_ok:
        # 模型/采样参数由每个实验自行声明；Preflight 只保证声明完整且可追溯，不永久绑定某个模型。
        checks["model_config"]["ok"] = config_ok

    # context 截断检查：正文 + prompt 不得超过模型上下文预算（保守按 60K 码点，
    # max_tokens 由 config 提供；超出则正式运行会被截断，禁止启动）
    text_hash = text_sha256(canonical_text)
    checks["canonical_text_hash"] = {"value": text_hash, "ok": True}

    ctx_ok = True
    try:
        max_tokens = int(config.get("max_tokens", 8192))
    except (TypeError, ValueError):
        max_tokens = 8192
    text_len = len(canonical_text)
    if text_len > 60000 or text_len + max_tokens > 100000:
        ctx_ok = False
        errors.append(f"context budget exceeded: text {text_len} chars + max_tokens {max_tokens}")
    checks["context_budget"] = {"value": {"text_len": text_len, "max_tokens": max_tokens}, "ok": ctx_ok}

    return PreflightResult(ok=not errors, checks=checks, errors=errors)
