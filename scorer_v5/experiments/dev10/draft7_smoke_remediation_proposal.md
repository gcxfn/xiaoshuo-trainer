# Draft-7 smoke reviewer findings — offline audit + remediation proposal

Date: 2026-08-30
Authority: DIRECTOR CONTRACT CORRECTION 2026-08-30 10:41 UTC+8
Scope: executor run 565 offline only. No model/API. No replacement smoke. No overwrite of `dev10_v5_r3_draft7_smoke`. No acceptance claim.

## Audit of existing run (invalid-for-isolation)

Path: `scorer_v5/experiments/dev10/runs/dev10_v5_r3_draft7_smoke`
Disposition: retained as audit artifact only. Not Smoke5 PASS. Not an input to Smoke19 / 150 / 570.

Finding 1 (AC3, confirmed): no `staging/` tree under that run root. Runner previously read manifest/corpus/specs/config from project root and passed those paths into preflight/run_card.

Finding 2 (AC2/AC8, confirmed): `is_done` originally omitted `EVIDENCE_FAIL` and `LOGIC_FAIL`. Four EVIDENCE_FAIL cards would have been pending on replay.

## Engineering already present (runner only)

File: `scorer_v5/experiments/dev10/run_dev10.py` (not specs/prompt/validator/parser/scorer/formal_model/corpus).

- `TERMINAL_STATUSES` includes EVIDENCE_FAIL, LOGIC_FAIL, SCHEMA_FAIL.
- `prepare_card_staging` copies one book text + frozen specs yaml + formal_model.yaml into `runs/<id>/staging/<book>/<metric>/repN/`; preflight/run_card use those paths.
- `--pending-only` computes pending with no HTTP and no `.env` read.

## No-network verification (executed)

```
python scorer_v5/experiments/dev10/run_dev10.py --smoke --pending-only --run-id dev10_v5_r3_draft7_smoke
```

Result: jobs=10, pending=0, http=0.
Old r3 summary SHA-256: d512c171fcdbab67a5be9ec8f6d443d6dde7c922ae2df69b4909f42f94cfd914
Old draft6 summary SHA-256: 63b4073a9d6b1f33451055dc0d682043e1b934439bcc9b587c984ece9a78ef65
Existing run `staging_root_present=False` (unchanged).

## No-network test plan (for independent review of engineering)

1. Re-run `--pending-only` on frozen draft7_smoke; assert pending=0 and no files under that run mtime-changed except none.
2. Unit: synthetic result.json with status EVIDENCE_FAIL / LOGIC_FAIL / OK / FAIL_PARSE → is_done True; missing file → False.
3. Dry staging: call `prepare_card_staging` in a temp RUN_DIR (not draft7_smoke); assert tree contains only text/specs/config/output; no ledger/split/tier fields; specs yaml count == 19.
4. Do not call MiniMax. Do not write into r3, draft6, or draft7_smoke.

## Out of this card

A new isolated Smoke5 rerun requires a **fresh task contract** and **explicit user authorization** after this engineering is independently reviewed. This proposal does not authorize 10 or 150 calls.
