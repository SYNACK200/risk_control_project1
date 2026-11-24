"""两种作者形态的等价性：同一语义两组写法必须得到同一个数、同一个类型。

为什么单独一组测试：步骤形态与表达式形态一旦分家，最典型的症状就是「口径一样、数不一样」，
而这类偏差在报表里看不出来，只能靠这里逐对固定下来。
"""
from __future__ import annotations

from decimal import Decimal

from .. import defs, expr, operators as ops
from . import sample_rows


def both(steps: list[dict], text: str):
    return (ops.run_steps(steps, ops.Frame(sample_rows())),
            expr.eval_expr(text, ops.Frame(sample_rows())))


def test_in_total_steps_equals_expr():
    steps = [{"atom": "filter_direction", "args": {"value": "in"}},
             {"atom": "sum", "args": {"signed": False}}]
    by_steps, by_expr = both(steps, "sum(amount, where=direction=='in')")
    assert by_steps == by_expr == Decimal("25300.00")
    assert isinstance(by_steps, Decimal) and isinstance(by_expr, Decimal)


def test_out_count_steps_equals_expr():
    steps = [{"atom": "filter_direction", "args": {"value": "out"}}, {"atom": "count"}]
    by_steps, by_expr = both(steps, "count(where=direction=='out')")
    assert by_steps == by_expr == 5


def test_night_out_total_steps_equals_expr():
    steps = [{"atom": "filter_direction", "args": {"value": "out"}},
             {"atom": "hour_band", "args": {"band": "night"}},
             {"atom": "sum", "args": {"signed": False}}]
    text = "sum(amount, where=(direction=='out') and ((hour>=22) or (hour<=5)))"
    by_steps, by_expr = both(steps, text)
    assert by_steps == by_expr == Decimal("4650.75")


def test_night_count_steps_equals_expr():
    steps = [{"atom": "hour_band", "args": {"band": "night"}}, {"atom": "count"}]
    by_steps, by_expr = both(steps, "count(where=(hour>=22) or (hour<=5))")
    assert by_steps == by_expr == 3


def test_same_semantics_through_compute_agrees_across_forms():
    """同一条口径写两遍定义，走 compute 也必须得到同一个值。"""
    statement = defs.Statement(rows=sample_rows())
    by_expr = defs.FeatureDef(code="t_expr_out", name="出账总额（表达式）", unit="元",
                              expr="sum(amount, where=direction=='out')")
    by_steps = defs.FeatureDef(code="t_steps_out", name="出账总额（步骤）", unit="元",
                               steps=[{"atom": "filter_direction", "args": {"value": "out"}},
                                      {"atom": "sum", "args": {"signed": False}}])
    records = {r["code"]: r for r in defs.compute([by_expr, by_steps], statement).records}
    assert records["t_expr_out"]["value"] == records["t_steps_out"]["value"] == Decimal("13050.75")
    assert records["t_expr_out"]["unit"] == records["t_steps_out"]["unit"] == "元"
