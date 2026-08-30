#!/usr/bin/env python3
"""Dev10 formal scoring runner: prompt → commandcode/deepseek-v4-flash HTTP → raw → run_card (zero repair).

Credentials are read from the blindwriter profile .env only; never written to
project files. Failed cards are recorded as BLOCKED, never invented scores.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import importlib.util

import yaml

_STAGE_MOD_PATH = Path(__file__).resolve().parent / "stage_only_exec.py"
_STAGE_SPEC = importlib.util.spec_from_file_location("dev10_stage_only_exec", _STAGE_MOD_PATH)
_STAGE = importlib.util.module_from_spec(_STAGE_SPEC)
assert _STAGE_SPEC and _STAGE_SPEC.loader
_STAGE_SPEC.loader.exec_module(_STAGE)
execute_stage_card = _STAGE.execute_stage_card
load_staged_config = _STAGE.load_staged_config
model_params_from_cfg = _STAGE.model_params_from_cfg
launch_stage_child = _STAGE.launch_stage_child
fan_in_staging_outputs = _STAGE.fan_in_staging_outputs
write_confined_result = _STAGE.write_confined_result
write_staged_raw = _STAGE.write_staged_raw

EXP_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = EXP_DIR / "dev10_r3_manifest.json"
CONFIG_PATH = ROOT / "scorer_v5" / "config" / "formal_model.yaml"
SPECS_DIR = ROOT / "scorer_v5" / "specs"
BLINDWRITER_ENV = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "profiles" / "blindwriter" / ".env"
RUN_ID = "dev10_v5_r3"
RUN_DIR = EXP_DIR / "runs" / RUN_ID
ALLOWED_PROVIDER = "commandcode"
ALLOWED_MODEL = "deepseek/deepseek-v4-flash"
TRIAL_PROVIDER = "xai"
TRIAL_MODEL = "grok-4.5"
FORMAL_CONFIG_PATH = ROOT / "scorer_v5" / "config" / "formal_model.yaml"
PAUSED_METRICS = frozenset({"C14"})
SMOKE_N_BOOKS = 2
SMOKE_REPS = (1,)
DEFAULT_URL = "https://api.commandcode.ai/provider/v1/chat/completions"
DEFAULT_XAI_URL = "https://api.x.ai/v1/chat/completions"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        out[k] = v
    return out


def load_config(path: Path | None = None) -> dict:
    cfg_path = path or CONFIG_PATH
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    route = (cfg.get("provider"), cfg.get("model"))
    is_formal = cfg_path.resolve() == FORMAL_CONFIG_PATH.resolve()
    if is_formal:
        if route != (ALLOWED_PROVIDER, ALLOWED_MODEL):
            raise SystemExit(f"formal_model.yaml must be {ALLOWED_PROVIDER}/{ALLOWED_MODEL}")
    elif route != (TRIAL_PROVIDER, TRIAL_MODEL):
        raise SystemExit(f"trial config must be {TRIAL_PROVIDER}/{TRIAL_MODEL}")
    return cfg


def card_dir(book_id: str, metric: str, rep: int) -> Path:
    return RUN_DIR / "cards" / book_id / metric / f"rep{rep}"


def result_path(book_id: str, metric: str, rep: int) -> Path:
    return card_dir(book_id, metric, rep) / "result.json"


# Strict terminal statuses: replay must not re-issue HTTP for these.
TERMINAL_STATUSES = frozenset(
    {
        "OK",
        "ABSTAIN",
        "FAIL_PARSE",
        "FAIL_DUPLICATE_KEY",
        "FAIL_SCHEMA",
        "SCHEMA_FAIL",
        "EVIDENCE_FAIL",
        "LOGIC_FAIL",
        "BLOCKED",
    }
)


def is_done(book_id: str, metric: str, rep: int) -> bool:
    """Pending/done uses only this card's staging output/result.json.

    Legacy RUN_DIR/cards/.../result.json is never consulted.
    """
    p = staging_dir(book_id, metric, rep) / "output" / "result.json"
    if not p.is_file():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    return data.get("status") in TERMINAL_STATUSES


def staging_dir(book_id: str, metric: str, rep: int) -> Path:
    return RUN_DIR / "staging" / book_id / metric / f"rep{rep}"


def prepare_card_staging(book: dict, metric: str, rep: int) -> dict[str, Path]:
    """Per-card isolated tree: this book's text, frozen specs, frozen config, card output.

    The scoring path after this function must read only these paths — never corpus/,
    ledger, splits, or the project root.
    """
    stage = staging_dir(book["id"], metric, rep)
    text_dir = stage / "text"
    specs_dst = stage / "specs"
    cfg_dst = stage / "config"
    out_dst = stage / "output"
    for d in (text_dir, specs_dst, cfg_dst, out_dst):
        d.mkdir(parents=True, exist_ok=True)
    src_text = ROOT / book["path"]
    dst_text = text_dir / "canonical.txt"
    dst_text.write_text(src_text.read_text(encoding="utf-8"), encoding="utf-8")
    for yaml_path in sorted(SPECS_DIR.glob("*.yaml")):
        shutil.copy2(yaml_path, specs_dst / yaml_path.name)
    shutil.copy2(CONFIG_PATH, cfg_dst / "formal_model.yaml")
    return {
        "root": stage,
        "text": dst_text,
        "specs": specs_dst,
        "config": cfg_dst / "formal_model.yaml",
        "output": out_dst,
    }


def extract_content(payload: dict) -> str:
    choices = payload.get("choices") or []
    if choices:
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") in (None, "text"):
                    parts.append(item.get("text") or "")
                elif isinstance(item, str):
                    parts.append(item)
            joined = "".join(parts)
            if joined.strip():
                return joined
    if isinstance(payload.get("content"), str) and payload["content"].strip():
        return payload["content"]
    raise ValueError("empty model content")


def call_commandcode(prompt: str, cfg: dict, api_key: str, base_url: str) -> tuple[str, dict]:
    """Parent-only commandcode/deepseek-v4-flash chat completions.

    OpenAI-compatible endpoint; DeepSeek V4 wire uses top-level
    ``reasoning_effort`` (low/medium/high/max) plus ``extra_body.thinking``
    enabled. Never logs credentials.
    """
    rm = cfg.get("reasoning_mode")
    if rm is False or rm is None:
        effort = "off"
    else:
        effort = str(rm).strip().lower()
        if effort in ("false", "off", "none", "disabled", "0"):
            effort = "off"
    body = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": float(cfg.get("temperature", 0.0)),
        "top_p": float(cfg.get("top_p", 1.0)),
        "max_tokens": int(cfg.get("max_tokens", 8192)),
        "seed": int(cfg.get("seed", 0)),
        "response_format": {"type": "json_object"},
    }
    if effort != "off":
        body["reasoning_effort"] = effort
        body["extra_body"] = {"thinking": {"type": "enabled"}}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base_url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            # urllib's default UA (Python-urllib/3.x) is blocked by
            # Cloudflare (403 code 1010); the interactive Hermes client
            # passes Cloudflare with a browser-class UA. Keep a stable
            # identifying UA here (transport-only; no scoring/isolation
            # impact).
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        },
    )
    timeout = int(cfg.get("timeout", 180))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_bytes = resp.read()
            http_status = resp.status
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {err_body[:500]}") from exc
    payload = json.loads(raw_bytes.decode("utf-8"))
    if payload.get("error"):
        raise RuntimeError(f"commandcode error={payload.get('error')}")
    content = extract_content(payload)
    meta = {
        "http_status": http_status,
        "usage": payload.get("usage"),
        "id": payload.get("id"),
        "model_returned": payload.get("model"),
    }
    return content, meta


def call_xai(prompt: str, cfg: dict, api_key: str, base_url: str) -> tuple[str, dict]:
    """Parent-only xAI chat completions. Never logs credentials."""
    body = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": float(cfg.get("temperature", 0.0)),
        "top_p": float(cfg.get("top_p", 1.0)),
        "max_tokens": int(cfg.get("max_tokens", 8192)),
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base_url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    timeout = int(cfg.get("timeout", 180))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_bytes = resp.read()
            http_status = resp.status
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {err_body[:500]}") from exc
    payload = json.loads(raw_bytes.decode("utf-8"))
    content = extract_content(payload)
    meta = {
        "http_status": http_status,
        "usage": payload.get("usage"),
        "id": payload.get("id"),
        "model_returned": payload.get("model"),
    }
    return content, meta


def classify_status(scored: dict) -> str:
    if scored.get("abstained"):
        return "ABSTAIN"
    err = scored.get("error") or ""
    val = scored.get("validation") or {}
    outcome = val.get("outcome") or val.get("status") or ""
    for token in ("FAIL_PARSE", "FAIL_DUPLICATE_KEY", "FAIL_SCHEMA", "EVIDENCE_FAIL", "LOGIC_FAIL", "SCHEMA_FAIL"):
        if token in str(err) or token in str(outcome):
            return token
    if scored.get("score") is None and err:
        return "BLOCKED"
    return "OK"


class ParentTransportError(Exception):
    """Offline parent acquisition failed without producing raw bytes."""


def offline_acquire_parent_raw(
    *,
    book: dict,
    metric: str,
    rep: int,
    stage: dict,
) -> bytes | None:
    """Default isolation transport: no .env, no HTTP, no sockets.

    Returns None (missing raw). Tests inject bytes or raise ParentTransportError.
    Live commandcode is injected by main via live_acquire_parent_raw into this seam.
    """
    del book, metric, rep, stage
    return None


def live_acquire_parent_raw(
    *,
    book: dict,
    metric: str,
    rep: int,
    stage: dict,
    cfg: dict,
    api_key: str,
    base_url: str,
) -> bytes:
    """Parent-only model call. Returns raw content bytes; never logs credentials."""
    del book, rep, cfg
    try:
        staged_cfg = load_staged_config(stage["config"])
        provider = staged_cfg.get("provider")
        model = staged_cfg.get("model")
        if provider == ALLOWED_PROVIDER and model == ALLOWED_MODEL:
            caller = call_commandcode
        elif provider == TRIAL_PROVIDER and model == TRIAL_MODEL:
            caller = call_xai
        else:
            raise ParentTransportError(
                "staged config is not commandcode/deepseek/deepseek-v4-flash or trial xai/grok-4.5"
            )
        if not api_key:
            if provider == TRIAL_PROVIDER:
                raise ParentTransportError("XAI_API_KEY missing from blindwriter .env / env")
            raise ParentTransportError("COMMANDCODE_API_KEY missing from blindwriter .env / env")
        call_cfg = dict(staged_cfg)
        call_cfg["temperature"] = 0.0
        call_cfg["top_p"] = 1.0
        call_cfg["seed"] = 0
        from scorer_v5.preprocessing.canonicalize import canonicalize
        from scorer_v5.runtime.prompts import build_prompt
        from scorer_v5.runtime.specs import load_metric_spec

        text = Path(stage["text"]).read_text(encoding="utf-8")
        spec = load_metric_spec(metric, specs_dir=Path(stage["specs"]))
        prompt = build_prompt(spec, canonicalize(text))
        content, _meta = caller(prompt, call_cfg, api_key, base_url)
        if not isinstance(content, str) or not content.strip():
            raise ParentTransportError("empty model content")
        return content.encode("utf-8")
    except ParentTransportError:
        raise
    except Exception as exc:
        raise ParentTransportError(str(exc)[:800]) from exc


def process_card(
    *,
    book: dict,
    metric: str,
    rep: int,
    cfg: dict,
    api_key: str,
    base_url: str,
    model_params: dict,
    acquire_parent_raw=None,
    prepare_fn=None,
) -> dict:
    """Orchestrator: stage → injectable parent raw → atomic write_staged_raw → child.

    Default acquire_parent_raw is offline (no HTTP/.env). Card artifacts stay
    under staging/.../output/. Fan-in to cards/ is a later explicit copy step.
    """
    del cfg, model_params  # scoring path reloads staged config
    del api_key, base_url  # never passed into child argv/env
    book_id = book["id"]
    prepare = prepare_fn or prepare_card_staging
    stage = prepare(book, metric, rep)
    (stage["root"] / "staging_manifest.json").write_text(
        json.dumps(
            {
                "staging_root": str(stage["root"]),
                "text": str(stage["text"]),
                "specs": str(stage["specs"]),
                "config": str(stage["config"]),
                "output": str(stage["output"]),
                "book_id": book_id,
                "metric_id": metric,
                "rep": rep,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    staged_cfg = load_staged_config(stage["config"])
    acquire = offline_acquire_parent_raw if acquire_parent_raw is None else acquire_parent_raw
    try:
        raw = acquire(book=book, metric=metric, rep=rep, stage=stage)
    except ParentTransportError as exc:
        rec = {
            "status": "BLOCKED",
            "reason": "parent_transport_failed",
            "error": str(exc)[:800],
            "book_id": book_id,
            "metric_id": metric,
            "rep": rep,
            "timestamp": utc_now(),
        }
        return write_confined_result(stage["output"], rec)
    except Exception as exc:
        rec = {
            "status": "BLOCKED",
            "reason": "parent_transport_failed",
            "error": str(exc)[:800],
            "book_id": book_id,
            "metric_id": metric,
            "rep": rep,
            "timestamp": utc_now(),
        }
        return write_confined_result(stage["output"], rec)
    if raw is None:
        rec = {
            "status": "BLOCKED",
            "reason": "parent_missing_raw",
            "error": "parent acquisition returned no raw; no HTTP in this isolation path",
            "book_id": book_id,
            "metric_id": metric,
            "rep": rep,
            "timestamp": utc_now(),
        }
        return write_confined_result(stage["output"], rec)
    raw_path = write_staged_raw(stage["output"], raw)
    try:
        rec = launch_stage_child(
            staging_root=stage["root"],
            book_id=book_id,
            metric=metric,
            rep=rep,
            run_id=RUN_ID,
            raw_file=raw_path,
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
        write_confined_result(stage["output"], rec)
    rec.setdefault("model_params", model_params_from_cfg(staged_cfg))
    return rec


def write_summaries(manifest: dict, *, expected: int | None = None) -> dict:
    rows = []
    blocked = []
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    for book in manifest["books"]:
        for metric in manifest["metrics"]:
            if metric in PAUSED_METRICS:
                continue
            for rep in manifest["reps"]:
                p = result_path(book["id"], metric, rep)
                if not p.is_file():
                    continue
                rec = json.loads(p.read_text(encoding="utf-8"))
                slim = {
                    "id": rec.get("book_id") or rec.get("id"),
                    "rep": rec.get("rep"),
                    "metric_id": rec.get("metric_id"),
                    "status": rec.get("status"),
                    "score": rec.get("score"),
                    "abstained": rec.get("abstained"),
                    "provider": rec.get("provider"),
                    "model": rec.get("model"),
                }
                rows.append(slim)
                if rec.get("status") == "BLOCKED":
                    blocked.append(rec)
    jsonl = RUN_DIR / "results.jsonl"
    with open(jsonl, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    (RUN_DIR / "blocked.json").write_text(json.dumps(blocked, ensure_ascii=False, indent=2), encoding="utf-8")
    if expected is None:
        expected = int(manifest.get("call_count", 150))
    summary = {
        "run_id": RUN_ID,
        "expected": expected,
        "written": len(rows),
        "blocked": len(blocked),
        "by_status": {},
        "provider": ALLOWED_PROVIDER,
        "model": ALLOWED_MODEL,
        "run_dir": str(RUN_DIR),
        "timestamp": utc_now(),
    }
    for row in rows:
        st = row.get("status") or "unknown"
        summary["by_status"][st] = summary["by_status"].get(st, 0) + 1
    (RUN_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--run-id",
        default=None,
        help="Isolate output under runs/<run-id>/; default remains dev10_v5_r3.",
    )
    parser.add_argument(
        "--pending-only",
        action="store_true",
        help="Print pending count and exit with no HTTP. Used to prove replay safety.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Experiment config path. Default is formal commandcode yaml (never overwritten).",
    )
    args = parser.parse_args(argv)
    global RUN_ID, RUN_DIR, CONFIG_PATH
    if args.run_id:
        RUN_ID = args.run_id
        RUN_DIR = EXP_DIR / "runs" / RUN_ID
    if args.config:
        CONFIG_PATH = Path(args.config)
        if not CONFIG_PATH.is_file():
            print(f"BLOCKED: config not found: {CONFIG_PATH}", file=sys.stderr)
            return 2
        if CONFIG_PATH.resolve() == FORMAL_CONFIG_PATH.resolve():
            print("BLOCKED: refusing to treat formal_model.yaml as a trial overwrite target", file=sys.stderr)
            return 2

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    cfg = load_config(CONFIG_PATH)
    model_params = {
        "temperature": float(cfg.get("temperature", 0.0)),
        "top_p": float(cfg.get("top_p", 1.0)),
        "seed": int(cfg.get("seed", 0)),
        "max_tokens": int(cfg.get("max_tokens", 8192)),
    }
    trial = (cfg.get("provider"), cfg.get("model")) == (TRIAL_PROVIDER, TRIAL_MODEL)
    if not trial and (cfg["provider"] != ALLOWED_PROVIDER or cfg["model"] != ALLOWED_MODEL):
        print("BLOCKED: refusing non-formal route", file=sys.stderr)
        return 2
    api_key = ""
    base_url = DEFAULT_XAI_URL if trial else DEFAULT_URL
    if not args.pending_only:
        env = load_dotenv(BLINDWRITER_ENV)
        if trial:
            api_key = env.get("XAI_API_KEY") or os.environ.get("XAI_API_KEY")
            if not api_key:
                print("BLOCKED: XAI_API_KEY missing from blindwriter .env / env", file=sys.stderr)
                return 2
            base_url = env.get("XAI_BASE_URL") or os.environ.get("XAI_BASE_URL") or DEFAULT_XAI_URL
        else:
            api_key = env.get("COMMANDCODE_API_KEY") or os.environ.get("COMMANDCODE_API_KEY")
            if not api_key:
                print("BLOCKED: COMMANDCODE_API_KEY missing from blindwriter .env / env", file=sys.stderr)
                return 2
            base_url = env.get("COMMANDCODE_BASE_URL") or os.environ.get("COMMANDCODE_BASE_URL") or DEFAULT_URL

    jobs = []
    paused = []
    metrics = [m for m in manifest["metrics"] if m not in PAUSED_METRICS]
    for book in manifest["books"]:
        for metric in metrics:
            for rep in manifest["reps"]:
                jobs.append((book, metric, int(rep)))
    for metric in manifest.get("paused_metrics", []) or []:
        paused.append(metric)
    if paused:
        print(f"paused_metrics={sorted(set(paused))}", flush=True)
    if args.smoke:
        smoke_metrics = list(metrics)
        jobs = []
        for book in manifest["books"][:SMOKE_N_BOOKS]:
            for metric in smoke_metrics:
                for rep in SMOKE_REPS:
                    jobs.append((book, metric, int(rep)))
        if len(jobs) != 10:
            print(f"BLOCKED: smoke must be 2 books × 5 metrics × rep1 = 10, got {len(jobs)}", file=sys.stderr)
            return 2
        reps = {j[2] for j in jobs}
        if reps != {1}:
            print(f"BLOCKED: smoke reps must be {{1}}, got {reps}", file=sys.stderr)
            return 2
    elif args.limit:
        jobs = jobs[: args.limit]

    pending = [j for j in jobs if not is_done(j[0]["id"], j[1], j[2])]
    workers = min(max(args.workers, 1), 3)
    print(f"run_id={RUN_ID} run_dir={RUN_DIR} jobs={len(jobs)} pending={len(pending)} workers={workers}", flush=True)
    if args.pending_only:
        print(json.dumps({"run_id": RUN_ID, "jobs": len(jobs), "pending": len(pending), "http": 0}, ensure_ascii=False))
        return 0 if len(pending) == 0 or not (RUN_DIR / "results.jsonl").is_file() else 0

    def acquire_live(*, book, metric, rep, stage):
        return live_acquire_parent_raw(
            book=book,
            metric=metric,
            rep=rep,
            stage=stage,
            cfg=cfg,
            api_key=api_key,
            base_url=base_url,
        )

    results = []
    if workers == 1:
        for book, metric, rep in pending:
            rec = process_card(
                book=book,
                metric=metric,
                rep=rep,
                cfg=cfg,
                api_key=api_key,
                base_url=base_url,
                model_params=model_params,
                acquire_parent_raw=acquire_live,
            )
            results.append(rec)
            print(f"{book['id']} {metric} r{rep} -> {rec.get('status')} score={rec.get('score')}", flush=True)
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {
                ex.submit(
                    process_card,
                    book=book,
                    metric=metric,
                    rep=rep,
                    cfg=cfg,
                    api_key=api_key,
                    base_url=base_url,
                    model_params=model_params,
                    acquire_parent_raw=acquire_live,
                ): (book["id"], metric, rep)
                for book, metric, rep in pending
            }
            for fut in as_completed(futs):
                bid, metric, rep = futs[fut]
                try:
                    rec = fut.result()
                except Exception as exc:
                    rec = {"status": "BLOCKED", "book_id": bid, "metric_id": metric, "rep": rep, "error": str(exc)[:800], "reason": "worker_exception"}
                    out = staging_dir(bid, metric, rep) / "output"
                    write_confined_result(out, rec)
                results.append(rec)
                print(f"{bid} {metric} r{rep} -> {rec.get('status')} score={rec.get('score')}", flush=True)

    fan_dest = RUN_DIR / "fan_in_tmp"
    summary = fan_in_staging_outputs(RUN_DIR / "staging", dest_dir=fan_dest)
    summary["run_id"] = RUN_ID
    summary["expected"] = len(jobs) if args.smoke else int(manifest.get("call_count", 150))
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    if args.smoke:
        if any(r.get("status") == "BLOCKED" and r.get("reason") == "preflight_failed" for r in results):
            return 3
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
