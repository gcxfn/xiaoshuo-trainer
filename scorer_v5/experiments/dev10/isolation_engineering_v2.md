# Smoke5 isolation engineering v2 (isolation-remediation-v2-childproc-fanin)

Date: 2026-08-30
Task: t_67adbb1d
Predecessor: t_443a8061 / reviewer t_a20fa278 CHANGES_REQUESTED
Mission: dev10-r3-smoke5-isolation-engineering
Scope: `scorer_v5/experiments/dev10/` runner/child-entry/tests/notes only. No model/API/HTTP. No .env. No new Smoke5. No edits to specs/prompt/validator/parser/scorer/preflight/formal_model/corpus/manifest or frozen r3/draft6/draft7 artifacts.

## Reviewer gaps closed

1. Live scoring path launches a real `subprocess.run` (`launch_stage_child`). Child `cwd` equals that card's staging root. Parent PID != child PID (offline test).
2. Child environment is allowlist-built (`sanitize_child_env`). `HERMES_HOME`, `PYTHONPATH`, credential/project-data keys are stripped. Child re-checks env and cwd (`assert_child_environment`, `assert_cwd_is_staging`). Argv is only the four bundle paths plus ids/flags — no credentials.
3. Child data paths remain the frozen bundle: `text/canonical.txt`, `specs/`, `config/formal_model.yaml`, `output/`.
4. All card-level terminals write `output/result.json` only (`write_confined_result`). ThreadPool exceptions no longer write `cards/`. Mapping: preflight → BLOCKED/preflight_failed; child launch/exit → BLOCKED/child_*; parse/schema via run_card; transport exception → BLOCKED/llm_call_failed; ABSTAIN/EVIDENCE_FAIL/LOGIC_FAIL via `classify_status` (same result writer).
5. Scoring path fan-in is `fan_in_staging_outputs` (read-only glob `staging/*/*/rep*/output/result.json` + sibling provenance). Deterministic sort + identity dedup. Does not read/write `cards/`. `write_summaries` is not called after jobs.

## Frozen replay (unchanged)

```
python scorer_v5/experiments/dev10/run_dev10.py --smoke --pending-only --run-id dev10_v5_r3_draft7_smoke
```

Expect `jobs=10 pending=0 http=0`.

Recorded summary SHA-256 (must remain):

- `runs/dev10_v5_r3/summary.json` = `d512c171fcdbab67a5be9ec8f6d443d6dde7c922ae2df69b4909f42f94cfd914`
- `runs/dev10_v5_r3_draft6_rerun/summary.json` = `63b4073a9d6b1f33451055dc0d682043e1b934439bcc9b587c984ece9a78ef65`

## Known limits (not this card)

- Child `--no-http` does not perform MiniMax calls. Future live HTTP must stay in the orchestrator (blindwriter `.env` only) and must not put credentials in child argv/env. Optional later: parent writes staged `raw.txt`, child `--raw-file` under staging.
- This card done ≠ Smoke5 authorization. Director must create an independent read-only reviewer card.
- draft7_smoke remains invalid-for-isolation evidence.

This note does not authorize 10 or 150 model calls.
