"""Spec-driven prompt generation. The spec is the only rule source."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..preprocessing.paragraphs import format_paragraph_view  # noqa: F401  (kept for callers)
from ..preprocessing.spans import format_span_view
from .output_schema import derive_output_schema
from .specs import MetricSpec

PROMPT_VERSION = "v5.1-prompt-9"

# The LLM is prohibited from emitting deterministic fields. The prompt states
# the contract; the validator enforces it.
_FORBIDDEN_STATEMENT = (
    "严禁输出 L/K/F/offset/码点位置/比例/阈值/最终分数等确定性计算字段；"
    "这些全部由程序计算。只输出语义判断与逐字引文。"
)


def _format_spec_field(field: Any) -> str:
    if isinstance(field, dict):
        lines = []
        for key, value in field.items():
            if isinstance(value, str):
                lines.append(f"- {key}: {value}")
            else:
                lines.append(f"- {key}: {json.dumps(value, ensure_ascii=False)}")
        return "\n".join(lines)
    if isinstance(field, list):
        return "\n".join(f"- {item}" for item in field)
    return str(field)


def build_prompt(spec: MetricSpec, canonical_text: str) -> str:
    """Build the scoring prompt for one metric from its frozen spec.

    The JSON schema embedded here is the SAME schema the validator and the
    extractor use (Step 12.5 Step 2): prompt format = validator format =
    extractor format.
    """
    d = spec.data
    schema = derive_output_schema(spec.semantic_outputs)
    sections = [
        "# 指标",
        f"指标：{spec.metric_id}（{d['construct']}）",
        f"规格版本：{spec.version}",
        "",
        "# 语义定义",
        d["semantic_definition"].strip(),
        "",
        "# 输出要求",
        "只输出一个 JSON 对象，必须完全符合下面的 JSON Schema：",
        "不要用 markdown 代码围栏；第一个非空白字符必须是 {。",
        json.dumps(schema, ensure_ascii=False, indent=2),
        "确认不存在符合条件的候选不等于 ABSTAIN：应 status=OK 且对应数组为空",
        "（如 candidates/conflicts/events=[]）。测量结果为零仍是 OK。",
        "ABSTAIN 仅用于无法确认边界、缺少必要证据、两种解释均合理、或证据冲突",
        "（此时不输出 semantic 字段，reason 说明原因）。",
        _FORBIDDEN_STATEMENT,
        "",
        "# 语义字段说明",
        _format_spec_field(spec.semantic_outputs),
        "",
        "# 证据引文规则",
        str(d["evidence_rule"]).strip(),
        "",
        "# 证据绑定（程序填原文）",
        "Canonical Text 已按句/回合标注 S001、S002…；编号只是定位标签，不是评分用的自然段号，不要输出 L/q/offset。",
        "所有 *_quote、decoding_evidence、nearby_anchor 必须输出对应 evidence span 的整数编号（S012 → 12）。",
        "禁止输出引文字符串；禁止把「S012」或编号前缀写进字段；程序用该 span 在 canonical 中的原文填入 quote。",
        "qualifies=true 或 item_hits 含 true 时，同一对象必须有有效 span id；否则填 false 或删除该候选。",
        "找不到该 span、编号越界或仍输出字符串，该证据作废。确认无候选时 status=OK 且对应数组为空。",
        "**若某 *_quote 的 span 原文可能在正文出现多次（短句/常用词/无标点片段），该对象必须同时提供 nearby_anchor**",
        "（邻近唯一上下文片段的 span 编号）帮助 Python 唯一定位；未提供导致歧义拒绝时该证据作废，不要依赖程序猜测。",
        "",
        "# Canonical Text（以下为完整 canonical text，已经提供）",
        "不要以 canonical text 未提供为由 ABSTAIN；下面的 Canonical Text 即待分析全文。",
        format_span_view(canonical_text) if canonical_text else "",
    ]
    return "\n".join(sections)


def prompt_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()
