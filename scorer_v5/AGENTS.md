# AI 小说创作规律模型（番茄短篇）

从 586 本带档位标注（S/A/B/C/小扑/无信号）的番茄短篇语料中，挖掘可验证的商业成功因素，
形成可执行的创作规则库。核心思想：先学会打分，再学会写。

## 关键路径
- 工作区：`D:\AI\workspace\小说训练\`（本目录）
- 正文语料：`corpus\`（586 本 txt，只读，勿改）
- **v5 最新计划（唯一活跃计划）**：`docs\v5\小说商业规律研究与评分器重构完整实施计划 v5.md` + `docs\v5\项目日志.md`（唯一日志）+ `docs\v5\旧数据重新分类登记_v1.md`
- 新评分器开发：`scorer_v5\`（specs\ 19 指标统一规格 + preprocessing\ 文本事实层 + runtime\ 严格解析/四层校验 + scoring\ 确定性评分 + config\ 正式模型冻结 + provenance\ 溯源 + tests\ 边界/冒烟测试；当前唯一活跃代码）
- 冻结参照（只读）：`scorer_frozen\release_v4\`（v4.0.0 发布包）+ `scorer_frozen\release_v4_candidate_v4.1\`（v4.1 候选）
- 历史流程定义：`全流程计划.md`（11 阶段，G0-G4 决策门）
- 切分/特征：`data\split_pilot.csv`(50) / `split_train.csv` / `split_val.csv`（验证集永不触碰）/ `features_a.csv` / `metadata.csv`
- 台账：`判爆扑台账\full_ledger_final.md`（586 本，含档位与在读人数）
- 归档：`archive\`（全部 v3/v4 实验、旧计划、旧评分器、旧 docs、泄漏审计数据，只读审计用）。**历史结论（G2 v1/v2、fresh50、held-out、provenance 等）的原始产物全部在 `archive\` 下，路径形如 `archive\g2_stability_v1\`、`archive\fresh50_scoring_v2\`；正文引用仅作历史描述，实际读取请加 `archive\` 前缀。**

## 固定约束
- 模型不是项目永久固定项；每个具体实验批次必须声明并记录实际 `provider/model/采样参数`，同一稳定性批次内按实验设计保持一致，跨模型实验则显式切换。
- 凭证只允许放在 `blindwriter` profile 的 `.env`，不得写入项目文件或报告。
- 全文语料仅限内部分析，不得传播；创作输出必须原创重组。
- 验证集在全部调参完成前不得触碰。
- B39 已移除，不得进入指标、评分、G2、G3 或写作规则库。
- **唯一规则源（v5.1）**：`scorer_v5/specs/*.yaml` 是 19 项指标的**唯一 active rule source**。评分 prompt 一律从 spec 自动生成；不得在 prompt/代码/文档中维护与 spec 并行的第二套规则。
- **Formal Preflight（正式运行前置检查）**：启动前自动检查 `spec_hash → prompt_hash → scoring code version → model config → canonical text hash` 五者一致，任一不一致直接禁止启动。spec hash 见 `scorer_v5/specs/spec_hashes.json`（validate_specs.py 生成）。
- **统一允许评分集合**：`0/1/3/5/7/9/10`。**2026-08-29 用户裁定：全 19 项 allowed=[0,1,3,5,7,9,10]（计数类指标在冻结 0/10 分支间新增单调细分断点，逐指标 mapping_note 登记，见项目日志 18:40 条目）**；连续型指标保存原始连续值再映射。

## 指标通用性硬约束
- 所有指标的**定义、判定标准、0/5/10 阈值和执行流程必须通用**：不得为单一篇目、单一题材、单一事件或本轮异常结果定制。
- 指标定义必须题材中立、文本中立；评分证据必须可观察、可复核；相同证据在相同规则下必须得到唯一分数。
- 锚点、挑战集和示范例只能解释通用规则，不能替代规则、改变规则或成为隐含例外。
- 发现边界偏离时，先记录为诊断证据；不得直接改写冻结规则。任何规则变更必须升版本、记录变更原因、保留旧版结果，并通过跨题材/跨结构 held-out 复核。
- 单指标问题不得自动推断为全体系问题；但任何一个指标暴露通用性缺口时，必须对当前纳入批次的全部指标执行同一套通用性审计。
- 通用性审计未完成并经独立 reviewer PASS 前，不得启动全量评分、G2 或 G3。

## 盲评分隔离（正式复测强制执行）
- 评分 worker 只能看到：冻结评分指标、指标含义、指标锚点、当前卡指定的正文，以及本卡写入所需的无标签输出文件。
- 不得向评分 worker 暴露或挂载：阅读量、商业档位、标题/作者、切分表、台账、历史评分、模型对比、统计报告或项目根目录。
- 正式复测必须使用逐卡独立 staging root：每卡只挂本卡指定正文、冻结任务书、锚点和本卡独立输出；不得把整个 corpus 或整个 output 目录挂载给 worker。网络、记忆、浏览器、搜索、会话检索与桌面控制继续禁用。
- 评分 JSONL 仅含 `id`、`rep`、五项评分与正文证据；按 `id` 合并真实标签、稳定性分析和效标关联只能在全部盲评分冻结后由 Director/分析流程执行。
- 旧 `writer` 看板及其 `results_retest_rep*.jsonl` 因可读取 `tier/reads/log_reads` 而存在标签泄漏；只保留审计，不得用于正式 G2/G3 或效标结论。
- 当前 `blind_scoring_v4` 批次已暂停；其中间输出只作审计，不得与修复后的正式复测结果混用。

## 当前状态（2026-08-29 19:10；Step 12.5 + 二轮审核五项修复完成：scorer_v5 就绪可进 Dev10）

**Step 12.5 及独立 reviewer 二轮审核五项修复全部完成并全量测试通过**，scorer_v5 进入可正式评分状态。详情见 `项目日志.md` 17:20/18:10/18:20/18:40/19:10 条目。
- **全 19 项完整七档**（用户裁定）：计数类指标用强度字段细分 1/3/5/7/9/10（B08 action_chain_count、B09 idle_gap_ratio、B23 chain_length、B30 event_count、B36 axis_count、B01 q、B02 position_ratio、B03 independent_secret_count、C01 max_quote_offset、C14 x_max_ratio、C22 subplot_count、N3 extreme_word_count、B16 last_5pct、B31 round_count、B34 entity_count、B18 invalid_ratio、N7 plot_count），逐指标 mapping_note 登记"用户裁定全七档"。
- 19 指标 spec 均 **spec-v5.1-draft-4**；声明式 `ordinal_mapping`（`{score, when}`，阈值/断点在 YAML），`score_scale.allowed == 映射产出集`（validate_specs.py 强制）。
- 快照：`scorer_v5/specs_snapshot_draft3/` + `scorer_v5/specs_predeclarative/`。N6/B33/B18 断点与快照核对一致。
- 输出 Schema：prompt/validator/extractor 共用 `derive_output_schema(spec)`；formal 零修复（FAIL_PARSE/FAIL_DUPLICATE_KEY/FAIL_SCHEMA），ABSTAIN 独立；B33 A 证据采用 a_code+a_quote，y_flag/character null 类型修好。
- 关键修复：B09 zero_sum bool、N6 game_goal 分组合并、B33 语义终局（`finale_quote` LLM 输出终局引文，开放结局 null 不排除；A 证据拆为 `a_code+a_quote`）、C14 A/B 限焦点角色 + C 查 c_inner + y_flag 白名单 + X1 由 Python 在选出焦点角色后按 character+block_type 计算、B36 breadth 用已定位轴、schema 漏关键字段 FAIL_SCHEMA（数组项 required 检查 + 可选字段排除）、extractor `_locate` 处理空/歧义引文、Preflight 逐 spec 版本检查。
- provenance 记录模型信息：`model_params`（由本次实际调用显式传入）+ `raw_stdout_hash`（raw 输出 sha256），每条含 provider/model/model_params/prompt_hash/spec_hash/text_hash/sidecar_hash/raw_stdout_hash/parsed/validator/final_score/timestamp。
- 测试入口：`smoke_pipeline.py` / `smoke_preflight.py` / `test_fact_layer.py` / `test_contract.py` / `test_dev10_six.py`（首批 6 指标 B01/B02/N6/B33/C14/B36 × 低/中/高/边界/典型错误）/ `validate_specs.py` — 全 PASS。

## 历史状态（2026-08-29 13:50；第一阶段 Step 1 完成：旧实验最终定性，v4.0 封存）

**决策：按《小说商业规律研究与评分器重构完整实施计划 v5》第一阶段执行。G2 v1/v2 均 FAIL，v4.0 不再进入新正式实验，进入 v5 架构重构。详情见 `项目日志.md`（唯一日志）。**

- **G2 v1：FAIL（0/19）**：`g2_stability_v1/`，prereg SHA `40031139…`，输入 fresh50 v1；三轮全同率实际 **12%–94%**（B33=12% 最差、仅 B36=94% 但退化全同），κ/α 普遍 ≤0.45，345 条高分歧 68% 相邻档 32% 跨两档。
- **G2 v2：FAIL（0/19）**：`g2_stability_v2/`，prereg SHA `bd0be644…`，输入 fresh50 v2（fan-in 150/150）；三轮全同率实际 **12%–98%**（B33=12%、N6=24% 最差；B23=94%/B30=92%/B36=98% 均退化全同）；κ²/ordinal α 普遍 ≤0.45；reviewer run 526 独立复算 PASS + Director 裁定（per_bin 解读 A，对 FAIL 零影响）。
- **G2 v2 实际使用 v4.0.0，不是 v4.1**：fresh50 v2 staging query 引用 `anchor-v4-formal-20260828`，无 v4.1。**不得写"v4.1 正式 G2 失败"**。
- **v4.1 仅通过规则/构造型 held-out（8/8 PASS，152 单元），未做真实长篇模型验证**；从未进入正式 fresh50/G2/G3。
- **v4.0 评分器已确认执行问题**（定量证据见 `项目日志.md`，全部来自 merged.jsonl 实查）：
  - LLM 单次承担语义判断+计数+计算+阈值+打分，无 Python 确定性层；
  - N6/B33 LLM 自估 K/L：reason 含 L=/K=/F= 数值 158/2850（N6=75、B33=82）；含粗估/无可用（reason+evidence 口径）283/2850；显式自估句仅 1 条；
  - reason 断言分值≠score 矛盾 36/2850（B33=12、N6=8…）；单条 reason 双分值 5 条；
  - 原始 JSON 解析分类：strict 120 + smart_fix 28 + salvage 2（rep3/034、rep3/037 连 fix 都不行，经 permissive salvage 发布）；fan-in/qa_validate 用 `_reject_dup` 拒重复键；
  - validator 只查格式（score 枚举、非空、顺序、sha256），不查 reason↔score 语义一致；
  - 正式 G2 provider/route 混用：registry 150 卡 = minimax-cn 59 + commandcode 91；
  - temperature/top_p/seed 无冻结证据（CLI 无参数，复测计划 v1:84,110,202 要求冻结但未执行/未记录）；
  - 19 指标单次处理负担：candidate 内容 min 2764 / median 5965 / max 12664 字符，>5000 占 106/150。
- **v4.0 不再进入新的正式实验**；v4.0/v4.1/fresh50 v1+v2/G2 v1+v2 全部归 Legacy（复盘用），不允许再用于新正式实验。
- **Step 3 已完成并通过 reviewer 复核（PASS with conditions → 修订后通过）**：`scorer_v5/specs/` 19 指标 YAML + schema.json + validate_specs.py（PASS）。阈值/档位语义与 v4.0.0 冻结 anchor 逐字一致（12 项抽查），冻结源 7 文件 hash 全 OK。修订：B03/C14 deterministic_inputs 统一单键 dict、N3 补极限词表、README 路径/表述修正。
- **Step 4 已完成（step4-v5.1-draft-1）**：19 指标拆解表产出（`scorer_v5/docs/step4_拆解表.md`）。**19 项均已尝试操作化，暂不预先归为 SUBJECTIVE**（B09 利害等级、B36 核心驱动、C22 动机一致等是否客观须由 Dev10 → Cross-model → Human-human 验证）。
- **Step 5 前门已完成（2026-08-29 16:20）**：独立 reviewer 四轮复核，19 个 YAML 升级 `spec-v5.1-draft-3`——ordinal_mapping 恢复 v4.0.0 冻结 0/5/10 分支（total+互斥+分支输入等价）；11 个指标的 semantic_outputs/derived_features 恢复冻结定义（B02/B31 round_count≥4 两完整交换、B16 V1=元话语 V2=另起无关新事件、B30 全文克制+两起事实承载、B34 回退选场链、B36 六轴+两主线场景、C22 V1 双分支+≥2 支线+④含交锋回合与不可逆决定、N3 峰值并列候选+冻结词表+主角本体收敛、C14 冻结 C/X/Y、B18 ≥50/≥25 精确阈值、N7 C1–C5 载体+字典序并列留档）。**中间档细分（1/3/7/9）在任何实证验证前不进入正式评分。**
- **Step 5–13 已完成（2026-08-29，第二阶段核心重构）**：`scorer_v5/` 建立 Python 确定性评分栈：
  - **preprocessing/**：canonical text（NFC+BOM+CRLF 归一）+ sidecar（L/K/paragraph/10%/15%/33%/85% 边界）+ 逐字引文定位（歧义拒绝）+ 段落/窗口事实层；
  - **runtime/**：spec 驱动 prompt 生成（LLM 不输出 score/offset/L/K/F）+ 严格 JSON 解析（formal 模式零修复，duplicate key 直接 FAIL）+ 四层 validator（V1 schema/V2 evidence 逐字定位/V3 logic/V4 由程序重算 score，ABSTAIN 不转 0）；
  - **scoring/**：确定性派生特征 + 冻结 ordinal_mapping 执行器（19 指标全部可跑）+ 正式统计（raw_valid/schema/duplicate/evidence/abstain 五率）；
  - **config/formal_model.yaml**：当前实验的 provider/model/采样参数配置（seed_supported 明示；模型不做项目级永久绑定），preflight 五链校验（spec→prompt→code→config→text hash）；
  - **provenance/**：14 字段溯源 registry（run/book/metric/rep/model/prompt_hash/spec_hash/text_hash/sidecar_hash/validator/final_score/timestamp）；
  - **tests/**：事实层边界单测（10/15/33/85% 切点、歧义拒绝、K=L/1000）+ 流水线冒烟（B02 两交换=10、单交换=0、N6 F 落档、ABSTAIN、FAIL_PARSE、FAIL_DUPLICATE_KEY）+ preflight/provenance 冒烟，全部 PASS；`python scorer_v5/scripts/validate_specs.py` PASS（19 文件）。
- 本阶段是历史冻结，不做任何修复；v5 重构（scorer_v5、统一规格、Python 事实层、删 LLM score）自 Step 3 起推进。

## 后续路线
1. ✅ 完成 8 批 held-out 材料（152 单元），每批执行自动闸门和独立 reviewer。
2. ✅ 完成 v4.0.0 发布冻结包与 fresh50 抽样（PASS）。
3. ✅ 完成 v4.1 候选规则 + 变更登记（PASS）与 v4.1 新 held-out 8 批（PASS）。
4. ✅ 完成 fresh50 v2 抽样（PASS）+ staging 构建（PASS）。
5. ✅ fresh50 v2 评分（150/150）→ fan-in 冻结 → **G2 稳定性重测：FAIL（0/19）**（v1/v2 双 FAIL）。
6. ✅ 第一阶段 Step 1 完成：旧实验最终定性（v4.0 封存，`项目日志.md`）。
7. ✅ 第一阶段 Step 2：旧数据重新分类（Legacy / Development 10 本 / Unseen，`docs/旧数据重新分类登记_v1.md`）。
8. ✅ 第二阶段 Step 3：建立 scorer v5 统一指标规格（`scorer_v5/specs/`，19 指标独立 YAML，镜像 v4.0.0 冻结规则）。
9. ✅ 第二阶段 Step 4：逐个拆解 19 指标（`scorer_v5/docs/step4_拆解表.md`，暂不预先归为 SUBJECTIVE）。
10. ✅ **第二阶段 Step 4.5：v5.1 规格收口**（19 YAML 升级 spec-v5.1-draft-1：三层结构 + 统一评分集合 0/1/3/5/7/9/10 + LLM 不报 offset + N6/B33 事件结构 + validator 加强 + 唯一规则源/Formal Preflight 写入约束）。
11. ✅ 第二阶段 Step 5–13：Python 确定性评分栈（preprocessing 事实层 + 严格解析零修复 + 四层 validator + 确定性 ordinal 评分 + 正式模型冻结 + provenance），Step 5 前门（v5.1-draft-3 阈值等价复核）PASS。
12. ✅ **第二阶段 Step 12.5：Dev10 前评分器修正**（spec-v5.1-draft-4）：19 指标七档声明式 ordinal_mapping（`{score, when}` 阈值全进 YAML，ordinal.py 通用解释器）；prompt=validator=extractor 同一 JSON Schema（output_schema.py 从 spec 派生，FAIL_SCHEMA/整数/null/数组推断）；13 指标 Python 确定性重算（B08/B09/B23/B30/B36/N3/C01/B16/C22/B31/C14/B18/N7 不再信任 LLM criteria/item_hits）；validator outcome 状态化（SCHEMA_FAIL/EVIDENCE_FAIL/LOGIC_FAIL/ABSTAIN/OK）+ V3 语义矛盾检查；preflight 加固（temperature/top_p/seed 冻结 + scoring 代码文件 hash + context 预算）；N6/B33/B18 断点与 draft-3 快照核对恢复并登记。测试：smoke_pipeline / smoke_preflight / test_fact_layer / test_contract（19 指标 schema/ABSTAIN/evidence 断言）全 PASS；validate_specs PASS 19 文件。
13. 🔵 第二阶段 Step 14–15：选 10 本旧小说（Dev10 manifest）→ 6 个代表指标 → 每本×每指标 3 次（180 调用）。
- 任一门禁失败、规则缺口未解决或 reviewer 未 PASS，路线停止，不以总体平均抵消。

## 纪律
- 不得编造执行、测试或验收结果；统计结论必须带数值和样本量。
- 不得修改冻结产物或静默改变已授权任务契约；变更必须升版本并保留关联。
- 外部写入和不可逆操作必须先获授权。
- 完成声明必须有真实产物、可复现命令和独立 reviewer/validator 证据。
- 每次项目状态、流程或约束更新后，必须同步维护本文件；不得保留已失效的当前状态。
