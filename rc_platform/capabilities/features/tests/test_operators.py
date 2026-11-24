"""算子库验收：四个算子族各算一遍、缺输入不填 0、Decimal 不进 float、报错要说人话。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from rc_platform.core.contracts import TxnRow

from .. import operators as ops
from . import sample_rows


def frame(*, drop: tuple[str, ...] = ()) -> ops.Frame:
    return ops.Frame(sample_rows(drop=drop))


def test_numeric_family_signed_and_unsigned():
    data = frame()
    assert ops.invoke("count", data) == 8
    # 数据帧上的 sum 是有符号净额；signed=false 才是金额绝对值合计
    assert ops.invoke("sum", data) == Decimal("12249.25")
    assert ops.invoke("sum", data, signed=False) == Decimal("38350.75")
    assert ops.invoke("mean", data, signed=False) == Decimal("38350.75") / Decimal(8)
    assert ops.invoke("median", data, signed=False) == Decimal("2100.25")
    assert ops.invoke("max", data) == Decimal("20000.00")
    assert ops.invoke("min", data) == Decimal("-7600.00")
    assert ops.invoke("max", data, column="balance") == Decimal("29999.50")


def test_std_and_cv_match_their_definition():
    data = frame()
    nums = [Decimal(text) for text in ("5000.00", "1200.50", "800.00", "3000.00",
                                       "20000.00", "450.25", "7600.00", "300.00")]
    mean = sum(nums) / Decimal(len(nums))
    expected_std = (sum((n - mean) ** 2 for n in nums) / Decimal(len(nums) - 1)).sqrt()
    assert ops.invoke("std", data, signed=False) == expected_std
    assert ops.invoke("cv", data, signed=False) == expected_std / mean
    single = ops.Frame([TxnRow(direction="out", amount=Decimal("10"))])
    assert ops.invoke("std", single) is None
    assert ops.invoke("cv", single) is None


def test_empty_input_gives_none_not_zero():
    empty = ops.Frame([])
    assert ops.invoke("sum", empty) is None
    assert ops.invoke("mean", empty) is None
    assert ops.invoke("max", empty) is None
    # 笔数是真的 0 笔，不是「填 0」
    assert ops.invoke("count", empty) == 0


def test_pct_change_and_series_stay_aligned_with_rows():
    series = ops.invoke("pct_change", frame())
    assert isinstance(series, ops.Series)
    assert len(series) == 8
    assert series.values[0] is None
    first, second = Decimal("5000.00"), Decimal("-1200.50")
    assert series.values[1] == (second - first) / abs(first)
    cumulative = ops.invoke("cumsum", ops.Frame([TxnRow(direction="in", amount=Decimal("1")),
                                                TxnRow(direction="in", amount=Decimal("2"))]))
    assert cumulative.values == [Decimal("1"), Decimal("3")]
    windowed = ops.invoke("window_sum", frame(), n=3)
    assert windowed.values[0] is None and windowed.values[1] is None
    assert windowed.values[2] is not None


def test_filter_family_keeps_sealed_semantics():
    out_frame = ops.invoke("filter_direction", frame(), value="out")
    assert isinstance(out_frame, ops.Frame) and len(out_frame) == 5
    assert ops.invoke("sum", out_frame, signed=False) == Decimal("13050.75")
    big = ops.invoke("filter_amount_abs_ge", frame(), value=5000)
    assert ops.invoke("count", big) == 3
    party = ops.invoke("filter_counterparty_contains", frame(), value="丙")
    assert ops.invoke("count", party) == 2


def test_steps_form_runs_sealed_custom_metric_shape():
    steps = [{"atom": "filter_direction", "args": {"value": "out"}},
             {"atom": "sum", "args": {"signed": False}}]
    assert ops.run_steps(steps, frame()) == Decimal("13050.75")
    assert ops.run_steps([{"atom": "group_by_counterparty"}, {"atom": "count"}], frame()) == 4


def test_group_family_aggregates_and_ranks():
    data = frame()
    sums = ops.invoke("sum_by", data, "counterparty_name", signed=False)
    assert sums["甲公司"] == Decimal("25800.00")
    assert ops.invoke("count_by", data, "counterparty_name")["丙公司"] == 2
    assert ops.invoke("mean_by", data, "counterparty_name", signed=False)["乙公司"] == Decimal("825.375")
    assert ops.invoke("distinct_count", data, "counterparty_name") == 4
    ranked = ops.invoke("rank_by", data, "counterparty_name", signed=False)
    assert list(ranked) == ["甲公司", "丙公司", "乙公司", "丁公司"]


def test_group_family_without_any_key_says_none():
    data = frame(drop=("counterparty_name",))
    assert ops.invoke("distinct_count", data, "counterparty_name") is None
    assert "counterparty_name" in data.missing


def test_monthly_grouping_and_monthly_agg():
    data = frame()
    months = ops.invoke("monthly", data)
    assert list(months) == ["2025-01", "2025-02", "2025-03"]
    out_frame = ops.invoke("filter_direction", data, value="out")
    assert ops.invoke("monthly_agg", out_frame, mode="sum", signed=False) == {
        "2025-01": Decimal("1200.50"),
        "2025-02": Decimal("3800.00"),
        "2025-03": Decimal("8050.25"),
    }
    with pytest.raises(ops.OperatorError):
        ops.invoke("monthly_agg", out_frame, mode="quantum")


def test_window_family_filters_and_buckets():
    data = frame()
    assert ops.invoke("count", ops.invoke("within_days", data, days=60)) == 6
    assert ops.invoke("count", ops.invoke("between_dates", data, start="2025-02-01", end="2025-02-28")) == 2
    assert ops.invoke("by_hour", data)["03"] == 1
    assert ops.invoke("count", ops.invoke("hour_band", data, band="night")) == 3
    assert ops.invoke("by_dow", data, mode="count")["周六"] == 2
    assert ops.invoke("span_days", data) == 87


def test_window_family_without_dates_says_none():
    data = frame(drop=("txn_date",))
    assert ops.invoke("span_days", data) is None
    assert "txn_date" in data.missing
    assert ops.invoke("within_days", data, days=90).rows == []


def test_logic_family_is_three_valued():
    assert ops.invoke("gt", Decimal("2"), 1) is True
    assert ops.invoke("ge", Decimal("1"), 1) is True
    assert ops.invoke("lt", Decimal("1"), 1) is False
    assert ops.invoke("le", Decimal("1"), 1) is True
    assert ops.invoke("eq", "out", "out") is True
    assert ops.invoke("ne", "out", "in") is True
    assert ops.invoke("gt", None, 1) is None
    assert ops.invoke("and", False, None) is False
    assert ops.invoke("and", True, None) is None
    assert ops.invoke("or", True, None) is True
    assert ops.invoke("not", None) is None
    assert ops.invoke("if_else", True, Decimal("1"), Decimal("0")) == Decimal("1")
    assert ops.invoke("if_else", None, Decimal("1"), Decimal("0")) is None


def test_unknown_operator_message_is_readable():
    with pytest.raises(ops.UnknownOperator) as info:
        ops.invoke("summ", frame())
    message = str(info.value)
    assert "未知算子" in message and "sum" in message


def test_wrong_input_kind_points_at_the_offending_step():
    steps = [{"atom": "sum"}, {"atom": "filter_direction", "args": {"value": "out"}}]
    with pytest.raises(ops.OperatorError) as info:
        ops.run_steps(steps, frame())
    message = str(info.value)
    assert "第 2 步" in message and "数据帧" in message


def test_describe_covers_all_required_operators_and_families():
    catalog = ops.describe()
    assert {item["family"] for item in catalog} == {"numeric", "logic", "group", "window", "filter"}
    assert len(catalog) >= 40
    assert ops.describe("sum")["unit"] == "元"
    assert ops.describe("sum")["compat"] is True
    for key in ("sum", "mean", "median", "std", "max", "min", "count", "pct_change", "cv",
                "gt", "ge", "lt", "le", "eq", "and", "or", "not", "if_else",
                "sum_by", "mean_by", "count_by", "distinct_count", "rank_by",
                "within_days", "between_dates", "monthly", "by_hour", "hour_band", "by_dow"):
        assert key in ops.operators(), key


def test_decimal_precision_never_falls_back_to_float():
    rows = [TxnRow(direction="in", amount=Decimal("0.1")),
            TxnRow(direction="in", amount=Decimal("0.2"))]
    total = ops.invoke("sum", ops.Frame(rows), signed=False)
    assert isinstance(total, Decimal)
    assert total == Decimal("0.3")
    assert not isinstance(total, float)
