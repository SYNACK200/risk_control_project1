"""比较能力自测：时间维、数值维、分布维各走一遍。

这三类是「能不能按条件筛行」的全部答案，缺一类业务就得来找算法改代码。
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from rc_platform.capabilities.features import predicates as pred
from rc_platform.capabilities.features.operators import Frame
from rc_platform.core.contracts import TxnRow


def row(day: str = "2026-01-05", time: str | None = None, amount: str = "100", direction: str = "out") -> TxnRow:
    return TxnRow(txn_date=day, trade_time=time, amount=Decimal(amount), direction=direction)


def test_in_hours_filters_by_clock():
    frame = Frame([row(time="09:30"), row(time="18:00"), row(time="23:30")])
    mask = pred.op_in_hours(frame, start="18:00", end="23:59")
    assert mask.values == [False, True, True]


def test_in_hours_crosses_midnight():
    frame = Frame([row(time="23:30"), row(time="02:00"), row(time="12:00")])
    mask = pred.op_in_hours(frame, start="22:00", end="05:59")
    assert mask.values == [True, True, False]


def test_missing_time_returns_blank_not_false():
    """缺列必须是「空」，不能是「假」——否则会报 0 笔，把没数据说成没发生。"""
    frame = Frame([row(), row()])
    notes: list[str] = []
    mask = pred.op_in_hours(frame, start="18:00", end="23:59", notes=notes)
    assert mask.values == [None, None]
    assert any("trade_time" in note for note in notes)


def test_is_weekend_uses_calendar():
    frame = Frame([row("2026-01-03"), row("2026-01-05")])   # 周六 / 周一
    mask = pred.op_is_weekend(frame)
    assert mask.values == [True, False]


def test_in_months_selects_by_month():
    frame = Frame([row("2026-01-05"), row("2026-02-05"), row("2026-03-05")])
    mask = pred.op_in_months(frame, 1, 2)
    assert mask.values == [True, True, False]


def test_zscore_is_standardised():
    frame = Frame([row(amount="10"), row(amount="20"), row(amount="30")])
    mask = pred.op_zscore(frame)
    values = [float(v) for v in mask.values]
    assert abs(sum(values)) < 1e-9
    assert abs(values[0] + values[2]) < 1e-9      # 对称


def test_zscore_needs_two_rows():
    notes: list[str] = []
    assert pred.op_zscore(Frame([row()]), notes=notes).values == [None]
    assert notes


def test_pct_rank_is_monotone():
    frame = Frame([row(amount="10"), row(amount="20"), row(amount="30"), row(amount="40")])
    values = [float(v) for v in pred.op_pct_rank(frame).values]
    assert values == sorted(values)
    assert values[-1] == 1.0


def test_quantile_matches_numpy_default():
    frame = Frame([row(amount=str(n)) for n in (10, 20, 30, 40)])
    assert pred.op_quantile(frame, q=0.5) == Decimal("25")
    assert pred.op_quantile(frame, q=0) == Decimal("10")
    assert pred.op_quantile(frame, q=1) == Decimal("40")


def test_amount_between_is_absolute():
    frame = Frame([row(amount="-500"), row(amount="50"), row(amount="5000")])
    mask = pred.op_amount_between(frame, low=100, high=1000)
    assert mask.values == [True, False, False]


def test_zscore_threshold_composes_with_count():
    """分布比较的真实用法：count(where=zscore() > 3)。"""
    from rc_platform.capabilities.features.operators import Frame as F
    from rc_platform.capabilities.features.expr import eval_expr

    frame = F([row(amount=str(n)) for n in (10, 11, 12, 13, 14, 100)])
    value = eval_expr("count(where=zscore() > 2)", frame)
    assert value == 1

def test_mad_is_median_absolute_deviation():
    frame = Frame([row(amount=str(n)) for n in (10, 20, 30, 40, 900)])
    assert pred.op_mad(frame) == Decimal("10")


def test_iqr_uses_quantiles():
    frame = Frame([row(amount=str(n)) for n in (10, 20, 30, 40)])
    assert pred.op_iqr(frame) == Decimal("15.0")


def test_robust_zscore_flags_the_outlier():
    """长尾样本里 900 应该被挑出来，而普通 3σ 在这种情况下常常挑不出。"""
    frame = Frame([row(amount=str(n)) for n in (10, 20, 30, 40, 900)])
    values = [float(v) for v in pred.op_robust_zscore(frame).values]
    assert values[-1] > 3
    assert all(abs(value) < 2 for value in values[:-1])
