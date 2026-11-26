"""AL-106：边界输入不让特征悄悄变成 0，也不让进程崩溃。"""
from __future__ import annotations

from decimal import Decimal

from rc_platform.core.contracts import Statement, TxnRow

from .. import defs
from . import sample_rows


def _got(rows):
    return {record["code"]: record for record in defs.compute(defs.BUILTIN_FEATURES, Statement(rows=rows)).records}


def test_zero_rows_counts_are_real_zero_others_are_none():
    got = _got([])
    assert got["f_txn_count"]["value"] == 0
    assert got["f_txn_count"]["reason"] is None
    assert got["f_out_total"]["value"] is None
    assert got["f_out_total"]["reason"]["code"] == "no_rows"


def test_one_row_does_not_crash_and_explains_incomplete_period():
    row = TxnRow(txn_date="2025-01-01", direction="out", amount=Decimal("-100.00"))
    got = _got([row])
    assert got["f_txn_count"]["value"] == 1
    assert got["f_out_total"]["value"] == Decimal("-100.00")
    assert got["f_in_cv"]["value"] is None
    assert got["f_in_cv"]["reason"]["code"] == "insufficient_period"
    assert got["f_balance_min"]["reason"]["code"] == "missing_column"


def test_negative_amount_is_not_silently_zeroed():
    """金额为负当前不拦：按原值计入，便于先看到异常，而不是被 0 掩盖。"""
    row = TxnRow(txn_date="2025-01-01", direction="out", amount=Decimal("-100.00"))
    got = _got([row])
    assert got["f_out_total"]["value"] == Decimal("-100.00")
    assert got["f_out_total"]["reason"] is None


def test_all_missing_columns_still_return_standard_reason_codes():
    rows = sample_rows(drop=("trade_time", "balance", "counterparty_name"))
    for record in _got(rows).values():
        if record["value"] is None:
            assert record["reason"]["code"] in defs.REASON_CODES, record["code"]