#!/usr/bin/env python3
"""Stage-only scoring execution boundary.

The scoring call path may only read staged canonical text, staged specs,
and staged config, and may only write card artifacts under staged output/.
Project root, corpus, ledger, splits, and historical run roots are rejected
as data paths. No credentials are accepted on argv.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Code import path only — never used as a scoring data root.
_CODE_ROOT = Path(__file__).resolve().parents[3]
if str(_CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CODE_ROOT))

import yaml

from scorer_v5.preflight import run_preflight
from scorer_v5.preprocessing.canonicalize import canonicalize
from scorer_v5.provenance.registry import ProvenanceRegistry
from scorer_v5.run_card import run_card
from scorer_v5.runtime.prompts import build_prompt
from scorer_v5.runtime.specs import load_metric_spec

ALLOWED_PROVIDER = "commandcode"
ALLOWED_MODEL = "deepseek/deepseek-v4-flash"
# Isolated grok-4.5 Smoke5 trial only; formal commandcode route unchanged.
TRIAL_PROVIDER = "xai"
TRIAL_MODEL = "grok-4.5"
ALLOWED_ROUTES = frozenset(
    {
        (ALLOWED_PROVIDER, ALLOWED_MODEL),
        (TRIAL_PROVIDER, TRIAL_MODEL),
    }
)
STAGING_LEAF = re.compile(
    r"[/\\]staging[/\\][^/\\]+[/\\][^/\\]+[/\\]rep\d+(?:[/\\]|$)",
    re.IGNORECASE,
)
FORBIDDEN_DATA_MARKERS = (
    "/corpus/",
    "\\corpus\\",
    "/data/split_",
    "\\data\\split_",
    "split_train.csv",
    "split_val.csv",
    "split_pilot.csv",
    "full_ledger",
    "判爆扑台账",
    "/cards/",
    "\\cards\\",
)

# Child process environment: allowlist only. Credentials and project-data
# pointers must never be inherited.
CHILD_ENV_ALLOW = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "SYSTEMDRIVE",
        "COMSPEC",
        "TEMP",
        "TMP",
        "TMPDIR",
        "PROCESSOR_ARCHITECTURE",
        "PROCESSOR_IDENTIFIER",
        "NUMBER_OF_PROCESSORS",
        "PYTHONIOENCODING",
        "PYTHONUTF8",
        "PYTHONNOUSERSITE",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "HOME",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "USERNAME",
        "USER",
        "LOGNAME",
        "OS",
        "TERM",
    }
)
CHILD_ENV_DENY_SUBSTR = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "AUTH",
    "CREDENTIAL",
    "HERMES",
    "PYTHONPATH",
    "VIRTUAL_ENV",
    "CONDA",
    "API",
    "CORPUS",
    "LEDGER",
    "SPLIT",
    "MINIMAX",
    "OPENAI",
    "ANTHROPIC",
)


class StageBoundaryError(ValueError):
    """Rejected non-staged or leaked data path."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(p: Path) -> Path:
    return p.resolve()


def _as_posix_lower(p: Path) -> str:
    return str(_norm(p)).replace("\\", "/").lower()


def assert_inside(path: Path, parent: Path, *, label: str) -> Path:
    rp = _norm(path)
    pp = _norm(parent)
    try:
        rp.relative_to(pp)
    except ValueError as exc:
        raise StageBoundaryError(f"{label} escapes staging parent: {rp} not under {pp}") from exc
    return rp


def reject_forbidden_data_path(path: Path, *, label: str) -> None:
    s = str(_norm(path))
    sl = s.replace("\\", "/").lower()
    for marker in FORBIDDEN_DATA_MARKERS:
        m = marker.replace("\\", "/").lower()
        if m in sl:
            raise StageBoundaryError(f"{label} hits forbidden marker {marker!r}: {path}")
    # Direct project-root data (not merely sharing a drive prefix).
    code_root = _as_posix_lower(_CODE_ROOT)
    p = sl.rstrip("/")
    if p == code_root:
        raise StageBoundaryError(f"{label} is project root: {path}")
    if sl.startswith(code_root + "/corpus"):
        raise StageBoundaryError(f"{label} is under corpus: {path}")
    if sl.startswith(code_root + "/data"):
        raise StageBoundaryError(f"{label} is under data/: {path}")


