"""版式检测自测：用合成样本当对照物。

判据不是「看起来对」，而是「四个版式的关键列都长出来了」：
工行/招行必须认得出日期、金额、余额；建行是收支分列；微信没有余额列，认不出余额才是对的。
"""
from __future__ import annotations

import pathlib

import pytest

from rc_platform.capabilities.layout.detect import detect_layout, detect_page
from rc_platform.capabilities.layout.legacy import to_legacy_layout
from rc_platform.capabilities.layout.words import read_pages

ROOT = pathlib.Path(__file__).resolve().parents[4]
SAMPLES = ROOT / "algorithm" / "inputs" / "samples" / "synthetic"

needs_samples = pytest.mark.skipif(not SAMPLES.exists(), reason="合成样本未生成")


def fields_of(name: str) -> set[str]:
    pages = read_pages((SAMPLES / "clean" / f"{name}.pdf").read_bytes())
    plan = detect_layout(pages)
    return {col.field for region in plan.regions for col in region.columns}


@needs_samples
def test_icbc_has_date_amount_balance():
    fields = fields_of("icbc")
    assert {"txn_date", "amount", "balance"} <= fields


@needs_samples
def test_ccb_splits_income_and_expense():
    fields = fields_of("ccb")
    assert "txn_date" in fields and "balance" in fields
    # 收入列在这批样本里大部分为空，但表头认出来了就必须留列带：
    # 删掉它，收入金额会被就近吸进支出金额，方向直接判反
    assert {"amount_in", "amount_out"} <= fields


@needs_samples
def test_cmb_has_direction_column():
    assert "direction" in fields_of("cmb")


@needs_samples
def test_wechat_has_no_balance_column():
    fields = fields_of("wechat")
    assert {"txn_date", "amount"} <= fields
    assert "balance" not in fields, "微信账单没有余额列，长出来就是误判"


@needs_samples
def test_short_page_falls_back_to_header_geometry():
    """末页只有一两行时不能整页丢掉：退到表头位置档。"""
    pages = read_pages((SAMPLES / "forged" / "icbc_row_deleted.pdf").read_bytes())
    plan = detect_layout(pages)
    assert len(plan.regions) == len(pages), "每一页都应该有几何结论"


@needs_samples
def test_layout_survives_missing_header_row():
    """把表头整行删掉，仍应靠几何聚类认出列（表头坏了不等于读不出来）。"""
    pages = read_pages((SAMPLES / "clean" / "icbc.pdf").read_bytes())
    page = pages[0]
    # 去掉第一行（表头）的词，模拟「表头被裁掉/识别不出」
    first_top = min(w.top for w in page.words)
    page.words = [w for w in page.words if w.top > first_top + 1]
    region = detect_page(page)
    assert region is not None, "没有表头也应该能靠几何聚类认出表格"
    assert len(region.columns) >= 2


@needs_samples
def test_legacy_layout_is_page_normalized():
    pages = read_pages((SAMPLES / "clean" / "icbc.pdf").read_bytes())
    legacy = to_legacy_layout(detect_layout(pages))
    assert legacy["tables"], "至少要有一张表"
    for table in legacy["tables"]:
        area = table["area"]
        assert 0 <= area["x"] <= 1 and 0 <= area["y"] <= 1
        assert 0 < area["w"] <= 1 and 0 < area["h"] <= 1
        for column in table["columns"]:
            assert 0 <= column["x"] <= 1 and 0 < column["w"] <= 1
