#!/usr/bin/env python3
"""Smoke5 stability 3-rep concurrent driver — commandcode/deepseek-v4-flash config-4.

Task t_a7b64411. 15 real calls: book 276 x metrics B01/B02/N6/B33/B36 x reps
1/2/3, workers=3. Reuses the frozen isolation machinery from
stage_only_exec.py (per-card staging, sanitized child env, --no-http child
scoring, atomic write_staged_raw). Does NOT modify any spec/prompt/config/
frozen artifact. New isolated run dir:
  runs/dev10_v5_r3_iso_v4_smoke5_stability_276_3rep
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml

_EXP = Path(__file__).resolve().parent
_STAGE_MOD = _EXP / "stage_only_exec.py"
_STAGE_SPEC = importlib.util.spec_from_file_location("smoke5_stability_stage", _STAGE_MOD)
_STAGE = importlib.util.module_from_spec(_STAGE_SPEC)
assert _STAGE_SPEC and _STAGE_SPEC.loader
_STAGE_SPEC.loader.exec_module(_STAGE)

from scorer_v5.preprocessing.canonicalize import canonicalize
from scorer_v5.runtime.prompts import build_prompt
from scorer_v5.runtime.specs import load_metric_spec

MANIFEST_PATH = _EXP / "dev10_r3_manifest.json"
CONFIG_PATH = ROOT / "scorer_v5" / "config" / "formal_model.yaml"
SPECS_DIR = ROOT / "scorer_v5" / "specs"
RUN_ID = "dev10_v5_r3_iso_v4_smoke5_stability_276_3rep"
RUN_DIR = _EXP / "runs" / RUN_ID
DEFAULT_URL = "https://api.commandcode.ai/provider/v1/chat/completions"

# Correct contract (t_a7b64411): one book 276 x 5 metrics x 3 reps = 15 calls.
BOOKS = ("276",)
METRICS = ("B01", "B02", "N6", "B33", "B36")
REPS = (1, 2, 3)
EXPECTED_CALLS = len(BOOKS) * len(METRICS) * len(REPS)  # 15


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


def blindwriter_env_path() -> Path:
    local = Path(__import__("os").environ.get("LOCALAPPDATA", ""))
    return local / "hermes" / "profiles" / "blindwriter" / ".env"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    if (cfg.get("provider"), cfg.get("model")) != (_STAGE.ALLOWED_PROVIDER, _STAGE.ALLOWED_MODEL):
        raise SystemExit(f"formal config must be {_STAGE.ALLOWED_PROVIDER}/{_STAGE.ALLOWED_MODEL}")
    if cfg.get("config_version") != "v5.1-config-4":
        raise SystemExit(f"formal config version must be v5.1-config-4, got {cfg.get('config_version')}")
    return cfg


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
    """Parent-only commandcode/deepseek-v4-flash chat completions (off reasoning).

    Bounded retry for transient upstream 5xx (HTTP 503/524 etc.) so a single
    upstream blip under concurrency does not poison the whole card as BLOCKED.
    Transport-only; no scoring/isolation impact.
    """
    import time as _time
    import urllib.error
    import urllib.request

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
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
        },
    )
    timeout = int(cfg.get("timeout", 180))
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw_bytes = resp.read()
                http_status = resp.status
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 524) and attempt < max_attempts:
                _time.sleep(2 * attempt)
                continue
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


def staging_dir(book_id: str, metric: str, rep: int) -> Path:
    return RUN_DIR / "staging" / book_id / metric / f"rep{rep}"


def is_done(book_id: str, metric: str, rep: int) -> bool:
    """Replay-safe: a terminal scoring verdict (OK/ABSTAIN/FAIL_*/BLOCKED) is done.

    BLOCKED is terminal so a killed run does not re-issue HTTP for cards that
    already hold a recorded verdict; the 3x5 measurement is taken from a fresh
    run dir each time (see --run-id).
    """
    p = staging_dir(book_id, metric, rep) / "output" / "result.json"
    if not p.is_file():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    return data.get("status") in _TERMINAL_STATUSES


_TERMINAL_STATUSES = frozenset(
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


def prepare_card_staging(book: dict, metric: str, rep: int) -> dict[str, Path]:
    """Per-card isolated tree: this book's text, frozen specs, frozen config, output."""
    import shutil

    stage = staging_dir(book["id"], metric, rep)
    text_dir = stage / "text"
    specs_dst = stage / "specs"
    cfg_dst = stage / "config"
    out_dst = stage / "output"
    for d in (text_dir, specs_dst, cfg_dst, out_dst):
        d.mkdir(parents=True, exist_ok=True)
    src_text = ROOT / book["path"]
    dst_text = text_dir / "canonical.txt"
    if not dst_text.exists():
        dst_text.write_text(src_text.read_text(encoding="utf-8"), encoding="utf-8")
    for yaml_path in sorted(SPECS_DIR.glob("*.yaml")):
        dst = specs_dst / yaml_path.name
        if not dst.exists():
            shutil.copy2(yaml_path, dst)
    cfg_dst_file = cfg_dst / "formal_model.yaml"
    if not cfg_dst_file.exists():
        shutil.copy2(CONFIG_PATH, cfg_dst_file)
    return {
        "root": stage,
        "text": dst_text,
        "specs": specs_dst,
        "config": cfg_dst_file,
        "output": out_dst,
    }


