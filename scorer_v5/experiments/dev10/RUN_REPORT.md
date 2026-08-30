# Dev10 r2 scoring run (t_39202394)

run_id: `dev10_v5_r2`
runner: `scorer_v5/experiments/dev10/run_dev10.py`
model_config: `scorer_v5/config/formal_model.yaml` → provider=`minimax-cn` model=`MiniMax-M3` temperature=0.0 top_p=1.0 seed=0

## Pipeline

build_prompt(spec) → HTTP `https://api.minimaxi.com/v1/chat/completions` → raw.txt → `run_card.py` formal=True (zero repair) → per-card provenance.json

Smoke: book 276 × B01 × rep1 first, then 180 with workers=3, skip existing result.json.

## Counts (read back)

- expected 180
- result.json 180
- raw.txt 180
- provenance records 180
- blocked 0
- salvage 0 (formal parse, no fence strip, no smart_fix)
- JSONL keys: id, rep, metric_id, status, score, abstained, provider, model — no tier/reads
- all provenance provider/model = minimax-cn / MiniMax-M3; four hashes + raw_stdout_hash present

## Status mix

- FAIL_PARSE 174 — typical raw starts with markdown ` ```json ` fences; validator rejects (not salvaged)
- ABSTAIN 5
- FAIL_SCHEMA 1
- scores assigned 0

This is engineering output, not model-validation success. GATE comparison is a later step.
