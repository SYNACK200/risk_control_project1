"""版式读取与扩散回归测试：覆盖旋转 PDF、双语副表头、换行时间列、复合表头与多单值前缀。"""
from __future__ import annotations

import pymupdf

from rc_platform.capabilities.layout import detect, inspect as li, keywords as kw
from rc_platform.capabilities.layout.words import PageWords, Word, read_pages


def test_compact_date_and_plus_amount_shapes():
    assert kw.is_date("20210513")
    assert not kw.is_money("20210513")
    assert kw.is_date("20210513 09:12:33")
    assert kw.is_money("+4986.78")
    assert kw.is_money("-4274.80")
    assert kw.is_direction("收(Cr)")
    assert kw.is_direction("付(Dr)")


def test_rotated_pdf_words_and_singles_are_aligned():
    doc = pymupdf.open()
    # 595x842 未旋转页面上竖排写字（rotate=90）再整体顺时针旋转 90°，对应真实横向扫描/导出 PDF（如建行样例）
    page = doc.new_page(width=595, height=842)
    def put(dx: float, dy: float, text: str, **kw_args):
        page.insert_text((dy, 842 - dx), text, fontsize=10, rotate=90, **kw_args)

    put(40, 60, "卡号/账号:6217007200012345678   客户名称：张三", fontname="china-ss")
    put(40, 100, "交易日期", fontname="china-ss")
    put(180, 100, "交易金额", fontname="china-ss")
    put(300, 100, "账户余额", fontname="china-ss")
    put(420, 100, "交易摘要", fontname="china-ss")
    for row_idx in range(4):
        y = 130 + row_idx * 22
        put(40, y, f"2024050{row_idx + 1}")
        put(180, y, f"{100 + row_idx}.00")
        put(300, y, f"{1000 + row_idx}.00")
        put(420, y, "工资入账", fontname="china-ss")
    page.set_rotation(90)
    pdf_bytes = doc.tobytes()
    doc.close()

    pages = read_pages(pdf_bytes)
    assert pages[0].width == 842.0 and pages[0].height == 595.0
    for w in pages[0].words:
        assert 0.0 <= w.x0 <= w.x1 <= pages[0].width
        assert 0.0 <= w.top <= w.bottom <= pages[0].height

    res = li.inspect(pdf_bytes, ocr_fallback=False)
    p0 = res["pages"][0]
    fields = {b["field"]: b for b in p0["bands"]}
    assert {"txn_date", "amount", "balance", "summary"} <= set(fields)
    assert len(fields["txn_date"]["cells"]) == 4
    singles = {s["field"]: s for s in p0["singles"]}
    assert singles["account_no"]["value"] == "6217007200012345678"
    assert singles["account_name"]["value"] == "张三"
    assert 0.0 <= singles["account_no"]["h"] <= 0.1


def test_bilingual_subheader_is_not_collected_as_data():
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((40, 80), "户   名：李四     开   户   行：合肥高新支行", fontsize=10, fontname="china-ss")
    page.insert_text((40, 130), "记账日期", fontsize=10, fontname="china-ss")
    page.insert_text((180, 130), "交易金额", fontsize=10, fontname="china-ss")
    page.insert_text((320, 130), "联机余额", fontsize=10, fontname="china-ss")
    page.insert_text((40, 146), "Date", fontsize=9)
    page.insert_text((180, 146), "Amount", fontsize=9)
    page.insert_text((320, 146), "Balance", fontsize=9)
    for row_idx in range(3):
        y = 175 + row_idx * 22
        page.insert_text((40, y), f"2026-08-0{row_idx + 1}", fontsize=10)
        page.insert_text((180, y), f"{200 + row_idx}.00", fontsize=10)
        page.insert_text((320, y), f"{2000 + row_idx}.00", fontsize=10)
    pdf_bytes = doc.tobytes()
    doc.close()

    res = li.inspect(pdf_bytes, ocr_fallback=False)
    p0 = res["pages"][0]
    fields = {b["field"]: b for b in p0["bands"]}
    assert [c["text"] for c in fields["txn_date"]["cells"]] == ["2026-08-01", "2026-08-02", "2026-08-03"]
    singles = {s["field"]: s["value"] for s in p0["singles"]}
    assert singles["account_name"] == "李四"
    assert singles["bank_branch"] == "合肥高新支行"


def test_composite_ocr_header_splits_into_distinct_columns():
    words = [
        Word("序号交易日期交易时间交易方式收支标志", 40, 450, 100, 130),
        Word("交易金额", 470, 560, 100, 130),
        Word("余额", 620, 690, 100, 130),
    ]
    for idx in range(4):
        top = 150 + idx * 45
        bot = top + 28
        words.extend([
            Word(str(idx + 1), 42, 58, top, bot),
            Word(f"2023010{idx + 1}", 95, 170, top, bot),
            Word("10:00:00", 190, 265, top, bot),
            Word("汇款汇入", 280, 355, top, bot),
            Word("收(Cr)", 380, 440, top, bot),
            Word(f"{100 + idx}.00", 475, 555, top, bot),
            Word(f"{1000 + idx}.00", 615, 700, top, bot),
        ])
    region = detect.detect_page(PageWords(0, 800, 1000, words, True))
    assert region is not None
    fields = {c.field for c in region.columns}
    assert {"txn_date", "summary", "direction", "amount", "balance"} <= fields
