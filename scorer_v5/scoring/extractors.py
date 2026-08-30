"""Per-metric derivation: validated semantic facts + sidecar → derived context.

Each extractor implements the frozen ``derived_features`` contract of its
spec: Python resolves quote evidence to offsets, computes counts/ratios/
windows, and hands the ordinal mapping the exact booleans/values it declares.
The LLM never computes any of these.
"""
from __future__ import annotations

import re

from typing import Any

from ..preprocessing.offsets import QuoteLocation, locate_quote
from ..preprocessing.windows import canonical_index_for_content_offset
from ..runtime.specs import MetricSpec
from ..runtime.validation import ValidationResult
from .derived import DerivedContext

# Scene approximation for C14 focal-character ranking: blocks whose canonical
# paragraphs are adjacent (or overlapping) belong to one scene; a paragraph
# index jump > 1 starts a new scene (mirrors the global 同一时空切场 rule).
_C14_FOCAL_TYPES = {"直接感知", "想法"}


def _locate(text: str, quote: str, offsets: list[int], anchor: str | None = None) -> QuoteLocation | None:
    if not quote:
        return None
    # 歧义引文（无锚点无法唯一定位）视为定位失败 → 不计（V2 已在 validation 层报 EVIDENCE_FAIL）
    try:
        return locate_quote(text, quote, nearby_anchor=anchor, offsets=offsets)
    except ValueError:
        return None


def _quote_content_len(loc: QuoteLocation) -> int:
    return max(0, loc.content_end - loc.content_start)


def _merge_intervals(intervals: list[tuple[int, int]], *, same_key: bool = True) -> int:
    """Merge overlapping/adjacent intervals; count merged groups."""
    if not intervals:
        return 0
    ordered = sorted(intervals)
    merged = 0
    cur_start, cur_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= cur_end:
            cur_end = max(cur_end, end)
        else:
            merged += 1
            cur_start, cur_end = start, end
    return merged + 1