def validate_staging_root(staging_root: Path) -> Path:
    root = _norm(staging_root)
    if not root.is_dir():
        raise StageBoundaryError(f"staging_root is not a directory: {root}")
    if not STAGING_LEAF.search(str(root).replace("\\", "/") + "/"):
        raise StageBoundaryError(
            f"staging_root must match .../staging/<book>/<metric>/repN, got {root}"
        )
    reject_forbidden_data_path(root, label="staging_root")
    return root


def validate_stage_bundle(
    *,
    staging_root: Path,
    text: Path,
    specs: Path,
    config: Path,
    output: Path,
) -> dict[str, Path]:
    root = validate_staging_root(staging_root)
    text_p = assert_inside(text, root, label="text")
    specs_p = assert_inside(specs, root, label="specs")
    config_p = assert_inside(config, root, label="config")
    output_p = assert_inside(output, root, label="output")
    for label, p in (
        ("text", text_p),
        ("specs", specs_p),
        ("config", config_p),
        ("output", output_p),
    ):
        reject_forbidden_data_path(p, label=label)
    expected_text = root / "text" / "canonical.txt"
    expected_specs = root / "specs"
    expected_config = root / "config" / "formal_model.yaml"
    expected_output = root / "output"
    if _norm(text_p) != _norm(expected_text):
        raise StageBoundaryError(f"text must be {expected_text}, got {text_p}")
    if _norm(specs_p) != _norm(expected_specs):
        raise StageBoundaryError(f"specs must be {expected_specs}, got {specs_p}")
    if _norm(config_p) != _norm(expected_config):
        raise StageBoundaryError(f"config must be {expected_config}, got {config_p}")
    if _norm(output_p) != _norm(expected_output):
        raise StageBoundaryError(f"output must be {expected_output}, got {output_p}")
    if not text_p.is_file():
        raise StageBoundaryError(f"staged text missing: {text_p}")
    if not config_p.is_file():
        raise StageBoundaryError(f"staged config missing: {config_p}")
    if not specs_p.is_dir():
        raise StageBoundaryError(f"staged specs missing: {specs_p}")
    output_p.mkdir(parents=True, exist_ok=True)
    return {
        "root": root,
        "text": text_p,
        "specs": specs_p,
        "config": config_p,
        "output": output_p,
    }


def load_staged_config(config_path: Path) -> dict:
    with open(config_path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    if not isinstance(cfg, dict):
        raise StageBoundaryError("staged config is not a mapping")
    route = (cfg.get("provider"), cfg.get("model"))
    if route not in ALLOWED_ROUTES:
        raise StageBoundaryError(
            f"staged config must be {ALLOWED_PROVIDER}/{ALLOWED_MODEL} "
            f"or trial {TRIAL_PROVIDER}/{TRIAL_MODEL}, "
            f"got {cfg.get('provider')}/{cfg.get('model')}"
        )
    return cfg


def build_call_payload(prompt: str, cfg: dict) -> dict:
    """Construct OpenAI-compatible body exclusively from staged cfg + prompt.

    commandcode/deepseek-v4-flash uses the DeepSeek V4 wire shape:
    top-level ``reasoning_effort`` (low/medium/high/max) plus
    ``extra_body.thinking`` enabled. No root config. ``reasoning_mode`` in
    cfg selects the effort level (low by default).
    """
    rm = cfg.get("reasoning_mode")
    if rm is False or rm is None:
        effort = "off"
    else:
        effort = str(rm).strip().lower()
        if effort in ("false", "off", "none", "disabled", "0"):
            effort = "off"
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": float(cfg.get("temperature", 0.0)),
        "top_p": float(cfg.get("top_p", 1.0)),
        "max_tokens": int(cfg.get("max_tokens", 8192)),
        "seed": int(cfg.get("seed", 0)),
        "response_format": {"type": "json_object"},
    }
    if effort != "off":
        payload["reasoning_effort"] = effort
        payload["extra_body"] = {"thinking": {"type": "enabled"}}
    return payload


def model_params_from_cfg(cfg: dict) -> dict:
    return {
        "temperature": float(cfg.get("temperature", 0.0)),
        "top_p": float(cfg.get("top_p", 1.0)),
        "seed": int(cfg.get("seed", 0)),
        "max_tokens": int(cfg.get("max_tokens", 8192)),
        "reasoning_mode": str(cfg.get("reasoning_mode") or "low").strip().lower(),
    }


def env_key_forbidden(name: str) -> bool:
    u = name.upper()
    if u in {"HERMES_HOME", "PYTHONPATH"}:
        return True
    for sub in CHILD_ENV_DENY_SUBSTR:
        if sub in u:
            return True
    return False


