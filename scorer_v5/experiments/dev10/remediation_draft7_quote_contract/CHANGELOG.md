# Dev10 r3 draft-7：最小化 evidence quote 输出规则修复

## 边界
本卡只改 evidence/prompt 输出规则。未改 validator 逐字定位、parser、scoring/ordinal 阈值、指标定义、模型配置语义、canonicalization、正式结果或旧 r3/rerun 产物。未发 HTTP，未重跑 smoke/150 次/C14，未读写凭证。

本卡完成不等于授权新的 smoke 或 150 次扩容；需独立 Reviewer PASS 后另行决定。

## 变更
1. 19 个 active spec 升至 spec-v5.1-draft-7，在 evidence_rule 声明同一套通用 *_quote 输出规则。
2. B01/B33/B36 仅追加指标级短引文约束。
3. runtime/prompts.py 从 spec 渲染「证据引文规则」（不维护并行 quote 规则文本）；PROMPT_VERSION=v5.1-prompt-5。
4. config/formal_model.yaml 同步 prompt/spec 版本（preflight 链）。
5. 新增 scorer_v5/tests/test_quote_contract.py。
6. validate_specs.py 重写 spec_hashes.json。

## Reviewer CHANGES_REQUESTED 修复（本轮）
1. validate_specs.py 不再硬编码 `schema: spec-v5.1-draft-4`；19 个 active spec 必须同一 version，否则 FAIL 且不写清单；通过后 `spec_hashes.json.schema` = 该唯一 version（现为 spec-v5.1-draft-7）。
2. test_quote_contract.py 补全通用「优先最短且足以证明判定的片段」；B01/B33/B36 全部专属条款在 spec 与 generated prompt 双侧断言；并回归检查 spec_hashes.json schema/bytes。
3. smoke_preflight.py 增加 manifest schema 与唯一 spec version 一致性检查。
本轮未重跑 smoke_pipeline（卡片禁止新 smoke）；未改 validator/parser/scoring。

## 测试（本机真实运行，全部 PASS）
- python scorer_v5/scripts/validate_specs.py
- python scorer_v5/tests/test_quote_contract.py
- python scorer_v5/tests/test_contract.py
- python scorer_v5/tests/test_json_fence.py
- python scorer_v5/tests/smoke_preflight.py
（smoke_pipeline 本轮未重跑，见上）

## 旧 r3 产物
scorer_v5/experiments/dev10/runs/dev10_v5_r3/summary.json SHA-256 仍为
d512c171fcdbab67a5be9ec8f6d443d6dde7c922ae2df69b4909f42f94cfd914

## 哈希
见同目录 hashes.json。
