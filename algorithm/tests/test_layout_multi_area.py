"""同页多表格区：明细表 + 汇总表都在一页时，两块都要能读到。

这家的真实流水常把「账户信息/汇总」和「明细」印在同一页；
只裁第一个框会把第二块整段丢掉，行数直接少一半。
"""
from __future__ import annotations

from algorithm.ocr.parse import _layout_areas_for, _crop_by_layout
from algorithm.ocr.table import Word


def word(text: str, x0: float, top: float, x1: float | None = None, bottom: float | None = None) -> Word:
    return Word(text=text, x0=x0, x1=x1 if x1 is not None else x0 + 20,
                top=top, bottom=bottom if bottom is not None else top + 8)


def layout_single() -> dict:
    return {
        "page_size": {"w": 800.0, "h": 1000.0},
        "tables": [{"page": 0, "slot": "first", "area": {"x": 0.05, "y": 0.10, "w": 0.90, "h": 0.40},
                    "columns": []}],
    }


def layout_two_on_one_page() -> dict:
    return {
        "page_size": {"w": 800.0, "h": 1000.0},
        "tables": [
            {"page": 0, "slot": "first", "area": {"x": 0.05, "y": 0.10, "w": 0.90, "h": 0.25}, "columns": []},
            {"page": 0, "slot": "first", "area": {"x": 0.05, "y": 0.55, "w": 0.90, "h": 0.35}, "columns": []},
        ],
    }


def test_single_table_behaves_as_before():
    areas = _layout_areas_for(layout_single(), 0, 1)
    assert len(areas) == 1


def test_two_tables_same_page_both_resolved():
    areas = _layout_areas_for(layout_two_on_one_page(), 0, 1)
    assert len(areas) == 2


def test_crop_keeps_words_in_either_block():
    words = [
        word("明细行1", 100, 200),      # 第一块（y 100–350）
        word("汇总行", 100, 700),       # 第二块（y 550–900）
        word("页脚落款", 100, 970),     # 两块之外（表头之上 12% 是刻意保留的，所以放页脚）
    ]
    kept = _crop_by_layout(words, layout_two_on_one_page(), 0, 1)
    texts = [w.text for w in kept]
    assert "明细行1" in texts
    assert "汇总行" in texts
    assert "页脚落款" not in texts


def test_crop_falls_back_when_nothing_matches():
    """框外全被裁掉时要退回原词表，不能把整页读成空。"""
    words = [word("只有页脚", 100, 985)]
    kept = _crop_by_layout(words, layout_two_on_one_page(), 0, 1)
    assert [w.text for w in kept] == ["只有页脚"]
