# Smoke5 isolation engineering v3 (staged-raw child lifecycle)

Date: 2026-08-30
Task: t_36308ec2
Predecessor: t_67adbb1d / reviewer t_362bf56a CHANGES_REQUESTED
Mission: dev10-r3-smoke5-isolation-engineering
Scope: `scorer_v5/experiments/dev10/` runner/child/tests/notes only. No model/API/HTTP. No .env. No new Smoke5. No edits to specs/prompt/validator/parser/scorer/preflight/formal_model/corpus/manifest or frozen r3/draft6/draft7 artifacts.

## Reviewer gaps closed

1. Isolated `is_done()` / pending selection reads only this card's staging `output/result.json` strict terminals. `RUN_DIR/cards/.../result.json` is never a fallback. Legacy cards OK + missing staging result → still pending.

2. Parent→child raw handoff: the only authorized raw source is bytes already obtained by a controlled parent. Parent writes them unchanged to this card `output/raw.txt` (no smart-fix). Child reads `--raw-file output/raw.txt` plus staged text/specs/config and writes parser/validator/deterministic score/provenance/result under the same output/.

3. `launch_stage_child` uses real `subprocess.run`, cwd=stage root, allowlist env, relative bundle argv (`--staging-root .`, `text/canonical.txt`, `specs`, `config/formal_model.yaml`, `output`, `output/raw.txt`). No credentials in argv/env. Child `--no-http` never opens a socket and never requires `.env`.

4. Missing raw is `BLOCKED/missing_raw` or parent `BLOCKED/parent_missing_raw` — not `PAYLOAD_ONLY` as a fake scoring terminal. Parent launch/timeout and child missing result write the same confined `output/result.json`.

5. Fan-in remains read-only from staging `output/result.json` + sibling provenance. Does not read cards/.

## What this card did not do

This engineering card did not perform or verify real credential/network MiniMax calls. Future live HTTP must stay in the authorized parent (blindwriter `.env` only), write `output/raw.txt`, then launch the child. This card does not authorize Smoke5 / Smoke19 / 150 / 570 / C14.

## Frozen replay

```
python scorer_v5/experiments/dev10/run_dev10.py --smoke --pending-only --run-id dev10_v5_r3_draft7_smoke
```

draft7_smoke has 10 cards results and **no** staging `output/result.json`. After removing the cards fallback, this prints `jobs=10 pending=10 http=0` — the cards-only tree no longer counts as done. That is the v3 pending-only proof, not a regression.

Recorded summary SHA-256 (must remain):

- `runs/dev10_v5_r3/summary.json` = `d512c171fcdbab67a5be9ec8f6d443d6dde7c922ae2df69b4909f42f94cfd914`
- `runs/dev10_v5_r3_draft6_rerun/summary.json` = `63b4073a9d6b1f33451055dc0d682043e1b934439bcc9b587c984ece9a78ef65`