def sanitize_child_env(src: dict[str, str] | None = None) -> dict[str, str]:
    """Build a cleaned child environment from an explicit allowlist.

    Never copies credentials, HERMES_HOME, PYTHONPATH, or project-data roots.
    """
    src = src if src is not None else os.environ
    out: dict[str, str] = {}
    for k, v in src.items():
        if env_key_forbidden(k):
            continue
        if k.upper() not in CHILD_ENV_ALLOW:
            continue
        out[k] = v
    out["PYTHONIOENCODING"] = "utf-8"
    out["PYTHONNOUSERSITE"] = "1"
    out.pop("PYTHONPATH", None)
    out.pop("HERMES_HOME", None)
    return out


def assert_child_environment(env: dict[str, str] | None = None) -> None:
    env = env if env is not None else os.environ
    leaked = sorted(k for k in env if env_key_forbidden(k))
    if leaked:
        raise StageBoundaryError(f"child environment contains forbidden keys: {leaked}")


def assert_cwd_is_staging(staging_root: Path) -> Path:
    root = _norm(staging_root)
    cwd = Path.cwd().resolve()
    if cwd != root:
        raise StageBoundaryError(f"child cwd {cwd} is not staging_root {root}")
    return cwd


def confined_result_path(output: Path) -> Path:
    return output / "result.json"


