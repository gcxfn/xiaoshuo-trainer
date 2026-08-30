# Smoke5 isolation engineering (isolation-remediation-v1)

Date: 2026-08-30
Task: t_443a8061
Mission: dev10-r3-smoke5-isolation-engineering
Scope: `scorer_v5/experiments/dev10/` runner/tests/notes only. No model/API/HTTP. No .env. No new smoke run. No edits to specs/prompt/validator/parser/scorer/preflight/formal_model/corpus/manifest or frozen r3/draft6/draft7 artifacts.

## Reviewer run 570 gaps addressed

1. MiniMax call payload is built only from staged `config/formal_model.yaml` (`stage_only_exec.build_call_payload` / `load_staged_config`). Orchestrator `load_config()` is not the scoring-path source.
2. Card artifacts (`preflight.json`, `prompt.txt`, `call_payload.json`, `raw.txt`, `http_meta.json`, `provenance.json`, `result.json`) are written only under `runs/<run-id>/staging/<book>/<metric>/repN/output/`. `cards/` is no longer the scoring write target. Run-level JSONL/summary remains an explicit later fan-in (`write_summaries` still reads historical `cards/` for frozen runs).
3. Executable boundary: `stage_only_exec.py` CLI/API. Data paths must match `.../staging/<book>/<metric>/repN/{text,specs,config,output}`. Project root, `corpus/`, `data/split_*`, ledger, `cards/`, and historical run roots are rejected. Subprocess `--no-http` never opens a socket. Live HTTP is not implemented inside this module (transport must be injected by the orchestrator; CLI without `--no-http` exits 2).

## Files

- `stage_only_exec.py` — boundary + payload + confined writes
- `run_dev10.py` — `process_card` prepares staging then calls `execute_stage_card`; `is_done` also honors staging `output/result.json` terminal statuses (frozen `cards/` still count)
- `test_stage_only_isolation.py` — offline unit/integration
- this note

## Frozen replay

```
python scorer_v5/experiments/dev10/run_dev10.py --smoke --pending-only --run-id dev10_v5_r3_draft7_smoke
```

Expect `jobs=10 pending=0 http=0`. Does not create staging or HTTP.

Recorded summary SHA-256 (must remain):

- `runs/dev10_v5_r3/summary.json` = `d512c171fcdbab67a5be9ec8f6d443d6dde7c922ae2df69b4909f42f94cfd914`
- `runs/dev10_v5_r3_draft6_rerun/summary.json` = `63b4073a9d6b1f33451055dc0d682043e1b934439bcc9b587c984ece9a78ef65`

## Satisfied vs still required before a new Smoke5 contract

Satisfied (engineering, offline):

- staged-config payload construction
- output confinement to per-card staging `output/`
- reject unapproved data paths with an executable subprocess
- pending-only replay of invalid-for-isolation draft7_smoke without HTTP
- no credentials in argv or project files

Still required (not this card):

- Independent reviewer PASS, then Director authorization
- Explicit new Smoke5 task contract (10 calls)
- Orchestrator-injected transport that still does not pass project-root data paths
- Explicit read-only fan-in from staging `output/` → run-level JSONL (must not write cards during scoring)
- Credential handling remains blindwriter `.env` in the orchestrator only, never in the stage-only argv
- draft7_smoke remains invalid-for-isolation evidence, not a PASS input to Smoke19/150/570

This note does not authorize 10 or 150 model calls.
