from datetime import date
from decimal import Decimal

from algorithm.algo.metrics import METRIC_SET_VERSION, compute_metrics
from algorithm.ocr.models import Transaction


def _txn(
    day: str,
    summary: str | None,
    *,
    direction: str = "in",
    amount: str = "0",
    balance: str = "0",
    counterparty: str | None = None,
    row: int = 1,
) -> Transaction:
    return Transaction(
        page_no=1,
        row_no=row,
        txn_date=day,
        summary=summary,
        counterparty_name=counterparty,
        direction=direction,
        amount=Decimal(amount),
        balance=Decimal(balance),
    )


def _history() -> list[Transaction]:
    return [
        _txn("2026-01-05", "工资", amount="10000", balance="10000", counterparty="甲公司", row=1),
        _txn("2026-01-10", "消费", direction="out", amount="2000", balance="8000", counterparty="商户", row=2),
        _txn("2026-02-05", "代发工资", amount="10000", balance="18000", counterparty="甲公司", row=3),
        _txn("2026-02-15", "还款", direction="out", amount="3000", balance="15000", counterparty="信用卡中心", row=4),
        _txn("2026-03-05", "工资", amount="10000", balance="25000", counterparty="甲公司", row=5),
        _txn("2026-03-20", "取现", direction="out", amount="1000", balance="24000", counterparty="ATM", row=6),
    ]


def _compute(**kwargs):
    defaults = dict(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 3, 31),
        holder_name="张三",
        opening_balance=Decimal("0"),
    )
    defaults.update(kwargs)
    return compute_metrics(_history(), **defaults)


def test_all_forty_metrics_present_and_versioned():
    result = _compute()
    assert result.metric_set_version == METRIC_SET_VERSION
    assert len(result.metrics) == 40
    assert [metric.code for metric in result.metrics] == [
        *(f"A{index:02d}" for index in range(1, 9)),
        *(f"B{index:02d}" for index in range(1, 9)),
        *(f"C{index:02d}" for index in range(1, 9)),
        *(f"D{index:02d}" for index in range(1, 9)),
        *(f"E{index:02d}" for index in range(1, 9)),
    ]
    assert all(metric.caliber_version == 1 for metric in result.metrics)


def test_income_metrics_use_excluded_totals():
    result = _compute()
    assert result.by_code("A01").value == Decimal("30000.00")
    assert result.by_code("A02").value == Decimal("10000.00")
    assert result.by_code("A03").value == Decimal("10000.00")
    assert result.by_code("A04").value == Decimal("0.0000")
    assert result.by_code("A05").value == Decimal("1.0000")
    assert result.by_code("A06").value == Decimal("1.0000")
    assert result.by_code("A07").value == Decimal("0.00")
    assert result.by_code("A08").value == Decimal("0.0000")
    assert result.exclusions is not None
    assert result.exclusions.inflow_before == Decimal("30000")


def test_liability_and_liquidity_metrics():
    result = _compute()
    assert result.by_code("B01").value == Decimal("1000.00")
    assert result.by_code("B02").value == Decimal("0.1000")
    assert result.by_code("B03").value == Decimal("0")
    assert result.by_code("B07").value == Decimal("0")
    assert result.by_code("B08").value == Decimal("0.0000")
    assert result.by_code("C01").value == Decimal("24000.00")
    assert result.by_code("C02").value == Decimal("5.0000")
    assert result.by_code("C03").value is not None
    assert result.by_code("C06").value == Decimal("15000.00")
    assert result.by_code("C07").value == Decimal("0.1667")


def test_behavior_metrics():
    result = _compute()
    assert result.by_code("D01").value == Decimal("0.0000")
    assert result.by_code("D02").value is None
    assert "trade_time" in result.by_code("D02").note
    assert result.by_code("D03").value == Decimal("1.0000")
    assert result.by_code("D04").value is None
    assert result.by_code("D05").value == Decimal("0.2778")
    assert result.by_code("D06").value == Decimal("0")
    assert result.by_code("D07").value == Decimal("0.0000")
    assert result.by_code("D08").value == Decimal("0.0000")


def test_counterparty_metrics():
    result = _compute(related_names={"甲公司"})
    assert result.by_code("E01").value == Decimal("0.7052")
    assert result.by_code("E02").value == Decimal("0.9722")
    assert result.by_code("E03").value == Decimal("0.8333")
    assert result.by_code("E04").value is None
    assert result.by_code("E06").value == Decimal("0.0000")
    assert result.by_code("E07").value == Decimal("0.0000")
    assert result.by_code("E08").value == Decimal("0.0000")


def test_missing_relation_data_returns_null():
    result = _compute()
    assert result.by_code("E03").value is None
    assert "关系数据" in result.by_code("E03").note


def test_labels_enable_loan_and_gambling_rates():
    labels = [set() for _ in _history()]
    labels[0] = {"LOAN"}
    labels[1] = {"GAMBLING"}
    result = _compute(labels=labels)
    assert result.by_code("E04").value == Decimal("0.1667")
    assert result.by_code("E05").value == Decimal("0.1667")


def test_trade_time_enables_night_ratio():
    times = ["10:00", "23:30", "09:00", "02:00", "12:00", "18:00"]
    result = _compute(trade_times=times)
    assert result.by_code("D02").value == Decimal("0.3333")


def test_trade_time_defaults_to_transaction_field():
    history = _history()
    history[0].trade_time = "23:10:00"
    history[1].trade_time = "09:00:00"
    result = compute_metrics(
        history,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 3, 31),
        holder_name="张三",
        opening_balance=Decimal("0"),
    )
    assert result.by_code("D02").value == Decimal("0.5")


def test_large_amount_threshold():
    result = _compute(large_amount_threshold=Decimal("5000"))
    assert result.by_code("D04").value == Decimal("3")


def test_loan_inflow_counts_and_platforms():
    history = _history() + [
        _txn(
            "2026-03-10",
            "消费金融放款",
            amount="50000",
            balance="74000",
            counterparty="某消费金融公司",
            row=7,
        )
    ]
    result = compute_metrics(
        history,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 3, 31),
        opening_balance=Decimal("0"),
    )
    assert result.by_code("B03").value == Decimal("1")
    assert result.by_code("B04").value == Decimal("1")
    assert result.by_code("A01").value == Decimal("30000.00")


def test_same_day_in_out_ratio():
    history = [
        _txn("2026-01-05", "转账", amount="1000", balance="1000", counterparty="甲", row=1),
        _txn("2026-01-05", "转账", direction="out", amount="1000", balance="0", counterparty="乙", row=2),
        _txn("2026-01-06", "工资", amount="500", balance="500", counterparty="丙", row=3),
    ]
    result = compute_metrics(history)
    assert result.by_code("C08").value == Decimal("0.6667")


def test_empty_input_returns_all_nulls_without_guessing():
    result = compute_metrics([])
    assert len(result.metrics) == 40
    assert all(metric.value is None for metric in result.metrics)
    for code in ("A01", "B05", "B06"):
        assert result.by_code(code).note == "无交易明细"
    assert result.by_code("A02").value is None
    assert result.by_code("C03").value is None
    assert result.by_code("E06").value is None
    assert all(metric.note for metric in result.metrics)


def test_repeated_computation_is_identical():
    first = _compute()
    second = _compute()
    assert [(m.code, m.value, m.note) for m in first.metrics] == [
        (m.code, m.value, m.note) for m in second.metrics
    ]