def write_staged_raw(output: Path, raw: str | bytes) -> Path:
    """Atomically place caller-provided model stdout under staged output/raw.txt.

    Same-directory tempfile + os.replace. Bytes unchanged (utf-8 if str).
    No smart-fix, no rewrite.
    """
    dest = output / "raw.txt"
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
    fd, tmp_name = tempfile.mkstemp(prefix=".raw.", suffix=".tmp", dir=str(dest.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, dest)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return dest


def write_confined_result(output: Path, rec: dict) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    _write_json(confined_result_path(output), rec)
    return rec


def child_audit_record(*, staging_root: Path, env: dict[str, str] | None = None) -> dict:
    env = env if env is not None else dict(os.environ)
    return {
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "cwd": str(Path.cwd().resolve()),
        "staging_root": str(_norm(staging_root)),
        "env_keys": sorted(env.keys()),
        "has_hermes_home": "HERMES_HOME" in env,
        "has_pythonpath": "PYTHONPATH" in env,
        "forbidden_env_keys": sorted(k for k in env if env_key_forbidden(k)),
    }


def launch_stage_child(
    *,
    staging_root: Path,
    book_id: str,
    metric: str,
    rep: int,
    run_id: str,
    raw_file: Path | None = None,
    timeout: int = 180,
) -> dict:
    """Start an isolated stage-only child with cwd=staging_root and cleaned env."""
    root = validate_staging_root(staging_root)
    bundle = validate_stage_bundle(
        staging_root=root,
        text=root / "text" / "canonical.txt",
        specs=root / "specs",
        config=root / "config" / "formal_model.yaml",
        output=root / "output",
    )
    argv = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--staging-root",
        ".",
        "--text",
        "text/canonical.txt",
        "--specs",
        "specs",
        "--config",
        "config/formal_model.yaml",
        "--output",
        "output",
        "--book-id",
        book_id,
        "--metric",
        metric,
        "--rep",
        str(int(rep)),
        "--run-id",
        run_id,
        "--no-http",
        "--emit-audit",
    ]
    if raw_file is not None:
        inside = assert_inside(raw_file, bundle["root"], label="raw_file")
        rel = inside.relative_to(bundle["root"]).as_posix()
        argv.extend(["--raw-file", rel])
    joined = " ".join(argv).lower()
    for needle in ("api_key", "token", "password", "minimax_cn", ".env", "bearer"):
        if needle in joined:
            raise StageBoundaryError("child argv must not contain credentials")
    env = sanitize_child_env()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(bundle["root"]),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:
        rec = {
            "status": "BLOCKED",
            "reason": "child_launch_failed",
            "error": str(exc)[:800],
            "book_id": book_id,
            "metric_id": metric,
            "rep": rep,
            "timestamp": utc_now(),
        }
        return write_confined_result(bundle["output"], rec)
    audit = {
        "parent_pid": os.getpid(),
        "returncode": proc.returncode,
        "argv": argv[2:],
        "cwd": str(bundle["root"]),
        "stdout_tail": (proc.stdout or "")[-2000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
    }
    _write_json(bundle["output"] / "child_launch.json", audit)
    result_p = confined_result_path(bundle["output"])
    if result_p.is_file():
        try:
            rec = json.loads(result_p.read_text(encoding="utf-8"))
            if isinstance(rec, dict):
                rec.setdefault("child_returncode", proc.returncode)
                return rec
        except Exception:
            pass
    rec = {
        "status": "BLOCKED",
        "reason": "child_exit_without_result" if proc.returncode != 0 else "child_missing_result",
        "error": (proc.stderr or proc.stdout or "")[:800],
        "book_id": book_id,
        "metric_id": metric,
        "rep": rep,
        "child_returncode": proc.returncode,
        "timestamp": utc_now(),
    }
    return write_confined_result(bundle["output"], rec)


def fan_in_staging_outputs(run_staging: Path, *, dest_dir: Path | None = None) -> dict:
    """Read-only fan-in from staging/*/*/rep*/output/result.json (+ provenance).

    Never reads or writes cards/. Deterministic sort + identity dedup.
    dest_dir if set receives temporary test summaries only.
    """
    staging = _norm(run_staging)
    if staging.name != "staging":
        raise StageBoundaryError(f"fan-in root must be a staging directory, got {staging}")
    found: dict[tuple[str, str, int], dict] = {}
    paths = sorted(staging.glob("*/*/rep*/output/result.json"))
    for p in paths:
        reject_forbidden_data_path(p, label="fan_in_result")
        if "cards" in {x.lower() for x in p.parts}:
            raise StageBoundaryError(f"fan-in hit cards path: {p}")
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(rec, dict):
            continue
        book = str(rec.get("book_id") or rec.get("id") or p.parents[3].name)
        metric = str(rec.get("metric_id") or p.parents[2].name)
        try:
            rep = int(rec.get("rep") if rec.get("rep") is not None else str(p.parents[1].name).replace("rep", ""))
        except Exception:
            continue
        key = (book, metric, rep)
        prov = p.with_name("provenance.json")
        slim = {
            "id": book,
            "book_id": book,
            "rep": rep,
            "metric_id": metric,
            "status": rec.get("status"),
            "score": rec.get("score"),
            "abstained": rec.get("abstained"),
            "provider": rec.get("provider"),
            "model": rec.get("model"),
            "result_path": str(p),
            "provenance_path": str(prov) if prov.is_file() else None,
        }
        found[key] = slim
    rows = [found[k] for k in sorted(found)]
    summary = {
        "written": len(rows),
        "by_status": {},
        "identities": [list(k) for k in sorted(found)],
        "source": "staging_output_readonly",
        "cards_read": 0,
        "timestamp": utc_now(),
    }
    for row in rows:
        st = row.get("status") or "unknown"
        summary["by_status"][st] = summary["by_status"].get(st, 0) + 1
    if dest_dir is not None:
        dest = _norm(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        if dest == staging or "cards" in {x.lower() for x in dest.parts}:
            raise StageBoundaryError("fan-in dest must not be cards/ or staging itself")
        jsonl = dest / "fan_in_results.jsonl"
        with open(jsonl, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        _write_json(dest / "fan_in_summary.json", summary)
        summary["jsonl"] = str(jsonl)
    return summary


def classify_status(scored: dict) -> str:
    if scored.get("abstained"):
        return "ABSTAIN"
    err = scored.get("error") or ""
    val = scored.get("validation") or {}
    outcome = val.get("outcome") or val.get("status") or ""
    for token in (
        "FAIL_PARSE",
        "FAIL_DUPLICATE_KEY",
        "FAIL_SCHEMA",
        "EVIDENCE_FAIL",
        "LOGIC_FAIL",
        "SCHEMA_FAIL",
    ):
        if token in str(err) or token in str(outcome):
            return token
    if scored.get("score") is None and err:
        return "BLOCKED"
    return "OK"


def _write_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def execute_stage_card(
    *,
    staging_root: Path,
    book_id: str,
    metric: str,
    rep: int,
    run_id: str,
    transport=None,
    allow_http: bool = False,
    raw_text_override: str | None = None,
) -> dict:
    """Run preflight → prompt → (optional transport) → run_card inside staging output.

    transport(prompt, cfg) -> (raw_text, http_meta). If omitted and allow_http is
    False, write payload.json and return status PAYLOAD_ONLY (no network).
    """
    root = validate_staging_root(staging_root)
    bundle = validate_stage_bundle(
        staging_root=root,
        text=root / "text" / "canonical.txt",
        specs=root / "specs",
        config=root / "config" / "formal_model.yaml",
        output=root / "output",
    )
    out = bundle["output"]
    try:
        return _execute_stage_card_inner(
            bundle=bundle,
            book_id=book_id,
            metric=metric,
            rep=rep,
            run_id=run_id,
            transport=transport,
            allow_http=allow_http,
            raw_text_override=raw_text_override,
        )
    except StageBoundaryError:
        raise
    except Exception as exc:
        rec = {
            "status": "BLOCKED",
            "reason": "stage_exception",
            "error": str(exc)[:800],
            "book_id": book_id,
            "metric_id": metric,
            "rep": rep,
            "timestamp": utc_now(),
        }
        return write_confined_result(out, rec)


def _execute_stage_card_inner(
    *,
    bundle: dict[str, Path],
    book_id: str,
    metric: str,
    rep: int,
    run_id: str,
    transport,
    allow_http: bool,
    raw_text_override: str | None,
) -> dict:
    out = bundle["output"]
    cfg = load_staged_config(bundle["config"])
    model_params = model_params_from_cfg(cfg)

    raw_text = bundle["text"].read_text(encoding="utf-8")
    canonical = canonicalize(raw_text)
    pre = run_preflight(
        canonical_text=canonical,
        config_path=bundle["config"],
        specs_dir=bundle["specs"],
    )
    _write_json(
        out / "preflight.json",
        {
            "ok": pre.ok,
            "errors": pre.errors,
            "checks": {
                k: {
                    "ok": v.get("ok"),
                    "value": v.get("value") if k != "scoring_code_files" else "omitted",
                }
                for k, v in pre.checks.items()
            },
            "config_path": str(bundle["config"]),
            "specs_dir": str(bundle["specs"]),
            "text_path": str(bundle["text"]),
        },
    )
    if not pre.ok:
        rec = {
            "status": "BLOCKED",
            "reason": "preflight_failed",
            "errors": pre.errors,
            "book_id": book_id,
            "metric_id": metric,
            "rep": rep,
            "provider": cfg["provider"],
            "model": cfg["model"],
            "timestamp": utc_now(),
        }
        return write_confined_result(out, rec)

    spec = load_metric_spec(metric, specs_dir=bundle["specs"])
    prompt = build_prompt(spec, canonical)
    (out / "prompt.txt").write_text(prompt, encoding="utf-8")
    payload = build_call_payload(prompt, cfg)
    payload_meta = {
        "provider": cfg["provider"],
        "model": payload["model"],
        "temperature": payload["temperature"],
        "top_p": payload["top_p"],
        "seed": payload["seed"],
        "max_tokens": payload["max_tokens"],
        "config_path": str(bundle["config"]),
        "source": "staged_config",
    }
    _write_json(out / "call_payload.json", {"meta": payload_meta, "body": payload})

    if raw_text_override is None and transport is None and not allow_http:
        rec = {
            "status": "PAYLOAD_ONLY",
            "reason": "no_transport_no_http",
            "book_id": book_id,
            "metric_id": metric,
            "rep": rep,
            "provider": cfg["provider"],
            "model": cfg["model"],
            "model_params": model_params,
            "timestamp": utc_now(),
            "http": 0,
        }
        return write_confined_result(out, rec)

    if raw_text_override is not None:
        raw, meta = raw_text_override, {"http_status": 0, "source": "raw_file", "http": 0}
        # Do not rewrite output/raw.txt; parent owns the bytes.
    elif transport is None:
        raise StageBoundaryError("allow_http without injected transport is forbidden in this module")
    else:
        try:
            raw, meta = transport(prompt, cfg)
        except Exception as exc:
            rec = {
                "status": "BLOCKED",
                "reason": "llm_call_failed",
                "error": str(exc)[:800],
                "book_id": book_id,
                "metric_id": metric,
                "rep": rep,
                "provider": cfg["provider"],
                "model": cfg["model"],
                "timestamp": utc_now(),
            }
            return write_confined_result(out, rec)
        write_staged_raw(out, raw)

    _write_json(out / "http_meta.json", meta)

    prov_path = out / "provenance.json"
    registry = ProvenanceRegistry(prov_path)
    scored = run_card(
        run_id=run_id,
        book_id=book_id,
        metric_id=metric,
        rep=rep,
        text=canonical,
        raw_model_output=raw,
        provenance=registry,
        specs_dir=bundle["specs"],
        provider=cfg["provider"],
        model=cfg["model"],
        model_params=model_params,
    )
    registry.save()
    status = classify_status(scored)
    rec = {
        "status": status,
        "book_id": book_id,
        "metric_id": metric,
        "rep": rep,
        "id": book_id,
        "score": scored.get("score"),
        "abstained": scored.get("abstained"),
        "continuous": scored.get("continuous"),
        "error": scored.get("error"),
        "validation": scored.get("validation"),
        "provider": cfg["provider"],
        "model": cfg["model"],
        "model_params": model_params,
        "timestamp": utc_now(),
    }
    return write_confined_result(out, rec)


def parse_argv(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stage-only scoring subprocess")
    p.add_argument("--staging-root", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--specs", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--book-id", required=True)
    p.add_argument("--metric", required=True)
    p.add_argument("--rep", type=int, required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument(
        "--no-http",
        action="store_true",
        help="Build payload and run preflight/prompt only; zero network.",
    )
    p.add_argument("--emit-audit", action="store_true")
    p.add_argument(
        "--raw-file",
        default=None,
        help="Staged-only raw model output path (must sit under staging_root).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_argv(argv)
    staging_root = Path(args.staging_root)
    try:
        assert_cwd_is_staging(staging_root)
        assert_child_environment()
        bundle = validate_stage_bundle(
            staging_root=staging_root,
            text=Path(args.text),
            specs=Path(args.specs),
            config=Path(args.config),
            output=Path(args.output),
        )
    except StageBoundaryError as exc:
        # Best-effort confinement when output is already a valid staged output dir.
        try:
            out = Path(args.output)
            if out.name == "output" and STAGING_LEAF.search(str(out.parent).replace("\\", "/") + "/"):
                write_confined_result(
                    out,
                    {
                        "status": "BLOCKED",
                        "reason": "stage_boundary",
                        "error": str(exc)[:800],
                        "book_id": args.book_id,
                        "metric_id": args.metric,
                        "rep": int(args.rep),
                        "timestamp": utc_now(),
                    },
                )
        except Exception:
            pass
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    audit = child_audit_record(staging_root=bundle["root"])
    _write_json(bundle["output"] / "child_audit.json", audit)
    if args.emit_audit:
        print(json.dumps({"ok": True, "audit": audit}, ensure_ascii=False), file=sys.stderr)
    if not args.no_http:
        rec = {
            "status": "BLOCKED",
            "reason": "http_disabled",
            "error": "HTTP disabled in stage_only_exec; parent must hand off staged output/raw.txt",
            "book_id": args.book_id,
            "metric_id": args.metric,
            "rep": int(args.rep),
            "timestamp": utc_now(),
            "http": 0,
        }
        write_confined_result(bundle["output"], rec)
        print(json.dumps({"ok": False, "error": rec["error"], "http": 0}, ensure_ascii=False), file=sys.stderr)
        return 2
    raw_override = None
    if not args.raw_file:
        rec = {
            "status": "BLOCKED",
            "reason": "missing_raw",
            "error": "child requires staged output/raw.txt; PAYLOAD_ONLY is not a scoring terminal",
            "book_id": args.book_id,
            "metric_id": args.metric,
            "rep": int(args.rep),
            "timestamp": utc_now(),
            "http": 0,
        }
        write_confined_result(bundle["output"], rec)
        print(json.dumps({"ok": True, "status": rec["status"], "http": 0}, ensure_ascii=False))
        return 0
    raw_path = assert_inside(Path(args.raw_file), bundle["root"], label="raw_file")
    if not raw_path.is_file():
        rec = {
            "status": "BLOCKED",
            "reason": "missing_raw",
            "error": f"raw file missing: {raw_path}",
            "book_id": args.book_id,
            "metric_id": args.metric,
            "rep": int(args.rep),
            "timestamp": utc_now(),
            "http": 0,
        }
        write_confined_result(bundle["output"], rec)
        print(json.dumps({"ok": True, "status": rec["status"], "http": 0}, ensure_ascii=False))
        return 0
    raw_override = raw_path.read_text(encoding="utf-8")
    rec = execute_stage_card(
        staging_root=bundle["root"],
        book_id=args.book_id,
        metric=args.metric,
        rep=int(args.rep),
        run_id=args.run_id,
        transport=None,
        allow_http=False,
        raw_text_override=raw_override,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "status": rec.get("status"),
                "http": 0,
                "pid": audit["pid"],
                "cwd": audit["cwd"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
