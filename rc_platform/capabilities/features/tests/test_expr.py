"""表达式形态验收：优先级、括号、三值传播、除零不炸、报错能定位到字符。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from .. import expr, operators as ops
from . import sample_rows


def run(text: str, *, drop: tuple[str, ...] = ()):
    return expr.eval_expr(text, ops.Frame(sample_rows(drop=drop)))


def test_precedence_follows_arithmetic_order():
    assert run("1 + 2 * 3") == Decimal(7)
    assert run("2 * 3 + 4 * 5") == Decimal(26)
    assert run("10 - 4 - 3") == Decimal(3)


def test_parentheses_override_precedence():
    assert run("(1 + 2) * 3") == Decimal(9)
    assert run("(10 - 4) - 3") == Decimal(3)


def test_comparison_binds_tighter_than_and_or():
    assert run("1 + 1 == 2 and 3 > 2") is True
    assert run("1 + 1 == 3 or 3 > 2") is True
    assert run("1 + 1 == 3 and 3 > 2") is False


def test_conditional_is_elementwise_over_rows():
    assert run("sum(amount if direction=='out' else 0)") == Decimal("13050.75")
    assert run("count(amount if direction=='in' else none)") == 3


def test_null_propagates_through_arithmetic_and_logic():
    assert run("none + 1") is None
    assert run("1 - none") is None
    assert run("none == none") is None
    assert run("not none") is None
    assert run("none and false") is False
    assert run("none or true") is True


def test_division_by_zero_yields_none_and_a_reason():
    notes: list[str] = []
    assert expr.eval_expr("1 / 0", ops.Frame([]), notes=notes) is None
    assert any("分母" in note for note in notes)


def test_where_keyword_filters_rows():
    assert run("sum(amount, where=direction=='out')") == Decimal("13050.75")
    assert run("count(where=direction=='out')") == 5
    assert run("sum(amount, where=(direction=='out') and ((hour>=22) or (hour<=5)))") == Decimal("4650.75")


def test_group_key_accepts_column_name_or_string():
    assert run("max(sum_by(counterparty_name, signed=false))") == Decimal("25800.00")
    assert run("max(sum_by('counterparty_name', signed=false))") == Decimal("25800.00")
    assert run("count(monthly())") == 3


def test_arithmetic_between_two_aggregates():
    assert run("sum(amount, where=direction=='in') - sum(amount, where=direction=='out')") == Decimal("12249.25")


def test_unknown_function_names_the_operator():
    with pytest.raises(ops.UnknownOperator) as info:
        run("summ(amount)")
    assert "未知算子" in str(info.value)


def test_unknown_column_lists_available_ones():
    with pytest.raises(ops.UnknownColumn) as info:
        run("sum(foo)")
    assert "可用列" in str(info.value) and "amount" in str(info.value)


def test_syntax_errors_point_at_the_position():
    with pytest.raises(expr.ExprError) as info:
        expr.parse("sum(amount")
    assert "表达式语法错误" in str(info.value) and "^" in str(info.value)
    with pytest.raises(expr.ExprError):
        expr.parse("1 + ")
    with pytest.raises(expr.ExprError):
        expr.parse("")
    with pytest.raises(expr.ExprError) as chained:
        expr.parse("1 < 2 < 3")
    assert "链式比较" in str(chained.value)


def test_not_binds_looser_than_comparison():
    assert run("not 1 > 2") is True
    assert run("not (1 > 2 and 3 > 2)") is True


def test_string_literals_compare_as_text():
    assert expr.eval_expr("'out' == 'out'", ops.Frame([])) is True
    assert expr.eval_expr("'out' == 'in'", ops.Frame([])) is False
    assert run("count(where=counterparty_name=='甲公司')") == 3
