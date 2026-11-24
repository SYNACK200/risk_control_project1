"""指标口径算子自测：这些算子决定指标数值，语义错一位整张报告就错。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from rc_platform.capabilities.features.operators import Frame
from rc_platform.core.contracts import TxnRow
from rc_platform.capabilities.metrics import ops_metrics as ops


def row(day: str, amount: str, balance: str | None = None, direction: str = "in",
        counterparty: str | None = None) -> TxnRow:
    return TxnRow(txn_date=day, direction=direction, amount=Decimal(amount),
                  balance=None if balance is None else Decimal(balance),
                  counterparty_name=counterparty)


def test_coverage_months_never_drops_below_one():
    """4 天的流水如果按 4/31 个月折算，月均收入会被放大 7 倍。"""
    frame = Frame([row("2026-10-01", "100"), row("2026-10-04", "100")])
    assert ops.op_coverage_months(frame) == Decimal("1")


def test_coverage_months_counts_partial_months():
    """1/15–2/15 = 17/31 + 15/28 ≈ 1.084，不是「两个整月」。"""
    frame = Frame([row("2026-01-15", "1"), row("2026-02-15", "1")])
    months = ops.op_coverage_months(frame)
    assert Decimal("1.08") < months < Decimal("1.09")


def test_monthly_values_fills_empty_months_with_zero():
    frame = Frame([row("2026-01-05", "100"), row("2026-03-05", "300")])
    series = ops.op_monthly_values(frame, agg="sum")
    assert list(series.values) == [Decimal("100"), Decimal("0"), Decimal("300")]


def test_daily_balances_carry_forward_on_idle_days():
    frame = Frame([row("2026-01-01", "10", "100"), row("2026-01-03", "10", "90")])
    series = ops.op_daily_balances(frame)
    assert list(series.values) == [Decimal("100"), Decimal("100"), Decimal("90")]


def test_overdraft_days_counts_negative_days_only():
    frame = Frame([row("2026-01-01", "1", "-5"), row("2026-01-02", "1", "-3"),
                   row("2026-01-03", "1", "2")])
    assert ops.op_overdraft_days(frame) == Decimal("2")


def test_share_square_sum_and_top_share():
    frame = Frame([row("2026-01-01", "50", counterparty="甲"),
                   row("2026-01-02", "30", counterparty="乙"),
                   row("2026-01-03", "20", counterparty="丙")])
    hhi = ops.op_share_square_sum(frame)
    assert hhi == Decimal("0.25") + Decimal("0.09") + Decimal("0.04")
    assert ops.op_top_share(frame, k=2) == Decimal("0.8")


def test_pstdev_is_population_not_sample():
    frame = Frame([row("2026-01-01", "1", "2"), row("2026-01-02", "1", "4")])
    assert ops.op_pstdev(frame) == Decimal("1")
