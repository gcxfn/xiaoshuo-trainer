# AI 小说创作规律模型（番茄短篇）

从 586 本带商业档位标注的内部短篇语料中，提炼可验证的商业成功因素，并先建立可靠评分器，再转化为创作规则。

## 活跃来源与目录

- 活跃计划与唯一活跃日志：`docs/v5/小说商业规律研究与评分器重构完整实施计划 v5.md`、`docs/v5/项目日志.md`
- 活跃评分器：`scorer_v5/`
- 19 项唯一规则源：`scorer_v5/specs/*.yaml`
- 正文语料：`corpus/`，只读；不得传播全文。
- 数据切分：`data/split_train.csv`、`data/split_val.csv`；验证集在调参结束前不得读取或使用。
- 冻结参照：`scorer_frozen/`，只读。
- 历史实验与旧结论：`archive/`，只读审计；不得作为新正式实验输入。
- 完整历史日志归档：`archive/v5_logs/项目日志_原始详细版_20260830.md`。

## 当前工作边界

- 活跃阶段：Dev10 r3 的最小可运行性门禁。具体 run、卡片、阻塞与恢复条件只记录在 `docs/v5/项目日志.md`，不得在本文件重复易过期状态。
- Smoke19、150、570、C14 真实评分必须以项目日志中的明确授权与门禁为准；没有明确授权不得启动。
- `B39` 已移除，不得进入指标、评分、G2/G3 或写作规则库。
- v4/v4.1、fresh50、旧 G2 与旧 Dev10 仅保留复盘价值，不得重新作为正式结论。

## 不可违反的评分规则

- 正式路线固定 `commandcode/deepseek/deepseek-v4-flash`（reasoning_mode=low）；禁止使用 `minimax` provider 作为正式评分路线。
- 凭证仅可位于 `blindwriter` profile 的 `.env`；不得读取、打印、复制或写入项目文件、日志、包或报告。
- 全 19 项分值集合固定为 `0/1/3/5/7/9/10`；连续指标保留原始连续值后映射。
- prompt、validator、extractor 必须从同一 spec 派生；禁止维护并行规则、阈值或评分 prompt。
- Formal Preflight 必须校验 `spec_hash → prompt_hash → scoring code version → model config → canonical text hash`；任一不一致即禁止运行。
- 正式模式严格解析：不 smart-fix、不 salvage、重复键直接失败；`ABSTAIN` 不得转为 0。
- Python 负责确定性特征、阈值和最终分数；LLM 不得输出 score、L/K/F、offset 或码点位置。

## 盲评分隔离

- 每张正式评分卡使用独立 staging root；worker 只能看见本卡正文、冻结任务书/锚点和本卡输出。
- worker 不得访问项目根、全 corpus、台账、切分、标题/作者、历史评分、统计报告、网络、记忆、浏览器或桌面控制。
- 评分 JSONL 只含 `id`、`rep`、评分与正文证据；标签合并、统计与效标分析只能在全部盲评分冻结后进行。
- 旧泄漏输出和旧 `cards/` 目录只作审计，绝不混入新结果。

## 验证入口

从项目根目录执行：

```bash
python scorer_v5/scripts/validate_specs.py
python scorer_v5/tests/smoke_preflight.py
python scorer_v5/tests/test_contract.py
python scorer_v5/tests/test_quote_contract.py
python scorer_v5/tests/test_quote_bind.py
python scorer_v5/tests/smoke_pipeline.py
python scorer_v5/tests/test_fact_layer.py
python scorer_v5/tests/test_dev10_six.py
python scorer_v5/experiments/dev10/test_stage_only_isolation.py
```

完成声明必须包含真实产物、实际命令结果和相应的独立审查/Director 验收证据；不能以执行器自报代替验收。

## 修改纪律

- 先读相关文件和调用路径，保持最小修改；不修改冻结产物。
- specs、prompt、评分、parser、validator、preflight、模型配置或隔离边界的实质变更必须升版本、记录变更原因、保留旧结果，并完成跨题材/结构复核。
- 任何影响正式模型调用、隔离、范围、成本或验收的长期任务，必须由 Kanban 管理；Kanban 是其唯一状态真相源。
- 本文件只保存稳定的项目规则、目录和命令。状态变化写入 `docs/v5/项目日志.md`；稳定规则变化才同步更新本文件。
