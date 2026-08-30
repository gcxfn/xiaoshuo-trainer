# scorer_v5 指标规格（spec-v5.1）

> **唯一规则源声明**：`scorer_v5/specs/*.yaml` 是 19 项指标的**唯一 active rule source**。
> 评分 prompt 一律从 spec 自动生成；正式运行前必须通过 Formal Preflight
> （`spec_hash → prompt_hash → scoring code version → model config → canonical text hash`，
> 任一不一致直接禁止启动）。不得在 prompt/代码/文档中维护与 spec 并行的第二套规则。

## 结构（v5.1 三层）

每个 YAML 使用以下结构（schema 见 `schema.json`）：

```yaml
metric_id: N6
version: spec-v5.1-draft-1

semantic_outputs:
  # LLM 唯一输出层：只提供语义判断与逐字证据（引文 + 邻近锚点）
  # 严禁出现 L/K/F/offset/比例/阈值/score

derived_features:
  # Python 唯一计算层：全部由程序根据 semantic_outputs + sidecar 产生
  # 含 resolved_offset / N / L / K / F / 比例 / 阈值判定 / 档位计数

score_scale:
  allowed: [0, 1, 3, 5, 7, 9, 10]   # 统一允许评分集合（每指标可只用子集）

ordinal_mapping:
  # 每指标冻结的档位映射（连续原始值始终另外保存）

evidence_rule:   # 引文定位与校验规则
abstain_rule:    # ABSTAIN 处理（不自动转 0，单独统计 abstention_rate）
```

### 关键规则

1. **LLM 输出中不再出现 L、K、F、offset、最终 score。** offset 是程序能百分百确定的东西，
   LLM 只给"逐字引文 + 邻近锚点"，Python 在 canonical text 中定位生成 offset。
2. **`score_scale.allowed` 是统一允许评分集合 0/1/3/5/7/9/10**，但**不强迫每个指标使用全部七档**：
   只有 3 个布尔条件的指标天然只有 4 种状态，硬拆 7 档是伪精确。
   连续型指标（N6/B33/N3 等）保存原始连续值（F/N/K），再映射七档子集。
3. **语义判定（semantic_outputs）与确定性计算（derived_features）严格分离**：
   语义字段（如 core_drive、finale_initiative、escalation、stake_level）属于 semantic_outputs，
   不得混入 derived_features。
4. **职责不重复**：LLM 做选择的地方，Python 不再做选择（如 C14 焦点角色只能由 Python 排序选出；
   LLM 只标块归属）。反之亦然。
5. **N6/B33 事件结构**：LLM 报事件清单（引文+锚点+语义判定，**不含 offset**），
   Python 定位引文生成 offset 后合并去重计数 N。

## 文件索引

| # | metric_id | 构造 | 评分集合 | 连续型? |
|---|---|---|---|---|
| 1 | B01 | 异常事件出现位置 | 七档子集 | 否（q 连续但映射离散） |
| 2 | B02 | 冲突出现速度 | 七档子集 | 否 |
| 3 | B03 | 信息差设置 | 七档子集 | 否 |
| 4 | C01 | 开篇钩子强度 | 七档子集 | 否 |
| 5 | B08 | 主角目标明确度 | 七档子集 | 否 |
| 6 | B09 | 核心冲突强度 | 七档子集 | 否 |
| 7 | B16 | 结尾闭环度 | 七档子集 | 否 |
| 8 | B23 | 主角能动性 | 七档子集 | 否 |
| 9 | B30 | 压抑铺垫充分度 | 七档子集 | 否 |
| 10 | B34 | 大爽点存在 | 七档子集 | 否 |
| 11 | B36 | 共鸣触发器 | 七档子集 | 否 |
| 12 | C22 | 整体质量 | 七档子集 | 否 |
| 13 | N3 | 强情弱写 | 七档子集 | 否 |
| 14 | N6 | 对话潜台词密度 | 七档子集 | ✅ F=N/K 连续 |
| 15 | B31 | 爆发释放强度 | 七档子集 | 否 |
| 16 | B33 | 小爽点密度 | 七档子集 | ✅ F=N/K 连续 |
| 17 | C14 | 代入感综合 | 七档子集 | 否 |
| 18 | B18 | 中段塌陷 | 七档子集 | 否 |
| 19 | N7 | 角色间认知操控 | 七档子集 | 否 |

固定顺序：B01, B02, B03, C01, B08, B09, B16, B23, B30, B34, B36, C22, N3, N6, B31, B33, C14, B18, N7
（顺序是内容属性，按 metric_id 读取，文件系统顺序无关）。

## 版本规则

- 当前版本：`spec-v5.1-draft-2`（2026-08-29，Step 5 前阈值复核修复）。
- 任何规则、阈值、档位映射变更必须升版本（spec-v5.1-draft-3 ...）并在 `项目日志.md` 登记变更原因。
- 旧 v4.0.0 冻结规则见 `scorer_frozen/release_v4/anchor_v4_正式发布.md`（只读，不修改）。

## 校验

```bash
python scorer_v5/scripts/validate_specs.py
```

校验内容（结构 PASS，语义职责冲突靠审查）：
- 恰好 19 个 YAML；metric_id 集合 = 固定 19 指标；metric_id 与文件名一致
- v5.1 必填字段齐全；**旧结构字段（llm_tasks/deterministic_inputs/score_rule）自动拒绝**
- **score_scale.allowed ⊆ {0,1,3,5,7,9,10} 且非空**；拒绝旧三档 {0,5,10}
- semantic_outputs 递归扫描：字段名/指令性值不得含 L/K/F/offset/比例/阈值/score
- N6/B33 强制 event_schema 且不含 offset 字段
- 版本号必须含 v5.1
- 每文件 sha256 写入 `spec_hashes.json`（Formal Preflight 用）