def derive_context(
    spec: MetricSpec,
    result: ValidationResult,
    canonical_text: str,
    sidecar,
) -> DerivedContext:
    ctx = DerivedContext()
    mid = spec.metric_id
    if result.parsed.value is None:
        return ctx
    semantic = result.parsed.value.get("semantic", {}) or {}
    offsets = [0]
    from ..preprocessing.offsets import content_offsets
    offsets = content_offsets(canonical_text)
    L = sidecar.L

    if mid == "B01":
        candidates = semantic.get("candidates", []) or []
        located: list[tuple[QuoteLocation, dict[str, Any]]] = []
        for cand in candidates:
            loc = _locate(canonical_text, cand.get("event_quote", ""), offsets, cand.get("nearby_anchor"))
            if loc is None:
                continue
            if cand.get("qualifies") is True:
                located.append((loc, cand))
        located.sort(key=lambda pair: pair[0].content_start)
        if not located:
            ctx.set("event_count", 0)
            ctx.set("q", 1.0)
            ctx.set("q_le_10", False)
            ctx.set("paragraph_ok", False)
            ctx.set("action_in_scene", False)
            return ctx
        loc, cand = located[0]
        q = loc.content_start / L if L else 1.0
        ctx.set("event_count", len(located))
        ctx.set("q", q)
        ctx.set("q_le_10", q <= 0.10)
        paragraph_ok = _paragraph_ok(loc, sidecar, 3)
        ctx.set("paragraph_ok", paragraph_ok)
        action_loc = None
        if cand.get("same_scene_action") is True:
            action_loc = _locate(canonical_text, cand.get("action_quote", ""), offsets)
        action_in_scene = bool(action_loc is not None and _same_scene(loc, action_loc, sidecar))
        ctx.set("action_in_scene", action_in_scene)
        # ①②③ 各自成立（Python 计算，不信任 LLM 汇总）
        hits = int(paragraph_ok) + int(action_in_scene) + int(q <= 0.10)
        ctx.set("item_hits_count", hits)
        return ctx

    if mid == "B02":
        conflicts = semantic.get("conflicts", []) or []
        located: list[tuple[QuoteLocation, dict[str, Any]]] = []
        for cand in conflicts:
            r1 = _locate(canonical_text, cand.get("round1_quote", ""), offsets, cand.get("nearby_anchor"))
            r2 = _locate(canonical_text, cand.get("round2_quote", ""), offsets, cand.get("nearby_anchor"))
            if r1 is None or r2 is None:
                continue
            if not (r1.content_start < r2.content_start):
                continue
            r3 = _locate(canonical_text, cand.get("round3_quote", ""), offsets) if cand.get("round3_quote") else None
            r4 = _locate(canonical_text, cand.get("round4_quote", ""), offsets) if cand.get("round4_quote") else None
            if r3 is not None and not (r2.content_start < r3.content_start):
                continue
            if r4 is not None and not (r3.content_start < r4.content_start):
                continue
            round_count = 2 + (1 if r3 else 0) + (1 if r4 else 0)
            if round_count < 4:
                continue  # frozen: at least two complete exchanges
            located.append((r1, cand))
        located.sort(key=lambda pair: pair[0].content_start)
        if not located:
            ctx.set("qualified", False)
            ctx.set("position_ratio", 1.0)
            ctx.set("first_round_le_500", False)
            ctx.set("same_lineage", False)
            return ctx
        r1, cand = located[0]
        ratio = r1.content_start / L if L else 1.0
        qualified = bool(cand.get("qualifies"))
        first_500 = r1.content_start <= 500
        lineage = bool(cand.get("same_lineage"))
        ctx.set("qualified", qualified)
        ctx.set("position_ratio", ratio)
        ctx.set("first_round_le_500", first_500)
        ctx.set("same_lineage", lineage)
        # ②③ 判定项（Python）：≤500 与同源；①位置 ≤15% 由 position_ratio 承载
        ctx.set("b02_hits", int(first_500) + int(lineage))
        return ctx

    if mid == "B03":
        secrets = semantic.get("secrets", []) or []
        independent = sum(1 for s in secrets if s.get("is_independent") is True)
        c1 = independent >= 2
        c2 = any(s.get("bottom_card_held") is True for s in secrets)
        c3 = any(s.get("reveal_turns_mainline") is True for s in secrets)
        ctx.set("c1", c1)
        ctx.set("c2", c2)
        ctx.set("c3", c3)
        ctx.set("independent_secret_count", independent)
        ctx.set("criterion_count", int(c1) + int(c2) + int(c3))
        return ctx

    if mid == "C01":
        items = semantic.get("items", []) or []
        item = items[0] if items else {}
        # 四项判定全部 Python 重算：引文定位 + 前 500 非空白码点窗口，绝不信任 LLM 的 item_hits。
        def _in_500(quote: str) -> bool:
            if not quote:
                return False
            loc = _locate(canonical_text, quote, offsets)
            return loc is not None and loc.content_start < 500

        item1 = _in_500(item.get("suspense_question_quote", ""))
        item2 = _in_500(item.get("high_concept_quote", ""))
        item3 = _in_500(item.get("pressure_quote", ""))
        # ④两条线索都落在前 500（后文解答句允许在前 500 之后，Python 只校验其存在）
        item4 = _in_500(item.get("identity_clue_quote", "")) and _in_500(item.get("conflict_clue_quote", ""))
        ctx.set("item_count", int(item1) + int(item2) + int(item3) + int(item4))
        # 窗口内引文最大位置（7/9/10 细分依据：4 项全成立时按最大位置切 9/10）
        max_off = -1
        for q in ("suspense_question_quote", "high_concept_quote", "pressure_quote", "identity_clue_quote", "conflict_clue_quote"):
            if item.get(q):
                loc = _locate(canonical_text, item.get(q, ""), offsets)
                if loc is not None and loc.content_start < 500:
                    max_off = max(max_off, loc.content_start)
        ctx.set("max_quote_offset", max_off)
        ctx.set("has_window_quote", max_off >= 0)
        return ctx

    if mid == "B08":
        goals = semantic.get("goals", []) or []
        core = next((g for g in goals if g.get("is_core") is True), None)
        goal_in_first_third = False
        if core is not None:
            loc = _locate(canonical_text, core.get("goal_quote", ""), offsets)
            goal_in_first_third = loc is not None and loc.content_start < sidecar.first_third_end
        # ②行动链：action_quote 可定位后计数（Python 判定 ②≥3）
        chain_count = 0
        for act in (core.get("chain_actions") or []) if core is not None else []:
            if not isinstance(act, dict):
                continue
            if _locate(canonical_text, act.get("action_quote", ""), offsets) is not None:
                chain_count += 1
        # ③因果自主：转折因果句可定位（主角行动直接促成）
        causal_located = _locate(canonical_text, core.get("causal_turn_quote", ""), offsets) is not None if core is not None else False
        ctx.set("goal_in_first_third", goal_in_first_third)
        ctx.set("action_chain_count", chain_count)
        ctx.set("causal_quote_located", causal_located)
        ctx.set("criterion_count", int(goal_in_first_third) + int(chain_count >= 3) + int(causal_located))
        return ctx

    if mid == "B09":
        main_conflict = (semantic.get("main_conflict") or [{}])[0]
        # ①利害≥L3：LLM 判 L 级，Python 布尔校验 + conflict_quote 可定位
        conflict_loc = _locate(canonical_text, main_conflict.get("conflict_quote", ""), offsets)
        stake_ge_l3 = conflict_loc is not None and main_conflict.get("stake_level") == "L3"
        # ②零和：LLM 判定，Python 校验 zero_sum_quote 可定位
        zero_sum_loc = _locate(canonical_text, main_conflict.get("zero_sum_quote", ""), offsets)
        zero_sum_flag = main_conflict.get("zero_sum") is True and zero_sum_loc is not None
        # ③ 贯穿：最大单一连续无冲突区段 / L ≤ 30.00%（不把分离区段相加）
        longest = 0.0
        for seg in main_conflict.get("idle_segments", []) or []:
            if not isinstance(seg, dict):
                continue
            s = _locate(canonical_text, seg.get("start_quote", ""), offsets)
            e = _locate(canonical_text, seg.get("end_quote", ""), offsets)
            if s is not None and e is not None:
                longest = max(longest, max(0, e.content_end - s.content_start))
        idle_gap_ratio = longest / L if L else 1.0
        ctx.set("idle_gap_ratio", idle_gap_ratio)
        ctx.set("stake_ge_l3", stake_ge_l3)
        ctx.set("zero_sum_flag", zero_sum_flag)
        ctx.set("criterion_count", int(stake_ge_l3) + int(zero_sum_flag) + int(idle_gap_ratio <= 0.30))
        return ctx

    if mid == "B23":
        actions = semantic.get("actions", []) or []
        # ①主动行动：action_quote 与 observable_result 均可定位才计数
        located_actions: list[dict[str, Any]] = []
        for act in actions:
            if not isinstance(act, dict):
                continue
            a = _locate(canonical_text, act.get("action_quote", ""), offsets)
            r = _locate(canonical_text, act.get("observable_result", ""), offsets)
            if a is not None and r is not None:
                located_actions.append(act)
        action_count = len(located_actions)
        # ②递进链：LLM 的 chain_link 序列，Python 算最长连续真链
        longest_chain = 0
        run = 0
        for act in located_actions:
            if act.get("chain_link") is True:
                run += 1
                longest_chain = max(longest_chain, run)
            else:
                run = 0
        # ③终局主动：任一行动携带的 finale_initiative_quote 可定位
        finale_located = any(
            _locate(canonical_text, act.get("finale_initiative_quote", ""), offsets) is not None
            for act in actions
            if isinstance(act, dict) and act.get("finale_initiative_quote")
        )
        ctx.set("action_count", action_count)
        ctx.set("chain_length", longest_chain)
        ctx.set("finale_quote_located", finale_located)
        ctx.set("criterion_count", int(action_count >= 5) + int(longest_chain >= 2) + int(finale_located))
        return ctx

    if mid == "B30":
        events = semantic.get("events", []) or []
        located_events: list[tuple[QuoteLocation, dict[str, Any]]] = []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            e = _locate(canonical_text, ev.get("event_quote", ""), offsets)
            s = _locate(canonical_text, ev.get("state_before", ""), offsets)
            a = _locate(canonical_text, ev.get("state_after", ""), offsets)
            if e is not None and s is not None and a is not None:
                located_events.append((e, ev))
        event_count = len(located_events)
        # ②升级：escalation_type 非空 + escalation_prev_quote 可定位
        escalation_flag = False
        for _, ev in located_events:
            if ev.get("escalation_type"):
                if _locate(canonical_text, ev.get("escalation_prev_quote", ""), offsets) is not None:
                    escalation_flag = True
                    break
        # ③克制呈现：候选块 ≥51 非空白码点才计块，全文 ≤2 块；且 ≥2 起事件主要证据为事实
        catharsis_count = 0
        seen_blocks: set[int] = set()
        for _, ev in located_events:
            for q in ev.get("catharsis_block_quotes", []) or []:
                loc = _locate(canonical_text, q, offsets)
                if loc is not None and _quote_content_len(loc) >= 51 and loc.content_start not in seen_blocks:
                    seen_blocks.add(loc.content_start)
                    catharsis_count += 1
        fact_carried = sum(1 for _, ev in located_events if ev.get("primary_evidence") == "fact")
        catharsis_ok = catharsis_count <= 2 and fact_carried >= 2
        ctx.set("event_count", event_count)
        ctx.set("escalation_flag", escalation_flag)
        ctx.set("catharsis_block_count", catharsis_count)
        ctx.set("fact_carried_count", fact_carried)
        ctx.set("criterion_count", int(event_count >= 3) + int(escalation_flag) + int(catharsis_ok))
        return ctx

    if mid == "B36":
        axes = semantic.get("axes", []) or []
        seen: set[str] = set()
        axis_entries: list[tuple[QuoteLocation | None, dict[str, Any]]] = []
        for ax in axes:
            if not isinstance(ax, dict):
                continue
            label = str(ax.get("axis", ""))
            if label not in {"P1", "P2", "P3", "P4", "P5", "P6"} or label in seen:
                continue  # Python 校验枚举 + 互斥去重
            seen.add(label)
            loc = _locate(canonical_text, ax.get("axis_quote", ""), offsets)
            if loc is None:
                continue  # 定位失败 → 该轴不计入①
            axis_entries.append((loc, ax))
        axis_count = len(axis_entries)
        # ②核心驱动：任一轴 is_core 且 ≥2 个 core_scene_quotes 可定位且位于不同主线场景
        #（场景近似：段落号不同即视为不同场景，与 _same_scene/_group_into_scenes 一致）
        core_drive_flag = False
        for loc, ax in axis_entries:
            if ax.get("is_core") is not True:
                continue
            scene_paras: set[int] = set()
            for q in ax.get("core_scene_quotes", []) or []:
                sl = _locate(canonical_text, q, offsets)
                if sl is None:
                    continue
                for paragraph in sidecar.paragraphs:
                    if sl.canonical_start < paragraph.canonical_end:
                        scene_paras.add(paragraph.index)
                        break
            if len(scene_paras) >= 2:
                core_drive_flag = True
                break
        # ③跨轴广度：命中轴含 P1/P3/P4 之一（仅计已定位轴——定位失败的轴不计入③）
        breadth_flag = any(ax.get("axis") in {"P1", "P3", "P4"} for _, ax in axis_entries)
        ctx.set("axis_count", axis_count)
        ctx.set("core_drive_flag", core_drive_flag)
        ctx.set("breadth_flag", breadth_flag)
        ctx.set("criterion_count", int(axis_count >= 2) + int(core_drive_flag) + int(breadth_flag))
        return ctx

    if mid == "B16":
        items = semantic.get("ending_items", []) or []
        item = items[0] if items else {}
        last15 = sidecar.last_15pct_start
        veto1 = _locate(canonical_text, item.get("veto1_quote", ""), offsets)
        veto2 = _locate(canonical_text, item.get("veto2_quote", ""), offsets)
        ctx.set("veto_found", bool(
            (veto1 is not None and veto1.content_start >= last15)
            or (veto2 is not None and veto2.content_start >= last15)
        ))
        callback = _locate(canonical_text, item.get("callback_quote", ""), offsets)
        opening = _locate(canonical_text, item.get("opening_quote_ref", ""), offsets)
        mainline = _locate(canonical_text, item.get("mainline_resolve_quote", ""), offsets)
        item1 = callback is not None and callback.content_start >= last15 and opening is not None
        item2 = mainline is not None and mainline.content_start >= last15
        states = item.get("antagonist_final_states") or []
        located_states = []
        for st in states:
            if not isinstance(st, dict):
                continue
            loc = _locate(canonical_text, st.get("state_quote", ""), offsets)
            if loc is not None and loc.content_start >= last15:
                located_states.append(loc)
        item3 = bool(located_states) and len(located_states) == len([s for s in states if isinstance(s, dict)])
        ctx.set("item1_ok", bool(item1))
        ctx.set("item2_ok", bool(item2))
        ctx.set("item3_ok", bool(item3))
        # 七档细分字段：末 5% 判定 + 回收引文是否全书最后落点（B16 7/9/10 档）
        last5 = (L * 95 + 99) // 100
        key_locs = [loc for loc in (callback, mainline) + tuple(located_states) if loc is not None]
        ctx.set("last_5pct_ok", bool(key_locs) and all(loc.content_start >= last5 for loc in key_locs))
        ctx.set("callback_latest", bool(callback is not None) and all(
            callback.content_start >= loc.content_start for loc in key_locs
        ))
        ctx.set("item_count", int(item1) + int(item2) + int(item3))
        return ctx
    if mid == "B34":
        candidates = semantic.get("candidates", []) or []
        resolved: list[tuple[QuoteLocation | None, dict[str, Any]]] = [
            (_locate(canonical_text, c.get("scene_quote", ""), offsets, c.get("nearby_anchor")), c) for c in candidates
        ]
        # 冻结回退链：最后不可逆确定主线结果场 → 最后一个可确定主线结果的实时交锋场 → 无清算场
        selected = None
        irreversible = [c for loc, c in resolved if c.get("determines_mainline") is True and c.get("is_realtime") is True]
        if irreversible:
            selected = irreversible[-1]
        else:
            realtime = [c for loc, c in resolved if c.get("is_realtime") is True and c.get("determines_mainline") is True]
            if realtime:
                selected = realtime[-1]
        if selected is None:
            ctx.set("item_count", 0)
            ctx.set("item1", False)
            ctx.set("item4", False)
            ctx.set("entity_count", 0)
            return ctx
        # 四项判定全部 Python 重算：引文可定位即成立（spec derived_features 契约，
        # 绝不信任 LLM 的 item_hits——schema 中该字段为标量 bool，仅作参考）。
        item1 = _locate(canonical_text, selected.get("public_quote") or "", offsets) is not None
        item2 = _locate(canonical_text, selected.get("defeat_quote") or "", offsets) is not None
        item3 = _locate(canonical_text, selected.get("trigger_quote") or "", offsets) is not None
        item4 = _locate(canonical_text, selected.get("cost_quote") or "", offsets) is not None
        count = int(item1) + int(item2) + int(item3) + int(item4)
        ctx.set("item_count", count)
        ctx.set("item1", item1)
        ctx.set("item4", item4)
        # entity_count：在场实体计数（spec derived_features 契约——Python 校验实体引文
        # 可定位后计数，判定 ①当众性强度；≥5 为 10 分强度档）。
        # schema 中 entities_present 为标量字符串（稳定称谓/唯一身份描述清单），
        # 逐字符定位无意义——按分隔符切分后校验每个称谓可定位。
        entities = selected.get("entities_present")
        located_entities = 0
        if isinstance(entities, str):
            for ent in re.split(r"[、,，;；/|]", entities):
                ent = ent.strip()
                if not ent:
                    continue
                try:
                    if _locate(canonical_text, ent, offsets) is not None:
                        located_entities += 1
                except ValueError:
                    continue  # 称谓在正文多次出现（歧义）→ 不可靠定位，不计
        elif isinstance(entities, list):
            for ent in entities:
                if isinstance(ent, str):
                    try:
                        if _locate(canonical_text, ent, offsets) is not None:
                            located_entities += 1
                    except ValueError:
                        continue
                elif isinstance(ent, dict):
                    name = ent.get("name") or ent.get("identity") or ent.get("entity") or ""
                    try:
                        if _locate(canonical_text, str(name), offsets) is not None:
                            located_entities += 1
                    except ValueError:
                        continue
        ctx.set("entity_count", located_entities)
        return ctx

    if mid == "C22":
        # quality_items: schema 为单元素对象数组（derive_output_schema 将 YAML 的
        # 7 个单键 dict 列表扁平化为一个含全部字段的对象）；合并所有 dict 条目容错。
        items = semantic.get("quality_items", []) or []
        item: dict[str, Any] = {}
        for entry in items:
            if isinstance(entry, dict):
                item.update(entry)
        veto1 = _locate(canonical_text, item.get("veto1_quote", ""), offsets)
        veto2 = _locate(canonical_text, item.get("veto2_quote", ""), offsets)
        ctx.set("veto_found", bool(veto1 is not None or veto2 is not None))
        # ①支线闭合：schema 类型为数组；元素可为 {opening_quote,closing_quote} 对象
        # 或直接引文字符串。对象取 pair 双定位，字符串取自身定位；≥2 条成立。
        subplots = item.get("subplot_close_quotes") or []
        closed = 0
        for sp in subplots:
            if isinstance(sp, dict):
                o = _locate(canonical_text, sp.get("opening_quote", ""), offsets)
                c = _locate(canonical_text, sp.get("closing_quote", ""), offsets)
                if o is not None and c is not None:
                    closed += 1
            elif isinstance(sp, str):
                if _locate(canonical_text, sp, offsets) is not None:
                    closed += 1
        item1 = closed >= 2
        # 七档细分字段：①支线闭合对数（4 项时 {2,3,4+} 划分 7/9/10 档）
        ctx.set("subplot_count", closed)
        motivation = _locate(canonical_text, item.get("motivation_quote", ""), offsets)
        item2 = motivation is not None
        # ③三幕：schema 类型为数组（钩子/中段/终局按序）；逐个元素定位并校验顺序。
        acts = item.get("three_act_quotes") or []
        if isinstance(acts, dict):
            acts = [acts.get("hook_quote", ""), acts.get("middle_quote", ""), acts.get("finale_quote", "")]
        elif not isinstance(acts, list):
            acts = [str(acts)] if acts else []
        act_locs = [_locate(canonical_text, q, offsets) for q in acts]
        act_locs = [loc for loc in act_locs if loc is not None]
        item3 = bool(
            len(act_locs) >= 3
            and act_locs[0].content_start < act_locs[1].content_start < act_locs[2].content_start
        )
        # ④终局强度：schema 类型为 string（单条引文），定位即成立。
        # 注：spec derived_features 描述为"B31 四项 ≥3 且含 realtime/irrevocable"，
        # 但 semantic_outputs 的 b31_items 字段类型为 string，模型只能输出单条引文；
        # 此处按 schema 实际可承载的单引文定位判定（schema 冻结，不能改 YAML）。
        b31_quote = item.get("b31_items") or ""
        if isinstance(b31_quote, list):
            b31_quote = b31_quote[0] if b31_quote else ""
        item4 = _locate(canonical_text, str(b31_quote), offsets) is not None
        ctx.set("item1_ok", bool(item1))
        ctx.set("item2_ok", bool(item2))
        ctx.set("item3_ok", bool(item3))
        ctx.set("item4_ok", bool(item4))
        ctx.set("item_count", int(item1) + int(item2) + int(item3) + int(item4))
        return ctx

    if mid == "N3":
        # 固定极限词表（v4.0.0 冻结，spec extreme_word_list anchor；"等"字开放语义不在此表）
        extreme_words = ("嘶吼", "撕心裂肺", "目眦欲裂", "崩溃", "痛不欲生", "嚎啕大哭", "歇斯底里", "绝望", "狂喜", "欣喜若狂")

        peaks = semantic.get("peaks", []) or []
        # ①峰值：至少一个可定位候选
        located_peaks: list[tuple[QuoteLocation, dict[str, Any]]] = []
        for pk in peaks:
            if not isinstance(pk, dict):
                continue
            loc = _locate(canonical_text, pk.get("peak_quote", ""), offsets, pk.get("nearby_anchor"))
            if loc is not None:
                located_peaks.append((loc, pk))
        peak_found = bool(located_peaks)
        # 对每个可定位候选执行同一计数，取最高档路径（并列候选取最高分）
        best_criteria = 0
        word_counts: list[int] = []
        selected_peaks: list[tuple[QuoteLocation, dict[str, Any]]] = []
        best_prev = -1
        for loc, pk in located_peaks:
            # 峰值两侧各 200 非空白码点窗口（跨段连续截取，越界按内容边界夹紧）
            lo = max(0, loc.content_start - 200)
            hi = min(L, loc.content_end + 200)
            c_lo = canonical_index_for_content_offset(offsets, lo)
            c_hi = canonical_index_for_content_offset(offsets, hi)
            window_text = canonical_text[c_lo:c_hi]
            # ②直给词收敛：Python 用固定词表在窗口内匹配计数（每次出现计一次）
            word_count = 0
            for w in extreme_words:
                start = 0
                while True:
                    idx = window_text.find(w, start)
                    if idx < 0:
                        break
                    word_count += 1
                    start = idx + len(w)
            extreme_le_2 = word_count <= 2
            # ③承载转译：transference_quote 可定位且在窗口内
            t_loc = _locate(canonical_text, pk.get("transference_quote", ""), offsets)
            transference_ok = bool(
                t_loc is not None
                and t_loc.content_start >= lo
                and t_loc.content_end <= hi
            )
            # ④主角本体收敛：convergence_quote 可定位且在窗口内
            c_loc = _locate(canonical_text, pk.get("convergence_quote", ""), offsets)
            convergence_ok = bool(
                c_loc is not None
                and c_loc.content_start >= lo
                and c_loc.content_end <= hi
            )
            criteria = int(extreme_le_2) + int(transference_ok) + int(convergence_ok)
            best_criteria = max(best_criteria, criteria)
            # 并列候选跟踪：最佳路径（最高计数）候选清单 + 各窗口极限词数（七档细分用）
            if criteria > best_prev:
                best_prev = criteria
                selected_peaks = [(loc, pk)]
                word_counts = [word_count]
            elif criteria == best_prev:
                selected_peaks.append((loc, pk))
                word_counts.append(word_count)
        ctx.set("peak_found", peak_found)
        # ①峰值不成立 → 0 分档；否则 ①+②③④ 成立计数（≤2→0，3→5，4→10）
        ctx.set("criterion_count", 0 if not peak_found else 1 + best_criteria)
        # 七档细分字段：最佳路径窗口极限词计数（4 项时 ≥1=7、=0=9）+ 三序不可逆判定（10 档）
        best_words = min(word_counts) if word_counts else 0
        ctx.set("extreme_word_count", 0 if not peak_found else best_words)
        ctx.set("peak_all_irreversible", bool(peak_found and located_peaks and all(
            "不可逆" in str(pk.get("peak_rank_note") or "") for _, pk in selected_peaks
        )))
        return ctx

    if mid == "N6":
        events = semantic.get("events", []) or []
        # 先按 game_goal 分组，再组内合并重叠/相邻区间（spec：同一目标连续对话只计一件）
        by_goal: dict[str, list[tuple[int, int]]] = {}
        for ev in events:
            if ev.get("qualifies") is not True:
                continue
            quotes = ev.get("round_quotes") or []
            if not isinstance(quotes, list) or len(quotes) < 2:
                continue
            s = _locate(canonical_text, quotes[0], offsets, ev.get("nearby_anchor"))
            e = _locate(canonical_text, quotes[-1], offsets, ev.get("nearby_anchor"))
            if s is None or e is None or not (s.content_start < e.content_end):
                continue
            goal = str(ev.get("game_goal") or "").strip() or "_ungrouped"
            by_goal.setdefault(goal, []).append((s.content_start, e.content_end))
        n = sum(_merge_intervals(ivs) for ivs in by_goal.values())
        ctx.set("N", n)
        ctx.set("F", n / sidecar.K if sidecar.K > 0 else 0.0)
        return ctx

    if mid == "B33":
        events = semantic.get("events", []) or []
        intervals = []
        # 语义终局（spec derived_features：finale_quote 定位 → finale_start；null 则不排除）
        finale_loc = _locate(canonical_text, semantic.get("finale_quote", ""), offsets)
        finale_start = finale_loc.content_start if finale_loc is not None else None
        for ev in events:
            if ev.get("qualifies") is not True:
                continue
            action = ev.get("active_action_quote", "")
            s = _locate(canonical_text, action, offsets, ev.get("nearby_anchor"))
            end_quote = ev.get("a_quote", "")
            e = _locate(canonical_text, end_quote, offsets) if isinstance(end_quote, str) and end_quote else s
            if s is None or e is None or not (s.content_start < e.content_end):
                continue
            # is_finale：事件落在主线终局区间内 → 不计入 N（finale 为 null 时不排除）
            if finale_start is not None and s.content_start >= finale_start:
                continue
            intervals.append((s.content_start, e.content_end))
        n = _merge_intervals(intervals)
        ctx.set("N", n)
        ctx.set("F", n / sidecar.K if sidecar.K > 0 else 0.0)
        return ctx

    if mid == "B31":
        candidates = semantic.get("candidates", []) or []
        best_count = -1
        ties = []
        for cand in candidates:
            r1 = _locate(canonical_text, cand.get("round1_quote", ""), offsets, cand.get("nearby_anchor"))
            r2 = _locate(canonical_text, cand.get("round2_quote", ""), offsets, cand.get("nearby_anchor"))
            if r1 is None or r2 is None:
                continue
            if not (r1.content_start < r2.content_start):
                continue
            r3 = _locate(canonical_text, cand.get("round3_quote", ""), offsets) if cand.get("round3_quote") else None
            r4 = _locate(canonical_text, cand.get("round4_quote", ""), offsets) if cand.get("round4_quote") else None
            if r3 is not None and not (r2.content_start < r3.content_start):
                continue
            if r4 is not None and not (r3.content_start < r4.content_start):
                continue
            round_count = 2 + (1 if r3 else 0) + (1 if r4 else 0)
            item1 = round_count >= 4
            item2 = _locate(canonical_text, cand.get("irrevocable_quote") or "", offsets) is not None
            item3 = _locate(canonical_text, cand.get("sensory_quote") or "", offsets) is not None
            item4 = _locate(canonical_text, cand.get("foreshadow_quote") or "", offsets) is not None
            count = int(item1) + int(item2) + int(item3) + int(item4)
            if count > best_count:
                best_count = count
                ties = [(cand, item1, item2, round_count)]
            elif count == best_count:
                ties.append((cand, item1, item2, round_count))
        best_count = max(0, best_count)
        ctx.set("item_count", best_count)
        if ties:
            ctx.set("item1", ties[0][1])
            ctx.set("item2", ties[0][2])
            # round_count：Python 校验的逐字可定位回合数为下界；LLM 自报的
            # 总回合数（schema 整数）可更高（正文交换不止 4 条记录引文），
            # 取各并列最高场中 LLM 自报的最大值承载 10 分强度档（≥6）。
            reported = [
                int(cand.get("round_count") or 0)
                for cand, _, _, verified in ties
                if isinstance(cand.get("round_count"), int) and cand.get("round_count") >= verified
            ]
            verified_max = max(t[3] for t in ties)
            ctx.set("round_count", max([verified_max] + reported))
        else:
            ctx.set("item1", False)
            ctx.set("item2", False)
            ctx.set("round_count", 0)
        return ctx

    if mid == "C14":
        blocks = semantic.get("blocks", []) or []
        resolved_blocks = []
        for blk in blocks:
            loc = _locate(canonical_text, blk.get("block_quote", ""), offsets, blk.get("nearby_anchor"))
            if loc is None:
                continue
            resolved_blocks.append((loc, blk))
        # 焦点角色：直接感知/想法块所在"场景"数最多 → 码点总数 → 首次出现
        scenes = _group_into_scenes(resolved_blocks, sidecar)
        char_scores: dict[str, dict[str, Any]] = {}
        for scene in scenes:
            seen_in_scene: set[str] = set()
            for loc, blk in scene:
                if blk.get("block_type") in _C14_FOCAL_TYPES and blk.get("character"):
                    ch = str(blk.get("character"))
                    if ch not in seen_in_scene:
                        seen_in_scene.add(ch)
                        entry = char_scores.setdefault(ch, {"scenes": 0, "codepoints": 0, "first": loc.content_start})
                        entry["scenes"] += 1
                        entry["codepoints"] += _quote_content_len(loc)
        focal = None
        if char_scores:
            focal = max(
                char_scores.items(),
                key=lambda kv: (kv[1]["scenes"], kv[1]["codepoints"], -kv[1]["first"]),
            )[0]
        ctx.set("focal_character", focal)
        # A/B 仅计焦点角色的块（focal 为 None 时无 A/B 成立）
        a_ok = bool(
            focal is not None
            and any(
                str(blk.get("character")) == focal and _locate(canonical_text, blk.get("a_body", ""), offsets) is not None
                for _, blk in resolved_blocks
                if blk.get("a_body")
            )
        )
        b_ok = bool(
            focal is not None
            and any(
                str(blk.get("character")) == focal and _locate(canonical_text, blk.get("b_sensory", ""), offsets) is not None
                for _, blk in resolved_blocks
                if blk.get("b_sensory")
            )
        )
        # C：检查 c_inner 引文本体的非空白码点数（≥51），不是 block_quote；全文 ≤2 块
        c_count = 0
        for _, blk in resolved_blocks:
            c_inner = blk.get("c_inner")
            if not c_inner:
                continue
            c_loc = _locate(canonical_text, c_inner, offsets)
            if c_loc is not None and _quote_content_len(c_loc) >= 51:
                c_count += 1
        c_ok = 1 <= c_count <= 2
        # X1：焦点角色由 Python 选出后，再由 character + block_type 确定；LLM 不直接判 nonfocal。
        x1_blocks = [
            loc for loc, blk in resolved_blocks
            if blk.get("block_type") == "想法"
            and blk.get("character")
            and (focal is None or str(blk.get("character")) != focal)
        ]
        x2_blocks = [loc for loc, blk in resolved_blocks if blk.get("x2_omniscient") is True]
        ctx.set("x1_ratio", sum(_quote_content_len(loc) for loc in x1_blocks) / L if L else 0.0)
        ctx.set("x2_ratio", sum(_quote_content_len(loc) for loc in x2_blocks) / L if L else 0.0)
        # 七档细分字段：X1/X2 中占比更大者（3 项时 >15%=7、≤15%=9、≤5%=10）
        _x1 = ctx.get("x1_ratio", 0.0)
        _x2 = ctx.get("x2_ratio", 0.0)
        ctx.set("x_max_ratio", max(_x1, _x2))
        # y_flag 白名单：仅明确的否决标记触发，'无'/空/其他 不触发（防 AI 输出"无"被误判）
        _Y_FLAGS = {"Y1", "Y2", "Y3", "Y1乱码", "Y2碎片", "Y3整段缺失", "顺序冲突"}
        ctx.set("y_veto", any(str(blk.get("y_flag", "")).strip() in _Y_FLAGS for _, blk in resolved_blocks))
        ctx.set("item_count", int(a_ok) + int(b_ok) + int(c_ok))
        return ctx

    if mid == "B18":
        hook = _locate(canonical_text, (semantic.get("endpoints") or {}).get("hook_quote", ""), offsets) if isinstance(semantic.get("endpoints"), dict) else None
        climax = _locate(canonical_text, (semantic.get("endpoints") or {}).get("climax_quote", ""), offsets) if isinstance(semantic.get("endpoints"), dict) else None
        scenes = semantic.get("middle_scenes", []) or []
        middle: list[dict[str, Any]] = []
        for sc in scenes:
            loc = _locate(canonical_text, sc.get("scene_quote", ""), offsets, sc.get("nearby_anchor"))
            if loc is None:
                continue
            if hook is not None and loc.canonical_start < hook.canonical_end and _contains(loc, hook):
                continue  # 端点同场只排除一次：钩子场景
            if climax is not None and _contains(loc, climax):
                continue
            middle.append(sc)
        valid = sum(1 for s in middle if s.get("valid") is True)
        total = len(middle)
        invalid = total - valid
        ratio = invalid / total if total else 0.0
        consecutive = 0
        best = 0
        for s in middle:
            if s.get("valid") is not True:
                consecutive += 1
                best = max(best, consecutive)
            else:
                consecutive = 0
        ctx.set("invalid_ratio", ratio)
        ctx.set("consecutive_invalid", best)
        return ctx

    if mid == "N7":
        plots = semantic.get("plots", []) or []
        best_key = None
        ties = []
        for plot in plots:
            reqs = 0
            carriers = set(plot.get("carriers") or [])
            carrier_count = sum(1 for c in carriers if str(c).startswith("C"))
            scene_quotes = plot.get("scenes") or []
            scene_count = 0
            prev_end = -1
            for q in scene_quotes:
                loc = _locate(canonical_text, q, offsets)
                if loc is not None and loc.content_start > prev_end:
                    scene_count += 1
                    prev_end = loc.content_end
            closure = plot.get("completes") is True
            if carrier_count >= 2:
                reqs += 1
            if scene_count >= 2:
                reqs += 1
            if closure:
                reqs += 1
            loss_count = 1 if plot.get("loss_quote") else 0
            key = (reqs, closure, scene_count, loss_count)
            if best_key is None or key > best_key:
                best_key = key
                ties = [plot]
            elif key == best_key:
                ties.append(plot)
        ctx.set("criterion_count", best_key[0] if best_key else 0)
        ctx.set("plot_count", len(ties))
        return ctx

    raise NotImplementedError(f"no extractor for {mid}")


