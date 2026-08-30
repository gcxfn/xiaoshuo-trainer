#!/usr/bin/env python3
"""scorer_v5/specs 校验脚本（spec-v5.1-draft-4）

验证（Step 12.5 加强）：
1. specs/ 下恰好 19 个 YAML，metric_id 集合 = 固定 19 指标
2. 每文件使用 v5.1 结构：semantic_outputs / derived_features / score_scale / ordinal_mapping / evidence_rule / abstain_rule / version
3. **拒绝旧结构字段**：llm_tasks / deterministic_inputs / score_rule / required_evidence
4. **拒绝旧 0/5/10 三档**：score_scale.allowed 必须 ⊆ {0,1,3,5,7,9,10} 且非空
5. **LLM 输出层禁止含确定性计算字段**：semantic_outputs 递归扫描 L/K/F/offset/比例/阈值/score
6. **N6/B33 强制 event_schema**，且不含 offset 字段
7. derived_features 每项为单键 dict
8. 版本号必须含 spec-v5.1 或更高
9. **声明式 ordinal_mapping（Step 4）**：每项 {score, when}，when 用 field/op/value；
   allowed == mapping 产出的 score 集（不再"文件写七档实际只出 0/5/10"）
10. 每文件 sha256 记录（Formal Preflight 用）

用法：python validate_specs.py [specs_dir]
退出码：0 = 全部通过；1 = 有错误。
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import sys

try:
    import yaml
except ImportError:
    print("需要 PyYAML: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

SPECS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "specs")
FIXED_ORDER = [
    "B01", "B02", "B03", "C01", "B08", "B09", "B16", "B23", "B30", "B34",
    "B36", "C22", "N3", "N6", "B31", "B33", "C14", "B18", "N7",
]
REQUIRED_FIELDS = [
    "metric_id", "version", "construct", "semantic_definition",
    "semantic_outputs", "derived_features", "score_scale",
    "ordinal_mapping", "evidence_rule", "abstain_rule",
]
OPTIONAL_FIELDS = ["deduplication_rule", "extreme_word_list", "event_schema", "mapping_note"]
ALLOWED = set(REQUIRED_FIELDS) | set(OPTIONAL_FIELDS)

# 旧结构字段（v5.1 必须消失）
FORBIDDEN_OLD_FIELDS = ["llm_tasks", "deterministic_inputs", "score_rule", "required_evidence"]

ALLOWED_SCORES = {0, 1, 3, 5, 7, 9, 10}
VALID_OPS = {"lt", "lte", "gt", "gte", "eq", "ne", "in", "not_in", "is_true", "is_false"}

# LLM 输出层禁止出现的确定性计算词
FORBIDDEN_DETERMINISTIC = [
    "L=", "K=", "F=", "offset", "码点", "比例", "百分比", "阈值",
    "前10%", "后15%", "前500", "score", "分路径", "落档", "0.20", "0.50",
    "0.60", "1.20", "30.00", "15.00", "10.00", "51", "200",
]
CALC_VERBS = ["计算", "记录", "报告", "输出", "数", "估", "判断位置", "码点位置"]


def check_llm_no_deterministic(metric_id: str, semantic_outputs, errors: list[str]) -> None:
    """递归扫描 semantic_outputs 的字段名与值，拒绝出现确定性计算指令。"""
    def walk(node, path=""):
        hits = []
        if isinstance(node, dict):
            for k, v in node.items():
                for w in ["offset", "码点", "比例", "阈值", "score", "0.20", "0.50", "0.60", "1.20", "51", "200", "10%", "15%", "500"]:
                    if w in str(k).lower():
                        hits.append(f"{path}.{k}（字段名含 {w}）")
                if isinstance(v, str):
                    for verb in CALC_VERBS:
                        if verb in v:
                            for w in ["offset", "码点", "比例", "阈值", "score", "L=", "K=", "F="]:
                                if w in v:
                                    hits.append(f"{path}.{k}（值含 {verb}+{w}）")
                                    break
                            break
                walk(v, path + "." + str(k))
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")
        return hits

    hits = walk(semantic_outputs)
    if hits:
        errors.append(f"{metric_id}: semantic_outputs 出现确定性计算字段/词 {hits}（LLM 不得输出 L/K/F/offset/比例/阈值/score）")


def check_declarative_mapping(name: str, om, ss, errors: list[str]) -> None:
    """校验声明式 ordinal_mapping：{score, when}，allowed == 产出集，when 结构合法。"""
    if not isinstance(om, list) or not om:
        errors.append(f"{name}: ordinal_mapping 必须是非空 list")
        return
    produced = set()
    for i, item in enumerate(om):
        if not isinstance(item, dict) or "score" not in item:
            errors.append(f"{name}: ordinal_mapping[{i}] 必须是含 score 的 dict: {item!r}")
            continue
        if not isinstance(item["score"], int) or item["score"] not in ALLOWED_SCORES:
            errors.append(f"{name}: ordinal_mapping[{i}].score 必须是 0/1/3/5/7/9/10 之一: {item.get('score')!r}")
        produced.add(item["score"])
        if "when" not in item:
            continue  # catch-all fallback
        when = item["when"]
        if not isinstance(when, dict):
            errors.append(f"{name}: ordinal_mapping[{i}].when 必须是 dict")
            continue

        def _check_cond(c, where):
            if not isinstance(c, dict) or "field" not in c or "op" not in c:
                errors.append(f"{name}: {where} 条件缺 field/op: {c!r}")
                return
            if c["op"] not in VALID_OPS:
                errors.append(f"{name}: {where} 未知 op {c['op']!r}（允许 {sorted(VALID_OPS)}）")
            if c["op"] not in ("is_true", "is_false") and "value" not in c:
                errors.append(f"{name}: {where} 缺 value: {c!r}")

        def _walk_when(w, where):
            if "and" in w:
                for j, c in enumerate(w["and"]):
                    _walk_one(c, f"{where}.and[{j}]")
            elif "or" in w:
                for j, c in enumerate(w["or"]):
                    _walk_one(c, f"{where}.or[{j}]")
            elif "not" in w:
                _walk_when(w["not"], f"{where}.not")
            else:
                _check_cond(w, where)

        def _walk_one(c, where):
            # 嵌套 and/or/not 树递归；叶子才是 field/op 条件
            if isinstance(c, dict) and "field" not in c and any(k in c for k in ("and", "or", "not")):
                _walk_when(c, where)
            else:
                _check_cond(c, where)

        _walk_when(when, f"ordinal_mapping[{i}].when")

    # allowed == produced（单一规则源，消灭"文件写七档实际只出 0/5/10"）
    if isinstance(ss, dict) and isinstance(ss.get("allowed"), list):
        allowed_set = set(ss["allowed"])
        uncovered = allowed_set - produced
        if uncovered:
            errors.append(f"{name}: score_scale.allowed {sorted(allowed_set)} 未被 ordinal_mapping 覆盖: {sorted(uncovered)}")
        extra = produced - allowed_set
        if extra:
            errors.append(f"{name}: ordinal_mapping 产出 allowed 之外的分值 {sorted(extra)}")


def main() -> int:
    specs_dir = sys.argv[1] if len(sys.argv) > 1 else SPECS_DIR
    files = sorted(glob.glob(os.path.join(specs_dir, "*.yaml")))
    errors: list[str] = []

    if len(files) != 19:
        errors.append(f"YAML 文件数 {len(files)} != 19")

    ids = []
    hashes = {}
    versions: list[str] = []
    for f in files:
        name = os.path.basename(f)[:-5]
        hashes[name] = hashlib.sha256(open(f, "rb").read()).hexdigest()
        try:
            with open(f, encoding="utf-8") as fh:
                d = yaml.safe_load(fh)
        except Exception as e:
            errors.append(f"{name}: YAML 解析失败: {e}")
            continue
        if not isinstance(d, dict):
            errors.append(f"{name}: 顶层不是 dict")
            continue
        mid = d.get("metric_id")
        ids.append(mid)
        if mid != name:
            errors.append(f"{name}: metric_id={mid!r} 与文件名不一致")

        # 1. 必填字段
        missing = [k for k in REQUIRED_FIELDS if k not in d]
        if missing:
            errors.append(f"{name}: 缺 v5.1 必填字段 {missing}")

        # 2. 旧字段禁止
        old = [k for k in FORBIDDEN_OLD_FIELDS if k in d]
        if old:
            errors.append(f"{name}: 出现旧结构字段 {old}（v5.1 必须删除）")

        # 3. 额外顶层字段
        extra = set(d) - ALLOWED
        if extra:
            errors.append(f"{name}: 额外顶层字段 {sorted(extra)}")

        # 4. 版本号
        ver = d.get("version", "")
        if not ver or ("v5.1" not in ver and "spec-v5.1" not in ver):
            errors.append(f"{name}: 版本号必须含 v5.1（当前 {ver!r}）")
        versions.append(ver if isinstance(ver, str) else "")

        # 5. score_scale
        ss = d.get("score_scale")
        if isinstance(ss, dict):
            allowed = ss.get("allowed")
            if not isinstance(allowed, list) or not allowed:
                errors.append(f"{name}: score_scale.allowed 必须是非空数组")
            elif not set(allowed).issubset(ALLOWED_SCORES):
                errors.append(f"{name}: score_scale.allowed 含非 0/1/3/5/7/9/10 值 {allowed}")
        else:
            errors.append(f"{name}: score_scale 结构错误（应为含 allowed 的对象）")

        # 6. semantic_outputs 递归禁确定性
        so = d.get("semantic_outputs")
        if isinstance(so, dict):
            check_llm_no_deterministic(mid, so, errors)
        else:
            errors.append(f"{name}: semantic_outputs 必须是非空 dict")

        # 7. derived_features 单键 dict
        df = d.get("derived_features")
        if not isinstance(df, list) or not df:
            errors.append(f"{name}: derived_features 必须是非空 list")
        else:
            for i, item in enumerate(df):
                if not isinstance(item, dict) or len(item) != 1:
                    errors.append(f"{name}: derived_features[{i}] 必须是单键 dict: {item!r}")

        # 8. 声明式 ordinal_mapping（Step 4 单一规则源）
        check_declarative_mapping(name, d.get("ordinal_mapping"), ss, errors)

        # 9. N6/B33 强制 event_schema，且不含 offset
        if mid in ("N6", "B33"):
            es = d.get("event_schema")
            if not isinstance(es, list) or not es:
                errors.append(f"{name}: N6/B33 必须定义 event_schema")
            else:
                for item in es:
                    if isinstance(item, dict):
                        for k in item.keys():
                            if "offset" in str(k).lower():
                                errors.append(f"{name}: event_schema 不得要求 LLM 报 offset 字段 {k}（offset 由 Python 定位生成）")

    if sorted(ids) != sorted(FIXED_ORDER):
        errors.append(f"metric_id 集合不匹配: {sorted(ids)}")

    unique_versions = sorted(set(versions))
    if len(unique_versions) != 1:
        errors.append(
            f"active specs 必须共用同一 version，当前混用: {unique_versions}"
        )

    if errors:
        print("FAIL:")
        for e in errors:
            print("  -", e)
        return 1

    # 输出 hash 清单（Formal Preflight 用）：schema = 唯一 active spec version
    active_version = unique_versions[0]
    manifest = {"schema": active_version, "specs_sha256": hashes}
    manifest_path = os.path.join(specs_dir, "spec_hashes.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    print(f"PASS: {len(files)} 个 YAML 全部通过 v5.1 校验")
    print(f"spec_hashes.json 已写入: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
