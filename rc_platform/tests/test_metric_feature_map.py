"""AL-102：特征-指标映射表的机器校验。

这张表的价值在于「40 行全有结论」。靠人眼看不住，所以让测试数一遍：
每项指标都在、没有待定、❌ 必须给出要补的特征名与表达式。
"""
from __future__ import annotations

import re
from pathlib import Path

from rc_platform.capabilities.metrics.mapping import ALL_CODES

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "特征指标映射.md"
STATUSES = {"✅", "⚠️", "❌"}


def _rows() -> list[tuple[str, str, str, str, str]]:
    text = DOC.read_text(encoding="utf-8")
    out: list[tuple[str, str, str, str, str]] = []
    for line in text.splitlines():
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 5 or not re.fullmatch(r"[A-E]\d{2}", cells[0]):
            continue
        out.append(tuple(cells))  # type: ignore[arg-type]
    return out


def test_document_exists_and_covers_all_40_metrics():
    assert DOC.exists(), f"缺少映射文档：{DOC}"
    rows = _rows()
    assert len(rows) == 40, f"应有 40 行，实际 {len(rows)}"
    codes = [row[0] for row in rows]
    assert len(set(codes)) == 40, "指标 code 有重复"
    assert set(codes) == set(ALL_CODES), "指标 code 与 ALL_CODES 不一致"


def test_every_row_has_a_conclusion_and_no_pending():
    for code, name, status, expression, difference in _rows():
        assert status in STATUSES, f"{code} 结论不在 ✅/⚠️/❌ 内：{status!r}"
        assert ALL_CODES[code] == name, f"{code} 名称不一致：{name}"
        assert expression, f"{code} 缺少表达式/特征"
        assert difference, f"{code} 缺少差异说明"
        assert "待定" not in expression + difference, f"{code} 仍有「待定」"


def test_missing_rows_name_the_feature_to_add():
    for code, _, status, expression, _ in _rows():
        if status == "❌":
            assert "f_" in expression, f"{code} 标了 ❌ 但没写要补的特征名"
            assert "=" in expression, f"{code} 标了 ❌ 但没写表达式"


def test_summary_counts_match_rows():
    text = DOC.read_text(encoding="utf-8")
    match = re.search(r"✅\s*(\d+)\s*项、⚠️\s*(\d+)\s*项、❌\s*(\d+)\s*项", text)
    assert match, "总览结论行找不到"
    expected = tuple(int(value) for value in match.groups())
    actual = tuple(
        sum(1 for row in _rows() if row[2] == status)
        for status in ("✅", "⚠️", "❌")
    )
    assert actual == expected, f"总览与明细不一致：总览 {expected} / 明细 {actual}"