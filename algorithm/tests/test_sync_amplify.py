from __future__ import annotations

from datetime import date
from decimal import Decimal

from algorithm.algo.merge import AccountInput, merge_accounts, mode_catalog
from algorithm.ocr.models import Transaction


def txn(day, direction, amount, summary="消费"):
    return Transaction(page_no=1, row_no=1, txn_date=day, direction=direction,
                       amount=Decimal(amount), balance=Decimal("0"), summary=summary)


def accounts_same_month():
    a = AccountInput("a", "CMB", date(2026, 1, 1), date(2026, 3, 31), [
        txn("2026-02-05", "in", "10000"), txn("2026-02-20", "out", "9000"),
        txn("2026-03-05", "in", "10000"), txn("2026-03-20", "out", "9000"),
    ])
    b = AccountInput("b", "CMB", date(2026, 1, 1), date(2026, 3, 31), [
        txn("2026-02-06", "in", "10000"), txn("2026-02-21", "out", "9000"),
        txn("2026-03-06", "in", "10000"), txn("2026-03-21", "out", "9000"),
    ])
    return [a, b]


def accounts_disjoint_months():
    a = AccountInput("a", "CMB", date(2026, 1, 1), date(2026, 1, 31), [
        txn("2026-01-05", "in", "10000"), txn("2026-01-20", "out", "9000")])
    b = AccountInput("b", "CMB", date(2026, 2, 1), date(2026, 2, 28), [
        txn("2026-02-05", "in", "10000"), txn("2026-02-20", "out", "9000")])
    return [a, b]


def test_sync_amplify_mode_is_listed():
    keys = [m["key"] for m in mode_catalog()]
    assert "sync_amplify" in keys


def test_sync_month_amplifies_risk_metric() -> None:
    result = merge_accounts(accounts_same_month(), "sync_amplify")
    sync = result["sync"]
    assert sync is not None
    assert sync["sync_months"], "两个账户同月大额流出应识别为同步月"
    factor = Decimal(sync["amplify_factor"])
    assert factor > 1

    sum_result = merge_accounts(accounts_same_month(), "sum")
    sync_values = {m["code"]: Decimal(m["value"]) for m in result["metrics"] if m["value"]}
    sum_values = {m["code"]: Decimal(m["value"]) for m in sum_result["metrics"] if m["value"]}
    amplified = [
        code for code in sync_values
        if code in sum_values and sync_values[code] != sum_values[code]
    ]
    assert amplified, "应有风险型指标被放大"
    for code in amplified:
        assert sync_values[code] > sum_values[code], code


def test_disjoint_months_do_not_amplify() -> None:
    result = merge_accounts(accounts_disjoint_months(), "sync_amplify")
    assert result["sync"]["sync_months"] == []
    assert Decimal(result["sync"]["amplify_factor"]) == Decimal(1)
