"""特征定义验收：记录形状、缺列口径、不算出标量就报错、版本随定义走。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from rc_platform.core.contracts import Statement

from .. import defs
from . import sample_rows


def records(**kwargs):
    return {record["code"]: record for record in defs.compute(defs.BUILTIN_FEATURES, Statement(rows=sample_rows(**kwargs))).records}


def test_builtin_definitions_are_well_formed():
    features = defs.BUILTIN_FEATURES
    assert len(features) >= 12
    codes = [definition.code for definition in features]
    assert len(codes) == len(set(codes))
    for definition in features:
        assert definition.name and definition.unit
        assert bool(definition.steps) != bool(definition.expr)
        assert definition.description


def test_compute_returns_contract_shaped_records():
    result = defs.compute(defs.BUILTIN_FEATURES, Statement(rows=sample_rows()), version="2.0")
    assert result.version == "2.0"
    assert len(result.records) == len(defs.BUILTIN_FEATURES)
    for record in result.records:
        assert set(record) == {"code", "name", "value", "unit", "reason", "version"}
        if record["value"] is not None:
            assert record["reason"] == ""
        else:
            assert record["reason"], record["code"]


def test_missing_balance_column_is_none_and_explained():
    got = records(drop=("balance",))
    for code in ("f_balance_min", "f_balance_last"):
        assert got[code]["value"] is None
        assert "balance" in got[code]["reason"]
        assert got[code]["value"] != 0


def test_missing_time_column_is_none_and_explained():
    got = records(drop=("trade_time",))
    assert got["f_night_count"]["value"] is None
    assert "trade_time" in got["f_night_count"]["reason"]


def test_missing_direction_column_is_none_and_explained():
    got = records(drop=("direction",))
    assert got["f_out_total"]["value"] is None
    assert "direction" in got["f_out_total"]["reason"]


def test_empty_statement_says_no_rows_and_count_is_real_zero():
    result = defs.compute(defs.BUILTIN_FEATURES, Statement())
    got = {record["code"]: record for record in result.records}
    assert got["f_out_total"]["value"] is None
    assert "明细为空" in got["f_out_total"]["reason"]
    # 笔数为 0 是真的 0 笔，不是「缺输入填 0」
    assert got["f_txn_count"]["value"] == 0
    assert got["f_txn_count"]["reason"] == ""


def test_no_value_is_ever_a_float():
    got = records()
    for record in got.values():
        assert not isinstance(record["value"], float), record["code"]
    assert isinstance(got["f_out_total"]["value"], Decimal)
    assert isinstance(got["f_txn_count"]["value"], int)
    assert isinstance(got["f_top_counterparty_share"]["value"], Decimal)


def test_definition_requires_exactly_one_form():
    with pytest.raises(defs.FeatureDefError):
        defs.FeatureDef(code="x", name="两种形态都缺")
    with pytest.raises(defs.FeatureDefError):
        defs.FeatureDef(code="x", name="两种形态都有", expr="count()", steps=[{"atom": "count"}])
    with pytest.raises(defs.FeatureDefError):
        defs.FeatureDef(code="x", name="steps 不是列表", steps="count")
    with pytest.raises(defs.FeatureDefError):
        defs.FeatureDef(code="x", name="步骤缺 atom", steps=[{"args": {}}])


def test_steps_that_end_with_a_series_are_rejected():
    definition = defs.FeatureDef(code="x", name="序列没收尾", steps=[{"atom": "pct_change"}])
    with pytest.raises(defs.FeatureDefError) as info:
        defs.compute([definition], Statement(rows=sample_rows()))
    assert "标量" in str(info.value)


def test_unknown_operator_inside_a_definition_names_the_feature():
    definition = defs.FeatureDef(code="x_typo", name="拼错算子", expr="summ(amount)")
    with pytest.raises(defs.FeatureDefError) as info:
        defs.compute([definition], Statement(rows=sample_rows()))
    message = str(info.value)
    assert "x_typo" in message and "未知算子" in message


def test_definition_version_and_unit_are_kept():
    definition = defs.FeatureDef(code="x_custom", name="自定义出账笔数", unit="笔", version="3.1",
                                 expr="count(where=direction=='out')")
    result = defs.compute([definition], Statement(rows=sample_rows()))
    record = result.records[0]
    assert record == {"code": "x_custom", "name": "自定义出账笔数", "value": 5,
                      "unit": "笔", "reason": "", "version": "3.1"}
