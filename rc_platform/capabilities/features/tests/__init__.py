"""测试共用的合成样本：8 笔、跨 3 个月、覆盖夜间与周末，四种算子族都有可验的数据。

为什么不含糊地用「随便几笔」：缺列口径要能被验证（余额列/时间列各自可以摘掉），
所以样本按「能逐项手工核对」的方式固定下来，改样本等于改口径，必须同步改断言。
"""
from __future__ import annotations

from decimal import Decimal

from rc_platform.core.contracts import Statement, TxnRow

_SAMPLE: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("2025-01-03", "09:15:00", "in", "5000.00", "15000.00", "甲公司"),
    ("2025-01-15", "23:40:00", "out", "1200.50", "13799.50", "乙公司"),
    ("2025-02-05", "14:20:00", "out", "800.00", "12999.50", "甲公司"),
    ("2025-02-18", "22:05:00", "out", "3000.00", "9999.50", "丙公司"),
    ("2025-03-01", "08:30:00", "in", "20000.00", "29999.50", "甲公司"),
    ("2025-03-12", "03:10:00", "out", "450.25", "29549.25", "乙公司"),
    ("2025-03-29", "16:45:00", "out", "7600.00", "21949.25", "丙公司"),
    ("2025-03-30", "11:00:00", "in", "300.00", "22249.25", "丁公司"),
)


def sample_rows(*, drop: tuple[str, ...] = ()) -> list[TxnRow]:
    """造样本；drop 用来摘掉整列（例如 "balance"、"trade_time"），验证缺列口径。"""
    rows = []
    for index, (day, clock, direction, amount, balance, party) in enumerate(_SAMPLE, 1):
        rows.append(TxnRow(
            txn_date=None if "txn_date" in drop else day,
            trade_time=None if "trade_time" in drop else clock,
            direction=None if "direction" in drop else direction,
            amount=None if "amount" in drop else Decimal(amount),
            balance=None if "balance" in drop else Decimal(balance),
            counterparty_name=None if "counterparty_name" in drop else party,
            summary="测试",
            row_no=index,
        ))
    return rows


def sample_statement(**kwargs) -> Statement:
    return Statement(rows=sample_rows(**kwargs), page_count=1)
