"""Declarative ordinal mapping interpreter (Step 12.5 Step 4).

Single rule source: every threshold, breakpoint, and condition count lives in
the spec YAML, not in Python. Each ``ordinal_mapping`` item is:

    - score: 10
      when: {field: F, op: gte, value: 0.50}

    - score: 1
      when: {field: F, op: gte, value: 0.20}
      and:  {field: F, op: lt, value: 0.30}

Operators: lt, lte, gt, gte, eq, ne, in, not_in, is_true, is_false.
The interpreter evaluates each item in declared order and returns the first
matching score. This is the ONLY scoring path; Python never hardcodes a
threshold.
"""
from __future__ import annotations

from typing import Any

from .derived import DerivedContext

_OPERATORS: dict[str, Any] = {}


def _op(name: str):
    def wrap(fn):
        _OPERATORS[name] = fn
        return fn
    return wrap


@_op("lt")
def _lt(value, target):
    return value < target


@_op("lte")
def _lte(value, target):
    return value <= target


@_op("gt")
def _gt(value, target):
    return value > target


@_op("gte")
def _gte(value, target):
    return value >= target


@_op("eq")
def _eq(value, target):
    return value == target


@_op("ne")
def _ne(value, target):
    return value != target


@_op("in")
def _in(value, target):
    return value in target


@_op("not_in")
def _not_in(value, target):
    return value not in target


@_op("is_true")
def _is_true(value, _target=None):
    return bool(value) is True


@_op("is_false")
def _is_false(value, _target=None):
    return bool(value) is False


def _eval_condition(cond: dict[str, Any], ctx: DerivedContext) -> bool:
    """Evaluate one condition dict against the derived context."""
    op = cond["op"]
    field = cond["field"]
    value = ctx.get(field)
    if op in ("is_true", "is_false"):
        fn = _OPERATORS[op]
        return fn(value)
    fn = _OPERATORS[op]
    return fn(value, cond["value"])


def _eval_when(when: dict[str, Any], ctx: DerivedContext) -> bool:
    """Evaluate a when clause: a single condition or and/or/not tree."""
    if "and" in when:
        return all(_eval_condition(c, ctx) for c in when["and"])
    if "or" in when:
        return any(_eval_condition(c, ctx) for c in when["or"])
    if "not" in when:
        return not _eval_condition(when["not"], ctx)
    return _eval_condition(when, ctx)


def score_from_mapping(spec, ctx: DerivedContext) -> int:
    """Evaluate the spec's declarative ordinal_mapping in declared order."""
    mapping = spec.data["ordinal_mapping"]
    for item in mapping:
        if not isinstance(item, dict) or "score" not in item:
            raise KeyError(f"ordinal_mapping item for {spec.metric_id} must have 'score': {item!r}")
        if "when" in item and _eval_when(item["when"], ctx):
            return int(item["score"])
        if "when" not in item:
            # bare {score: N} acts as a catch-all fallback
            return int(item["score"])
    raise ValueError(f"no ordinal branch matched for {spec.metric_id}")