def _paragraph_ok(loc: QuoteLocation, sidecar, max_paragraph: int) -> bool:
    """True if the located quote's paragraph index is at most ``max_paragraph``."""
    for paragraph in sidecar.paragraphs:
        if loc.canonical_start < paragraph.canonical_end:
            return paragraph.index <= max_paragraph
    return False


def _same_scene(a: QuoteLocation, b: QuoteLocation, sidecar) -> bool:
    """Paragraph-index proximity as a scene approximation."""
    pa = pb = None
    for paragraph in sidecar.paragraphs:
        if a.canonical_start < paragraph.canonical_end:
            pa = paragraph.index
            break
    for paragraph in sidecar.paragraphs:
        if b.canonical_start < paragraph.canonical_end:
            pb = paragraph.index
            break
    if pa is None or pb is None:
        return False
    return abs(pa - pb) <= 2


def _contains(outer: QuoteLocation, inner: QuoteLocation) -> bool:
    return outer.canonical_start <= inner.canonical_start < inner.canonical_end <= outer.canonical_end


def _group_into_scenes(resolved: list[tuple[QuoteLocation, dict[str, Any]]], sidecar) -> list[list[tuple[QuoteLocation, dict[str, Any]]]]:
    """Group resolved blocks into scenes by paragraph adjacency (jump > 1 cuts)."""
    scenes: list[list[tuple[QuoteLocation, dict[str, Any]]]] = []
    current: list[tuple[QuoteLocation, dict[str, Any]]] = []
    prev_para = None
    for loc, blk in sorted(resolved, key=lambda pair: pair[0].canonical_start):
        para = None
        for paragraph in sidecar.paragraphs:
            if loc.canonical_start < paragraph.canonical_end:
                para = paragraph.index
                break
        if current and para is not None and prev_para is not None and para - prev_para > 1:
            scenes.append(current)
            current = []
        current.append((loc, blk))
        if para is not None:
            prev_para = para
    if current:
        scenes.append(current)
    return scenes
