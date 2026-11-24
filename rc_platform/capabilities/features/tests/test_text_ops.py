"""文本比较与词库自测。

判据不是「能不能跑」，而是「命中/不命中/缺列」三种情况能不能分清——
把缺列当不命中，就会把 14 项语义指标悄悄算成 0。
"""
from __future__ import annotations

from decimal import Decimal

from rc_platform.capabilities.features import lexicon, text_ops
from rc_platform.capabilities.features.operators import Frame
from rc_platform.core.contracts import TxnRow


def row(summary: str | None = "转账", counterparty: str | None = "张三", amount: str = "100") -> TxnRow:
    return TxnRow(txn_date="2026-01-05", summary=summary, counterparty_name=counterparty,
                  amount=Decimal(amount), direction="out")


def test_contains_matches_summary():
    frame = Frame([row("工资代发"), row("消费")])
    assert text_ops.op_contains(frame, word="工资").values == [True, False]


def test_contains_ignores_case_and_space():
    frame = Frame([row("ATM 取款")])
    assert text_ops.op_contains(frame, word="atm取款").values == [True]


def test_contains_on_missing_column_returns_blank():
    frame = Frame([row(summary=None), row(summary=None)])
    notes: list[str] = []
    mask = text_ops.op_contains(frame, word="工资", notes=notes)
    assert mask.values == [None, None]
    assert notes


def test_matches_supports_regex():
    frame = Frame([row("贷款发放-张三"), row("贷款还款")])
    assert text_ops.op_matches(frame, pattern="贷款发放").values == [True, False]


def test_matches_reports_bad_regex():
    import pytest

    with pytest.raises(text_ops.OperatorError):
        text_ops.op_matches(Frame([row()]), pattern="(")


def test_in_lexicon_uses_default_words():
    frame = Frame([row("工资"), row("绩效奖金"), row("买菜")])
    assert text_ops.op_in_lexicon(frame, name="salary").values == [True, True, False]


def test_lexicon_is_overridable(tmp_path, monkeypatch):
    monkeypatch.setattr(lexicon, "STORE_PATH", tmp_path / "lexicons.json")
    lexicon.save_override("salary", ["手工费"])
    assert "手工费" in lexicon.resolve("salary")
    assert "工资" not in lexicon.resolve("salary")
    entry = [item for item in lexicon.catalog() if item["name"] == "salary"][0]
    assert entry["overridden"] is True and entry["version"] >= 1


def test_unknown_lexicon_is_reported():
    import pytest

    with pytest.raises(text_ops.OperatorError):
        text_ops.op_in_lexicon(Frame([row()]), name="不存在的词库")
