# DEV10_GATE_v5

> 冻结时间：看结果之前（Step 18 预注册）。
> 依据：`docs/v5/小说商业规律研究与评分器重构完整实施计划 v5.md` Step 18；书目 `scorer_v5/experiments/dev10/dev10_manifest.json`（manifest_id=`dev10_v5_r1`）。
> 本文件不填入任何实测分数、κ、全同率或工程率。Dev10 成功 ≠ 模型验证成功。

适用范围：10 本 × 6 指标（B01, B02, N6, B33, C14, B36）× 3 次 = 180 次调用，全部完成后对照本闸门，不得事后改阈值。

---

## 工程层

在看到 Dev10 结果前冻结以下五项（对照计划 Step 18）：

1. **duplicate key = 0**  
   formal 模式零修复；重复键直接 FAIL_DUPLICATE_KEY，不得 salvage。

2. **score/reason contradiction = 0**  
   因为 score 已由 Python 确定性层重算，LLM 不得输出 score。

3. **数学落档错误 = 0**  
   ordinal_mapping 由程序执行；派生特征与档位必须可复算一致。

4. **evidence offset 错误接近 0**  
   引文必须逐字可定位；歧义拒绝，不得猜 offset。

5. **raw JSON 合法率目标 ≥98%**  
   合法 = 严格解析通过（非 FAIL_PARSE / FAIL_DUPLICATE_KEY / FAIL_SCHEMA）。ABSTAIN 单独计，不计入“非法 JSON”，也不转 0。

未达到工程层硬项（1–3 非零，或合法率显著低于目标且不可解释为环境故障）时，不得把 Dev10 解读为 GREEN。

---

## 重复性层

每个指标必须记录（计算在全部 180 次冻结之后，本文件不预填数值）：

- 三轮全同率
- pairwise exact
- weighted κ
- semantic field agreement
- event-level agreement（对 N6/B33 等事件结构指标）

此处先不宣布“正式通过”。Dev10 只分 GREEN / YELLOW / RED，不是 G2/G3。

---

## GREEN

明显改善，可以进入正式 reliability（后续独立批次，不得用 Dev10 当 G3/效标）。

示意（冻结口径，非事后拟合）：工程层 1–3 为 0；raw JSON 合法率达到目标；重复性相对 v4.0 G2 同指标有可指出的改善，且问题不表现为同一本书事件定义完全不同或 evidence 大幅漂移。

## YELLOW

存在集中、可解释的问题，只允许再修改一次（单指标：一轮 v5 初版 + 一轮针对性修正）。

示意：工程层基本达标，但个别指标重复性差且可归因于已知操作化缺口（非全体系崩溃）。

## RED

仍严重随机，不继续救。该指标 DROP 或重新定义。

示意：第二轮后仍大量出现——同一本事件定义完全不同；evidence 大幅漂移；语义判断随机；最终 score 一致率很低。

---

## 停止规则（Step 19，预注册）

单指标最多允许：一轮 v5 初版 + 一轮针对性修正。超此预算不得继续调参。

Development 上的任何颜色判定必须标注 “Development-only，需 Unseen/新 fresh 验证”。
