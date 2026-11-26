"""AL-101：统一解析入口的回归。

这三个入口必须给出同一份结果：直接调 parse_statement、Lab 的 _statement_from_bytes、
CLI 的 run_file。差异只允许出现在报告层，不允许出现在「解析出多少行、日期覆盖多少」。
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from rc_platform.capabilities.parse import entry
from rc_platform.core.contracts import Statement, TxnRow

ROOT = Path(__file__).resolve().parents[4]
SAMPLE = ROOT / "algorithm" / "inputs" / "samples" / "synthetic" / "clean" / "icbc.pdf"


def test_rows_input_is_converted_without_reparsing():
    statement = entry.parse_statement(
        rows=[
            {
                "txn_date": "2021-05-13",
                "direction": "in",
                "amount": "9671.74",
                "balance": "9691.67",
                "summary": "工资",
                "counterparty": "某公司",
            }
        ]
    )
    assert statement.meta["parser_used"] == "rows"
    assert statement.meta["row_count"] == 1
    assert statement.meta["dated_ratio"] == 1.0
    row = statement.rows[0]
    assert row.amount == Decimal("9671.74")
    assert row.balance == Decimal("9691.67")
    assert row.counterparty_name == "某公司"
    assert row.row_no == 1


def test_rows_input_keeps_page_count():
    statement = entry.parse_statement(rows=[{"page_no": 2, "txn_date": "2021-05-13"}])
    assert statement.page_count == 3


def test_rows_win_when_both_inputs_are_given():
    statement = entry.parse_statement(
        data=b"%PDF-1.4 fake",
        rows=[{"txn_date": "2021-05-13", "amount": "1.00"}],
    )
    assert statement.meta["parser_used"] == "rows"


def test_bad_amount_is_rejected_instead_of_zero():
    with pytest.raises(entry.ParseFailed):
        entry.parse_statement(rows=[{"amount": "not-a-number"}])


def test_pdf_uses_layout_v2_and_records_meta():
    statement = entry.parse_statement(data=SAMPLE.read_bytes(), profile={"carrier": "electronic"})
    assert statement.meta["parser_used"] == "layout_v2"
    assert statement.meta["row_count"] == len(statement.rows) == 6
    assert statement.meta["dated_ratio"] == 1.0


def test_low_dated_ratio_falls_back_to_legacy(monkeypatch):
    layout = Statement(rows=[TxnRow(amount=Decimal("1.00")) for _ in range(3)])
    legacy = Statement(
        rows=[TxnRow(txn_date="2021-05-13", amount=Decimal("1.00")) for _ in range(3)]
    )
    monkeypatch.setattr(entry, "_run_layout", lambda data, profile: layout)
    monkeypatch.setattr(entry, "_run_legacy", lambda data: legacy)

    statement = entry.parse_statement(data=b"%PDF-1.4 fake")
    assert statement.meta["parser_used"] == "legacy_fallback"
    assert statement.meta["layout_dated_ratio"] == 0.0
    assert statement.meta["legacy_dated_ratio"] == 1.0
    assert "fallback_reason" in statement.meta


def test_missing_page_falls_back_even_when_dates_are_complete(monkeypatch):
    """招行 2 页件实测：只出第 1 页时日期仍 100%，必须靠页覆盖发现整页丢失。"""
    layout = Statement(
        page_count=2,
        rows=[TxnRow(txn_date="2026-08-30", amount=Decimal("1.00")) for _ in range(2)],
    )
    legacy = Statement(
        page_count=2,
        rows=[TxnRow(txn_date="2026-08-30", amount=Decimal("1.00")) for _ in range(4)],
    )
    monkeypatch.setattr(entry, "_run_layout", lambda data, profile: layout)
    monkeypatch.setattr(entry, "_run_legacy", lambda data: legacy)

    statement = entry.parse_statement(data=b"%PDF-1.4 fake")
    assert statement.meta["parser_used"] == "legacy_fallback"
    assert statement.meta["layout_page_coverage"] == 0.5
    assert statement.meta["page_coverage"] == 0.5


def test_missing_page_without_better_result_keeps_layout(monkeypatch):
    layout = Statement(
        page_count=2,
        rows=[TxnRow(txn_date="2026-08-30", amount=Decimal("1.00")) for _ in range(3)],
    )
    legacy = Statement(
        page_count=2,
        rows=[TxnRow(txn_date="2026-08-30", amount=Decimal("1.00")) for _ in range(2)],
    )
    monkeypatch.setattr(entry, "_run_layout", lambda data, profile: layout)
    monkeypatch.setattr(entry, "_run_legacy", lambda data: legacy)

    statement = entry.parse_statement(data=b"%PDF-1.4 fake")
    assert statement.meta["parser_used"] == "layout_v2"
    assert any("只覆盖" in warning for warning in statement.warnings)


def test_fallback_without_improvement_keeps_layout(monkeypatch):
    layout = Statement(rows=[TxnRow(txn_date="2021-05-13", amount=Decimal("1.00"))])
    monkeypatch.setattr(entry, "_run_layout", lambda data, profile: layout)
    monkeypatch.setattr(entry, "_run_legacy", lambda data: None)

    statement = entry.parse_statement(data=b"%PDF-1.4 fake")
    assert statement.meta["parser_used"] == "layout_v2"
    assert statement.meta["dated_ratio"] == 1.0


def test_both_paths_failing_raises_with_reasons(monkeypatch):
    def boom(data, profile):
        raise RuntimeError("layout broken")

    monkeypatch.setattr(entry, "_run_layout", boom)
    monkeypatch.setattr(entry, "_run_legacy", lambda data: None)

    with pytest.raises(entry.ParseFailed) as caught:
        entry.parse_statement(data=b"%PDF-1.4 fake")
    assert "layout broken" in str(caught.value)


def test_no_input_is_rejected():
    with pytest.raises(entry.ParseFailed):
        entry.parse_statement()


def test_lab_and_cli_entries_agree_with_library():
    """三入口一致性：直接调用 / Lab / CLI 的 row_count 与 dated_ratio 必须相同。"""
    from rc_platform.api.app import _statement_from_bytes
    from rc_platform.cli import run_file

    data = SAMPLE.read_bytes()
    library = entry.parse_statement(data=data, profile={"carrier": "electronic"})
    lab = _statement_from_bytes(data, SAMPLE.name)
    cli = run_file(SAMPLE)

    assert lab.meta["row_count"] == library.meta["row_count"]
    assert lab.meta["dated_ratio"] == library.meta["dated_ratio"]
    assert cli["txn_count"] == library.meta["row_count"]
    assert cli["dated_ratio"] == library.meta["dated_ratio"]
    assert cli["parser_used"] == library.meta["parser_used"]