"""模板必需列的判定：两处（试跑诊断、报告限制说明）必须同一个口径。

真实反例：建行版式把金额拆成「收入金额 / 支出金额」两列，没有 amount 列——
按字段名一对一判，会误报「模板缺列 amount」，报告里凭空多一条限制说明。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.template_checks import missing_required  # noqa: E402


SPLIT_AMOUNT = {"txn_date": 0, "summary": 1, "amount_in": 3, "amount_out": 4, "balance": 5}
SINGLE_AMOUNT = {"txn_date": 0, "summary": 1, "amount": 3, "balance": 5}


def test_split_amount_satisfies_amount():
    assert missing_required(SPLIT_AMOUNT, ["txn_date", "amount", "balance"]) == []


def test_split_amount_satisfies_direction():
    assert missing_required(SPLIT_AMOUNT, ["direction"]) == []


def test_truly_missing_column_is_reported():
    assert missing_required(SPLIT_AMOUNT, ["txn_date", "account_no"]) == ["account_no"]


def test_single_amount_column_is_fine_too():
    assert missing_required(SINGLE_AMOUNT, ["txn_date", "amount", "balance"]) == []


def test_trade_time_satisfies_txn_date():
    assert missing_required({"trade_time": 0, "amount": 1, "balance": 2}, ["txn_date"]) == []


def test_empty_required_or_field_map_is_safe():
    assert missing_required(None, None) == []
    assert missing_required(SPLIT_AMOUNT, []) == []
    assert missing_required({}, ["amount"]) == ["amount"]