def acquire_parent_raw(*, book: dict, metric: str, rep: int, stage: dict, cfg: dict, api_key: str, base_url: str) -> bytes:
    """Real live model call, parent-only (same seam run_dev10 uses)."""
    del rep
    staged_cfg = _STAGE.load_staged_config(stage["config"])
    provider = staged_cfg.get("provider")
    model = staged_cfg.get("model")
    if provider != _STAGE.ALLOWED_PROVIDER or model != _STAGE.ALLOWED_MODEL:
        raise RuntimeError(f"staged config is not {_STAGE.ALLOWED_PROVIDER}/{_STAGE.ALLOWED_MODEL}")
    if not api_key:
        raise RuntimeError("COMMANDCODE_API_KEY missing from blindwriter .env / env")
    call_cfg = dict(staged_cfg)
    call_cfg["temperature"] = 0.0
    call_cfg["top_p"] = 1.0
    call_cfg["seed"] = 0
    text = Path(stage["text"]).read_text(encoding="utf-8")
    spec = load_metric_spec(metric, specs_dir=Path(stage["specs"]))
    prompt = build_prompt(spec, canonicalize(text))
    content, meta = call_commandcode(prompt, call_cfg, api_key, base_url)
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("empty model content")
    return content.encode("utf-8"), meta


def process_card(
    *,
    book: dict,
    metric: str,
    rep: int,
    cfg: dict,
    api_key: str,
    base_url: str,
) -> dict:
    """Stage → live parent raw → atomic write_staged_raw → child (isolated)."""
    stage = prepare_card_staging(book, metric, rep)
    (stage["root"] / "staging_manifest.json").write_text(
        json.dumps(
            {
                "staging_root": str(stage["root"]),
                "text": str(stage["text"]),
                "specs": str(stage["specs"]),
                "config": str(stage["config"]),
                "output": str(stage["output"]),
                "book_id": book["id"],
                "metric_id": metric,
                "rep": rep,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    try:
        raw, meta = acquire_parent_raw(
            book=book, metric=metric, rep=rep, stage=stage,
            cfg=cfg, api_key=api_key, base_url=base_url,
        )
    except Exception as exc:
        rec = {
            "status": "BLOCKED",
            "reason": "parent_transport_failed",
            "error": str(exc)[:800],
            "book_id": book["id"],
            "metric_id": metric,
            "rep": rep,
            "timestamp": utc_now(),
        }
        return _STAGE.write_confined_result(stage["output"], rec)
    raw_path = _STAGE.write_staged_raw(stage["output"], raw)
    try:
        rec = _STAGE.launch_stage_child(
            staging_root=stage["root"],
            book_id=book["id"],
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
            "book_id": book["id"],
            "metric_id": metric,
            "rep": rep,
            "timestamp": utc_now(),
        }
        _STAGE.write_confined_result(stage["output"], rec)
    return rec


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--pending-only", action="store_true")
    p.add_argument(
        "--run-id",
        default=RUN_ID,
        help="Isolate output under runs/<run-id>/; default %(default)s.",
    )
    args = p.parse_args(argv)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    cfg = load_config()
    books = {b["id"]: b for b in manifest["books"]}
    jobs = [(books[b], m, r) for b in BOOKS for m in METRICS for r in REPS]
    assert len(jobs) == EXPECTED_CALLS, f"expected {EXPECTED_CALLS} jobs, got {len(jobs)}"
    missing = [b for b in BOOKS if b not in books]
    if missing:
        print(f"BLOCKED: books not in manifest: {missing}", file=sys.stderr)
        return 2

    if args.run_id and args.run_id != RUN_ID:
        # Rebind module-level RUN_ID/RUN_DIR for isolated run dirs.
        globals()["RUN_ID"] = args.run_id
        globals()["RUN_DIR"] = _EXP / "runs" / args.run_id
    pending = [j for j in jobs if not is_done(j[0]["id"], j[1], j[2])]
    workers = min(max(args.workers, 1), 3)
    print(
        f"run_id={RUN_ID} run_dir={RUN_DIR} jobs={len(jobs)} pending={len(pending)} "
        f"workers={workers} books={list(BOOKS)} metrics={list(METRICS)}",
        flush=True,
    )
    if args.pending_only:
        print(
            json.dumps(
                {"run_id": RUN_ID, "jobs": len(jobs), "pending": len(pending), "http": 0},
                ensure_ascii=False,
            )
        )
        return 0

    api_key = ""
    env = load_dotenv(blindwriter_env_path())
    api_key = env.get("COMMANDCODE_API_KEY") or __import__("os").environ.get("COMMANDCODE_API_KEY")
    if not api_key:
        print("BLOCKED: COMMANDCODE_API_KEY missing from blindwriter .env / env", file=sys.stderr)
        return 2
    base_url = env.get("COMMANDCODE_BASE_URL") or DEFAULT_URL

    t0 = time.monotonic()
    results = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(process_card, book=b, metric=m, rep=r, cfg=cfg, api_key=api_key, base_url=base_url): (b["id"], m, r)
            for b, m, r in pending
        }
        for fut in as_completed(futs):
            bid, metric, rep = futs[fut]
            try:
                rec = fut.result()
            except Exception as exc:
                rec = {"status": "BLOCKED", "book_id": bid, "metric_id": metric, "rep": rep, "error": str(exc)[:800], "reason": "worker_exception"}
                _STAGE.write_confined_result(staging_dir(bid, metric, rep) / "output", rec)
            results.append(rec)
            print(f"{bid} {metric} r{rep} -> {rec.get('status')} score={rec.get('score')}", flush=True)
    elapsed = time.monotonic() - t0

    fan_dest = RUN_DIR / "fan_in_tmp"
    summary = _STAGE.fan_in_staging_outputs(RUN_DIR / "staging", dest_dir=fan_dest)
    summary["run_id"] = RUN_ID
    summary["expected"] = EXPECTED_CALLS
    summary["concurrency"] = {"workers": workers, "elapsed_seconds": round(elapsed, 3), "started_utc": None, "finished_utc": utc_now()}
    (RUN_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    print(f"elapsed_seconds={round(elapsed, 3)} workers={workers}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
