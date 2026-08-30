# Smoke5 isolation engineering v4 (parent handoff + atomic raw)

Date: 2026-08-30
Task: t_02a64094
Predecessor: t_36308ec2 / reviewer t_e93e9d7d CHANGES_REQUESTED
Mission: dev10-r3-smoke5-isolation-engineering
Revision: isolation-remediation-v4-parent-handoff-atomic-raw
Scope: `scorer_v5/experiments/dev10/` runner/child/tests/notes only. No model/API/HTTP. No .env. No new Smoke5. No edits to specs/prompt/validator/parser/scorer/preflight/formal_model/corpus/manifest or frozen r3/draft6/draft7 artifacts.

## Reviewer gaps closed

1. `process_card` now goes through an injectable parent acquisition seam (`acquire_parent_raw`). Default is `offline_acquire_parent_raw`: returns None, reads no `.env`, opens no HTTP. On success it calls `write_staged_raw` then launches a real stage child. Missing transport writes `BLOCKED/parent_missing_raw`; transport exceptions write `BLOCKED/parent_transport_failed` — both confined to this card `output/result.json`. This card does not call `call_minimax`.

2. `write_staged_raw` writes a same-directory tempfile (`tempfile.mkstemp`) then `os.replace` onto `output/raw.txt`. Bytes are unchanged. Tests cover leftover `.tmp` absence and raw SHA-256 invariance across parent→child handoff.

## What this card did not do

This engineering card did not perform or verify real credential/network MiniMax calls. Future live HTTP must stay in an authorized parent that returns raw bytes into the same `acquire_parent_raw` seam, then the existing atomic write + child launch. This card does not authorize Smoke5 / Smoke19 / 150 / 570 / C14.

## Frozen replay

```
python scorer_v5/experiments/dev10/run_dev10.py --smoke --pending-only --run-id dev10_v5_r3_draft7_smoke
```

draft7_smoke has 10 cards results and **no** staging `output/result.json`. After removing the cards fallback, this prints `jobs=10 pending=10 http=0`.

Recorded summary SHA-256 (must remain):

- `runs/dev10_v5_r3/summary.json` = `d512c171fcdbab67a5be9ec8f6d443d6dde7c922ae2df69b4909f42f94cfd914`
- `runs/dev10_v5_r3_draft6_rerun/summary.json` = `63b4073a9d6b1f33451055dc0d682043e1b934439bcc9b587c984ece9a78ef65`
