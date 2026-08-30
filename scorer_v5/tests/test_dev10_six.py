#!/usr/bin/env python3
"""Step 7 Dev10 首批 6 指标边界测试（B01/B02/N6/B33/C14/B36）。

每指标覆盖：低档 / 中档 / 高档 / 阈值边界 / 典型错误。
通过真实 extractor + ordinal 引擎验证（不信任 LLM 聚合）。

用约 2000 字长文本，使 q/position/F 断点有实际区分度。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scorer_v5.preprocessing.sidecar import build_sidecar
from scorer_v5.preprocessing.spans import build_evidence_spans
from scorer_v5.runtime.parsing import parse_model_output
from scorer_v5.runtime.quote_bind import bind_evidence_spans
from scorer_v5.runtime.specs import load_metric_spec
from scorer_v5.runtime.validation import validate_model_output
from scorer_v5.scoring.engine import compute_score

# 长文本：约 2000 字。前半段是日常铺垫（冲突在 ~8% 处出现），中段多个事件，末段终局。
TEXT = (
    "清晨六点，我挤上地铁，车厢里挤满了赶早班的人。"
    "我靠在门边，看着窗外灰蒙蒙的天色，想着今天要做的事。"
    "先去医院拿体检报告，再去公司提交季度报表，晚上还有个应酬。"
    "地铁到站，我快步走出站口，晨风裹着早点摊的香气扑面而来。"
    "买了个肉包子，边吃边往公司走。路上经过那家熟悉的彩票店，"
    "老板探出头来喊：\"小陈，昨天的彩票中了没？\""
    "我笑着摇头：\"哪那么容易中奖。\""
    "老板嘿嘿一笑：\"你要是中了，记得请客。\""
    "我摆摆手，继续往前走。"
    "到了公司楼下，门卫老张拦住我：\"按规矩，外来人员要登记。\""
    "我掏出工牌：\"我是技术部的陈默，今天来取设备。\""
    "老张盯着工牌看了半天：\"你这工牌是旧的，系统里查不到。\""
    "我心里一沉：\"怎么会？我上周还在用。\""
    "老张摇头：\"系统显示你上周五就离职了，工牌已注销。\""
    "\"离职？\"我愣住了，\"我昨天还在上班啊。\""
    "老张叹了口气：\"人事通知的，你自己去问吧。\""
    "我冲进大楼，直奔人事部。前台小妹看见我，脸色变了："
    "\"陈、陈工，你怎么来了？\""
    "\"来上班。\"我盯着她，\"为什么我的工牌被注销了？\""
    "她支支吾吾：\"这……系统里显示你办了离职手续。\""
    "\"我没办过任何手续！\"我提高声音，\"谁签的字？\""
    "她低下头：\"是……是林总签的。\""
    "我转身冲向林总办公室，推开门。林总正坐在办公桌后，"
    "看见我，脸上闪过一丝慌乱。"
    "\"林总，解释一下。\"我走到桌前，双手撑在桌面上，"
    "\"为什么我的人事档案显示离职？\""
    "林总干笑：\"小陈，你冷静点。这是……这是个误会。\""
    "\"误会？\"我冷笑，\"你签的字，叫误会？\""
    "林总站起身，绕过桌子，拍拍我的肩膀："
    "\"年轻人，别激动。公司有公司的规矩。\""
    "\"什么规矩？\"我甩开他的手，\"我昨天还在加班改系统，"
    "今天就成了离职人员？\""
    "林总沉默了几秒，压低声音：\"有人举报你泄露客户数据。\""
    "我如遭雷击：\"什么？！我从来没有碰过客户数据！\""
    "林总摇头：\"证据在信息安全部手里，你自求多福吧。\""
    "他说完，转身走出办公室。我站在原地，浑身发冷。"
    "这不是误会，是陷害。"
    "我握紧拳头，指甲掐进掌心。我不能就这么认了。"
    "我掏出手机，拨通了法务部老同学的电话："
    "\"老周，我遇到麻烦了，公司说我泄露客户数据。\""
    "电话那头沉默片刻：\"你有证据自证清白吗？\""
    "\"我有操作日志。\"我冷静下来，\"每次访问都有记录。\""
    "\"那就好。\"老周说，\"把日志导出来，我帮你看看。\""
    "我挂断电话，冲回工位。电脑已经被锁了，屏幕上一行字："
    "\"该账户已被停用。\""
    "我深吸一口气，掏出备用笔记本，登录系统后台。"
    "操作日志还在，一条条记录着我的每一次访问。"
    "我翻到上周五的记录，愣住了——那天下班后，"
    "有人用我的账户登录过，访问了客户数据库。"
    "时间：晚上九点十七分。那时我已经离开公司了。"
    "我立刻截图保存证据，给老周发了过去。"
    "老周回复：\"这份日志能证明不是你操作的，但需要设备指纹。\""
    "\"我能查。\"我手指飞快敲击键盘，\"后台有登录设备记录。\""
    "几分钟后，我找到了那台设备——是信息安全部内部的测试机。"
    "陷害我的人，就在信息安全部。"
    "我站起身，正要去找信息安全部主管对质，"
    "手机突然响了。是个陌生号码。"
    "\"陈默？\"电话那头是个陌生的男声，\"你查得挺快啊。\""
    "\"你是谁？\"我握紧手机。"
    "\"劝你别查了。\"男声冷冷地说，\"查下去，对你没好处。\""
    "\"是吗？\"我冷笑，\"我倒要看看，谁怕谁。\""
    "我挂断电话，转身下楼，直奔信息安全部。"
    "推开门的瞬间，我看见一个熟悉的背影——"
    "信息安全部的主管，王栋，正对着电脑操作。"
    "屏幕上，赫然是我的工号。"
    "\"王主管。\"我缓缓开口，\"解释一下？\""
    "王栋猛地转身，脸色煞白：\"你……你怎么进来的？\""
    "\"大门没锁。\"我走到他面前，\"你往我账户里栽赃数据，"
    "就是为了掩盖你自己泄露客户信息的勾当吧？\""
    "王栋额头冒汗：\"你血口喷人！\""
    "\"那这台测试机的登录记录怎么解释？\"我举起手机，"
    "\"要不要我现在就报警？\""
    "王栋瘫坐在椅子上，嘴唇哆嗦：\"我……我只是……\""
    "\"你只是什么？\"我居高临下地看着他，\"说！\""
    "王栋突然扑过来抢我的手机，我侧身躲开，"
    "他重心不稳，撞翻了桌上的文件，摔在地上。"
    "我冷眼看着他：\"就这点本事？\""
    "王栋爬起来，声音发抖：\"是林总让我干的。\""
    "我心里一凉：\"林总？\""
    "\"客户数据泄露的事，是林总经手的。\"王栋低下头，"
    "\"他只是需要个替罪羊，你正好撞上来。\""
    "我沉默良久，然后笑了。原来如此。"
    "从陷害到威胁，从威胁到栽赃，一张大网早就铺好了。"
    "但我没被网住。我攥着证据，走出信息安全部。"
    "走廊尽头，林总正站在那里，像是等着我。"
    "\"查清楚了？\"林总问，语气平静。"
    "\"查清楚了。\"我点头，\"王栋都说了。\""
    "林总脸上没什么表情：\"然后呢？\""
    "\"然后？\"我举起手机，\"报警，起诉，该走的法律程序，"
    "一步都不会少。\""
    "林总忽然笑了：\"你觉得你能赢？\""
    "\"证据在我手里。\"我看着他，\"公道自在人心。\""
    "林总收起笑容，沉默了很久，终于说：\"我们谈谈条件。\""
    "我摇头：\"没什么好谈的。\""
    "我转身离开，走出大楼。阳光刺眼，我眯起眼睛。"
    "这场仗，才刚刚开始。但我手里有证据，有真相，"
    "还有老周这个律师朋友。我按下报警键，"
    "电话那头传来接线员的声音：\"您好，这里是110。\""
    "\"我要报案。\"我说，\"关于职务侵占和伪造证据。\""
    "挂断电话，我抬头看了看天空。"
    "天很蓝，云很白，像是这场风波的底色。"
    "我握紧手机，大步向前走去。"
)


def _wire_encode(value, text: str):
    """Test-only: replace quote-like string values with span ids.

    Quote strings resolve to the unique span whose body contains them. For
    ambiguous strings (e.g. an anchor substring appearing twice), prefer the
    span nearest to any other bind value resolved in the same object.
    """
    from scorer_v5.runtime.quote_bind import is_bind_field
    spans = build_evidence_spans(text)
    spans_by_text = {}
    for s in spans:
        spans_by_text.setdefault(s.text, []).append(s.span_id)

    def resolve(quote: str, context_ids: set[int]) -> int:
        if quote in spans_by_text and len(spans_by_text[quote]) == 1:
            return spans_by_text[quote][0]
        candidates = []
        for s in spans:
            if quote in s.text:
                candidates.append(s.span_id)
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            # Fixture may span multiple spans (e.g. a quoted exchange that
            # contains an interior terminator). Map to the span containing the
            # longest leading prefix that is actually present.
            prefix = quote
            while len(prefix) >= 2:
                prefix = prefix[:-1]
                cand = [s.span_id for s in spans if prefix and prefix in s.text]
                if len(cand) == 1:
                    return cand[0]
                if cand:
                    candidates = cand
                    break
        if context_ids:
            nearest = min(candidates, key=lambda sid: min((abs(sid - c) for c in context_ids), default=10**9))
            return nearest
        raise ValueError(f"fixture quote not uniquely resolvable: {quote!r} (candidates={candidates})")

    def rec(node, context: set[int]):
        if isinstance(node, dict):
            # Resolve bind fields using same-object context; keep raw string for
            # empty markers (a_quote="" -> EVIDENCE_FAIL).
            ctx = set(context)
            out = {}
            for k, v in node.items():
                if is_bind_field(k) and isinstance(v, str) and v != "":
                    sid = resolve(v, ctx)
                    out[k] = sid
                    ctx.add(sid)
                elif is_bind_field(k) and isinstance(v, list):
                    ids = []
                    for item in v:
                        if isinstance(item, str) and item:
                            sid = resolve(item, ctx)
                            ids.append(sid)
                            ctx.add(sid)
                        else:
                            ids.append(item)
                    out[k] = ids
                elif isinstance(v, dict):
                    out[k] = rec(v, ctx)
                elif isinstance(v, list):
                    out[k] = [rec(item, ctx) for item in v]
                else:
                    out[k] = v
            return out
        if isinstance(node, list):
            return [rec(item, context) for item in node]
        return node

    return rec(value, set())


def run(metric_id: str, semantic: dict):
    spec = load_metric_spec(metric_id)
    # Test-only wire shim: translate quote *strings* in fixtures to span ids so
    # the fixtures stay readable while exercising the integer span-id wire.
    semantic = _wire_encode(semantic, TEXT)
    raw = json.dumps({"status": "OK", "semantic": semantic}, ensure_ascii=False)
    parsed = parse_model_output(raw, formal=True, spec=spec)
    if parsed.parse_status != "OK":
        return {"parse": parsed.parse_status, "error": parsed.error}
    bound, _index = bind_evidence_spans(parsed.value["semantic"], TEXT)
    parsed.value["semantic"] = bound
    result = validate_model_output(parsed, spec, TEXT, content_offsets=OFFSETS)
    scored = compute_score(spec, result, TEXT, SIDECAR)
    return {"outcome": result.outcome, "score": scored.score, "derived": dict(scored.derived)}


def check(metric_id: str, label: str, semantic: dict, expect, failures: list[str]):
    """expect: int 分数 或 'EVIDENCE_FAIL'（引文缺失应 EVIDENCE_FAIL）"""
    r = run(metric_id, semantic)
    if expect == "EVIDENCE_FAIL":
        ok = r.get("outcome") == "EVIDENCE_FAIL"
        status = "PASS" if ok else "FAIL"
        if not ok:
            failures.append(f"{metric_id} [{label}]: expected EVIDENCE_FAIL, got {r}")
        print(f"  {status} {metric_id} [{label}]: outcome={r.get('outcome')}")
        return
    got = r.get("score")
    status = "PASS" if got == expect else "FAIL"
    if got != expect:
        failures.append(f"{metric_id} [{label}]: expected {expect}, got {got} (outcome={r.get('outcome')}, derived={r.get('derived')})")
    print(f"  {status} {metric_id} [{label}]: score={got}")


def main() -> int:
    failures: list[str] = []
    global SIDECAR_TEXT, SIDECAR, OFFSETS

    print(f"text L={SIDECAR.L} K={SIDECAR.K}")

    print("== B01 异常事件位置（q≤10% 内 1/3/5/7/9/10） ==")
    # 低档：无事件 → 0
    check("B01", "low-no-event", {"candidates": []}, 0, failures)
    # 中档：q≤10% 但仅③（1 项）→ 1 —— 事件在 ~6% 处
    check("B01", "mid-one-hit", {
        "candidates": [{
            "event_quote": "老板探出头来喊", "nearby_anchor": "小陈",
            "is_external_event": True, "same_scene_action": False, "qualifies": True,
        }],
    }, 3, failures)
    # 高档：①②③ 全成立且 q≤2.5% → 10
    check("B01", "high-three-hits", {
        "candidates": [{
            "event_quote": "地铁到站，我快步走出站口", "nearby_anchor": "晨风",
            "is_external_event": True, "same_scene_action": True,
            "action_quote": "买了个肉包子", "qualifies": True,
        }],
    }, 9, failures)
    # 边界：q>10% 的事件 → 0（位置靠后）
    check("B01", "boundary-q-gt-10", {
        "candidates": [{
            "event_quote": "我冲进大楼，直奔人事部", "nearby_anchor": "前台",
            "is_external_event": True, "same_scene_action": True,
            "action_quote": "我转身冲向林总办公室", "qualifies": True,
        }],
    }, 0, failures)
    # 典型错误：非外部事件（内心情绪）qualifies=false → 0
    check("B01", "err-internal", {
        "candidates": [{
            "event_quote": "我如遭雷击", "nearby_anchor": "林总",
            "is_external_event": False, "same_scene_action": False, "qualifies": False,
        }],
    }, 0, failures)

    print("== B02 冲突速度（≤15% 内 1/3/5/7/9/10） ==")
    # 低档：不 qualify → 0
    check("B02", "low-no-qualify", {
        "conflicts": [{
            "entity_a": "我", "entity_b": "彩票店老板", "issue": "中奖",
            "round1_quote": "小陈，昨天的彩票中了没？", "round2_quote": "哪那么容易中奖。",
            "round3_quote": None, "round4_quote": None, "round_count": 2,
            "same_lineage": False, "qualifies": False,
        }],
    }, 0, failures)
    # 中档：qualify + ≤15% + hits=0 → 1
    check("B02", "mid-zero-hits", {
        "conflicts": [{
            "entity_a": "我", "entity_b": "门卫老张", "issue": "登记",
            "round1_quote": "按规矩，外来人员要登记。", "round2_quote": "我是技术部的陈默",
            "round3_quote": "你这工牌是旧的", "round4_quote": "怎么会？我上周还在用。",
            "round_count": 4, "same_lineage": False, "qualifies": True,
        }],
    }, 3, failures)
    # 高档：≤500 且同源 → 10
    check("B02", "high-500-lineage", {
        "conflicts": [{
            "entity_a": "我", "entity_b": "门卫老张", "issue": "工牌",
            "round1_quote": "按规矩，外来人员要登记。", "round2_quote": "我是技术部的陈默",
            "round3_quote": "你这工牌是旧的", "round4_quote": "怎么会？我上周还在用。",
            "round_count": 4, "same_lineage": True, "qualifies": True,
        }],
    }, 10, failures)
    # 边界：hits=1 且位置≤8% → 5（同源 False 但位置早）
    check("B02", "boundary-one-hit-early", {
        "conflicts": [{
            "entity_a": "我", "entity_b": "门卫老张", "issue": "登记",
            "round1_quote": "按规矩，外来人员要登记。", "round2_quote": "我是技术部的陈默",
            "round3_quote": "你这工牌是旧的", "round4_quote": "怎么会？我上周还在用。",
            "round_count": 4, "same_lineage": False, "qualifies": True,
        }],
    }, 3, failures)
    # 典型错误：round_count=2 单交换 → 不 qualify → 0
    check("B02", "err-single-exchange", {
        "conflicts": [{
            "entity_a": "我", "entity_b": "门卫", "issue": "退票",
            "round1_quote": "按规矩，外来人员要登记。", "round2_quote": "我是技术部的陈默",
            "round3_quote": None, "round4_quote": None, "round_count": 2,
            "same_lineage": False, "qualifies": True,
        }],
    }, 0, failures)

    print("== N6 潜台词密度（F 断点 0.2/0.3/0.4/0.5/0.65/0.8） ==")
    # 低档：0 事件 → F=0 → 0
    check("N6", "low-no-event", {"events": []}, 0, failures)
    # 中档：2 事件 → F=2/K≈0.4 → 5（K≈2.0）
    check("N6", "mid-two-events", {
        "events": [
            {"round_quotes": ["按规矩，外来人员要登记。", "我是技术部的陈默"],
             "nearby_anchor": "门卫老张", "literal_meaning": "要求", "real_meaning": "刁难",
             "decoding_evidence": "我心里一沉", "game_goal": "进楼", "qualifies": True},
            {"round_quotes": ["系统显示你上周五就离职了", "怎么会？我上周还在用。"],
             "nearby_anchor": "老张摇头", "literal_meaning": "告知", "real_meaning": "施压",
             "decoding_evidence": "我冲进大楼", "game_goal": "进楼", "qualifies": True},
        ],
    }, 5, failures)
    # 高档：≥8 事件 → F≥4 → 10
    check("N6", "high-many-events", {
        "events": [
            {"round_quotes": ["按规矩，外来人员要登记。", "我是技术部的陈默"],
             "nearby_anchor": "门卫老张", "literal_meaning": "要求", "real_meaning": "刁难",
             "decoding_evidence": "我心里一沉", "game_goal": "进楼", "qualifies": True},
            {"round_quotes": ["系统显示你上周五就离职了", "怎么会？我上周还在用。"],
             "nearby_anchor": "老张摇头", "literal_meaning": "告知", "real_meaning": "施压",
             "decoding_evidence": "我冲进大楼", "game_goal": "进楼", "qualifies": True},
            {"round_quotes": ["陈、陈工，你怎么来了？", "来上班。"],
             "nearby_anchor": "前台小妹", "literal_meaning": "惊讶", "real_meaning": "心虚",
             "decoding_evidence": "她低下头", "game_goal": "问工牌", "qualifies": True},
            {"round_quotes": ["为什么我的工牌被注销了？", "系统里显示你办了离职手续"],
             "nearby_anchor": "她支支吾吾", "literal_meaning": "质问", "real_meaning": "追责",
             "decoding_evidence": "我提高声音", "game_goal": "问工牌", "qualifies": True},
            {"round_quotes": ["林总，解释一下。", "小陈，你冷静点"],
             "nearby_anchor": "办公桌后", "literal_meaning": "要求", "real_meaning": "对峙",
             "decoding_evidence": "我走到桌前", "game_goal": "讨说法", "qualifies": True},
            {"round_quotes": ["什么规矩？", "公司有公司的规矩。"],
             "nearby_anchor": "林总站起身", "literal_meaning": "反问", "real_meaning": "不忿",
             "decoding_evidence": "我甩开他的手", "game_goal": "讨说法", "qualifies": True},
            {"round_quotes": ["我有操作日志。", "那就好。"],
             "nearby_anchor": "电话那头", "literal_meaning": "陈述", "real_meaning": "自证",
             "decoding_evidence": "我冷静下来", "game_goal": "自证", "qualifies": True},
            {"round_quotes": ["查清楚了？", "查清楚了。"],
             "nearby_anchor": "走廊尽头", "literal_meaning": "询问", "real_meaning": "试探",
             "decoding_evidence": "林总脸上没什么表情", "game_goal": "对峙", "qualifies": True},
            {"round_quotes": ["你觉得你能赢？", "证据在我手里。"],
             "nearby_anchor": "林总忽然笑了", "literal_meaning": "挑衅", "real_meaning": "威胁",
             "decoding_evidence": "我看着他", "game_goal": "对峙", "qualifies": True},
        ],
    }, 10, failures)
    # 边界：game_goal 相同 → 合并 → N 减少
    check("N6", "boundary-same-goal-merge", {
        "events": [
            {"round_quotes": ["按规矩，外来人员要登记。", "我是技术部的陈默"],
             "nearby_anchor": "门卫老张", "literal_meaning": "要求", "real_meaning": "刁难",
             "decoding_evidence": "我心里一沉", "game_goal": "进楼", "qualifies": True},
            {"round_quotes": ["系统显示你上周五就离职了", "怎么会？我上周还在用。"],
             "nearby_anchor": "老张摇头", "literal_meaning": "告知", "real_meaning": "施压",
             "decoding_evidence": "我冲进大楼", "game_goal": "进楼", "qualifies": True},
        ],
    }, 5, failures)
    # 典型错误：qualifies=false 不计
    check("N6", "err-not-qualify", {
        "events": [{
            "round_quotes": ["按规矩，外来人员要登记。", "我是技术部的陈默"],
            "nearby_anchor": "门卫老张", "literal_meaning": "要求", "real_meaning": "刁难",
            "decoding_evidence": "我心里一沉", "game_goal": "进楼", "qualifies": False,
        }],
    }, 0, failures)

    print("== B33 主角主动节奏（F 断点 0.6/0.75/0.9/1.2/1.5/1.8） ==")
    # 低档：0 事件 → 0
    check("B33", "low-no-event", {"finale_quote": None, "events": []}, 0, failures)
    # 中档：2 事件 → F=2/K≈1 → 5（精确 span 定位：两事件均早于终局，计入 N）
    check("B33", "mid-two-events", {
        "finale_quote": "我转身离开，走出大楼", "events": [
            {"active_action_quote": "我冲进大楼", "nearby_anchor": "老张摇头",
             "a_code": "A1", "a_quote": "直奔人事部", "qualifies": True},
            {"active_action_quote": "我转身冲向林总办公室", "nearby_anchor": "前台小妹",
             "a_code": "A2", "a_quote": "推开门", "qualifies": True},
        ],
    }, 5, failures)
    # 高档：≥4 事件 → F≥2 → 10
    check("B33", "high-four-events", {
        "finale_quote": "我转身离开，走出大楼", "events": [
            {"active_action_quote": "我冲进大楼", "nearby_anchor": "老张摇头",
             "a_code": "A1", "a_quote": "直奔人事部", "qualifies": True},
            {"active_action_quote": "我转身冲向林总办公室", "nearby_anchor": "前台小妹",
             "a_code": "A2", "a_quote": "推开门", "qualifies": True},
            {"active_action_quote": "我掏出手机", "nearby_anchor": "浑身发冷",
             "a_code": "A3", "a_quote": "拨通了法务部老同学的电话", "qualifies": True},
            {"active_action_quote": "我立刻截图保存证据", "nearby_anchor": "愣住了",
             "a_code": "A4", "a_quote": "给老周发了过去", "qualifies": True},
        ],
    }, 10, failures)
    # 边界：终局排除——事件落在末 15% 不计入 N
    check("B33", "boundary-finale-excluded", {
        "finale_quote": "我按下报警键", "events": [{
            "active_action_quote": "我按下报警键", "nearby_anchor": "老周这个律师朋友",
            "a_code": "A1", "a_quote": "电话那头传来接线员的声音", "qualifies": True,
        }],
    }, 0, failures)
    # 典型错误：a_quote 无效 span id（越界）→ 绑定空 → 不计
    check("B33", "err-no-evidence", {
        "finale_quote": "我转身离开，走出大楼", "events": [{
            "active_action_quote": "我冲进大楼", "nearby_anchor": "老张摇头",
            "a_code": "A1", "a_quote": 99999, "qualifies": True,
        }],
    }, "EVIDENCE_FAIL", failures)
    # 开放结局：finale_quote=null → 不排除任何事件（末段事件仍计 N=2 → F≈0.95 → 5 档）
    check("B33", "err-open-ending", {
        "finale_quote": None, "events": [
            {"active_action_quote": "我冲进大楼", "nearby_anchor": "老张摇头",
             "a_code": "A1", "a_quote": "直奔人事部", "qualifies": True},
            {"active_action_quote": "我按下报警键", "nearby_anchor": "老周这个律师朋友",
             "a_code": "A2", "a_quote": "电话那头传来接线员的声音", "qualifies": True},
        ],
    }, 5, failures)

    print("== C14 代入感（item_count 0-3 + x_max 细分） ==")
    # 低档：Y 否决 → 0
    check("C14", "low-y-veto", {
        "blocks": [{
            "block_quote": "按规矩，外来人员要登记。", "character": "门卫老张",
            "block_type": "对话", "a_body": None, "b_sensory": None, "c_inner": None,
            "y_flag": "Y1乱码", "x2_omniscient": False,
        }],
    }, 0, failures)
    # 中档：1 项 → 3
    check("C14", "mid-one-item", {
        "blocks": [{
            "block_quote": "我心里一沉", "character": "我",
            "block_type": "想法", "a_body": "我握紧拳头", "b_sensory": None,
            "c_inner": None, "y_flag": None, "x2_omniscient": False,
        }],
    }, 3, failures)
    # 高档：3 项 + x_max≤5% → 10（测试文本无 ≥51 字 c_inner，item_count=2 → 5）
    check("C14", "high-three-items", {
        "blocks": [
            {"block_quote": "我握紧拳头，指甲掐进掌心", "character": "我", "block_type": "直接感知",
             "a_body": "我握紧拳头，指甲掐进掌心", "b_sensory": "浑身发冷",
             "c_inner": "这不是误会，是陷害。", "y_flag": None, "x2_omniscient": False},
        ],
    }, 5, failures)
    # 边界：3 项 + 5%<x_max≤15% → 9（X1 少量非焦点块）；焦点由 Python 依 span 长度与场景数判定
    check("C14", "boundary-x-mid", {
        "blocks": [
            {"block_quote": "我掏出手机，拨通了法务部老同学的电话", "character": "我", "block_type": "直接感知",
             "a_body": "这不是误会，是陷害。我握紧拳头，指甲掐进掌心。", "b_sensory": "浑身发冷",
             "c_inner": "这不是误会，是陷害。", "y_flag": None,
             "x2_omniscient": False},
            {"block_quote": "林总干笑", "character": "林总", "block_type": "直接感知",
             "a_body": None, "b_sensory": None, "c_inner": None, "y_flag": None,
             "x2_omniscient": False},
        ],
    }, 5, failures)
    # 典型错误：character 非焦点角色 → A/B 不计
    check("C14", "err-nonfocal", {
        "blocks": [
            {"block_quote": "林总干笑", "character": "林总", "block_type": "直接感知",
             "a_body": "他站起身", "b_sensory": None, "c_inner": None,
             "y_flag": None, "x2_omniscient": False},
            {"block_quote": "我握紧拳头", "character": "我", "block_type": "直接感知",
             "a_body": None, "b_sensory": None, "c_inner": None,
             "y_flag": None, "x2_omniscient": False},
        ],
    }, 1, failures)

    print("== B36 核心驱动（criterion_count + axis_count 细分） ==")
    # 低档：0 项 → 0
    check("B36", "low-zero", {
        "axes": [{"axis": "P1", "axis_quote": "我靠在门边", "is_core": False, "core_scene_quotes": []}],
    }, 1, failures)
    # 中档：2 项 + 轴<4 → 3
    check("B36", "mid-two-axes", {
        "axes": [
            {"axis": "P1", "axis_quote": "系统显示你上周五就离职了", "is_core": True, "core_scene_quotes": ["你这工牌是旧的", "怎么会？我上周还在用。"]},
            {"axis": "P3", "axis_quote": "我冲进大楼", "is_core": False, "core_scene_quotes": []},
        ],
    }, 3, failures)
    # 高档：3 项 + 轴≥5 → 10
    check("B36", "high-three-axes", {
        "axes": [
            {"axis": "P1", "axis_quote": "系统显示你上周五就离职了", "is_core": True, "core_scene_quotes": ["你这工牌是旧的", "怎么会？我上周还在用。"]},
            {"axis": "P2", "axis_quote": "我冲进大楼", "is_core": False, "core_scene_quotes": []},
            {"axis": "P3", "axis_quote": "我冲进大楼", "is_core": False, "core_scene_quotes": []},
            {"axis": "P4", "axis_quote": "我冲进大楼", "is_core": False, "core_scene_quotes": []},
            {"axis": "P5", "axis_quote": "我冲进大楼", "is_core": False, "core_scene_quotes": []},
        ],
    }, 5, failures)
    # 边界：3 项 + 轴=4 → 9
    check("B36", "boundary-four-axes", {
        "axes": [
            {"axis": "P1", "axis_quote": "系统显示你上周五就离职了", "is_core": True, "core_scene_quotes": ["你这工牌是旧的", "怎么会？我上周还在用。"]},
            {"axis": "P2", "axis_quote": "我冲进大楼", "is_core": False, "core_scene_quotes": []},
            {"axis": "P3", "axis_quote": "我冲进大楼", "is_core": False, "core_scene_quotes": []},
            {"axis": "P4", "axis_quote": "我冲进大楼", "is_core": False, "core_scene_quotes": []},
        ],
    }, 5, failures)
    # 典型错误：轴重复 → 去重后不足 → 低档
    check("B36", "err-dup-axes", {
        "axes": [
            {"axis": "P1", "axis_quote": "系统显示你上周五就离职了", "is_core": True, "core_scene_quotes": ["你这工牌是旧的", "怎么会？我上周还在用。"]},
            {"axis": "P1", "axis_quote": "我冲进大楼", "is_core": False, "core_scene_quotes": []},
        ],
    }, 1, failures)

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("\nALL PASS")
    return 0


SIDECAR_TEXT, SIDECAR, OFFSETS = build_sidecar(TEXT)

if __name__ == "__main__":
    sys.exit(main())
