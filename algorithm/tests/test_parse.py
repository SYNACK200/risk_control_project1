from decimal import Decimal

import fitz
import pytest

from algorithm.ocr import OcrUnavailable, Template, parse


def make_pdf(pages, header, xs, footer=None):
    doc = fitz.open()
    for page_index, rows in enumerate(pages):
        page = doc.new_page(width=800, height=1000)
        page.insert_text((40, 60), "银行账户交易明细", fontsize=12, fontname="china-s")
        y = 90
        for label, x in zip(header, xs):
            page.insert_text((x, y), label, fontsize=7, fontname="china-s")
        last_y = y
        for row_index, row in enumerate(rows, start=1):
            last_y = y + 18 * row_index
            for value, x in zip(row, xs):
                page.insert_text((x, last_y), value, fontsize=7, fontname="china-s")
        if footer and page_index == len(pages) - 1:
            page.insert_text((40, last_y + 24), footer, fontsize=7, fontname="china-s")
    data = doc.tobytes()
    doc.close()
    return data


BANK_HEADER = ["交易日期", "摘要", "对方户名", "借贷标志", "交易金额", "余额"]
BANK_XS = [40, 200, 380, 480, 560, 660]
BANK_ROWS = [
    ["2026-01-05", "工资", "某公司", "贷", "12,500.00", "13,200.00"],
    ["2026-01-06", "消费", "某超市", "借", "300.50", "12,899.50"],
    ["2026-01-07", "转账", "张三", "借", "1,000.00", "11,899.50"],
]


def test_bank_statement_single_page():
    pdf = make_pdf([BANK_ROWS], BANK_HEADER, BANK_XS, footer="共 3 笔记录")
    result = parse(pdf)

    assert result.page_count == 1
    assert result.footer_count == 3
    assert len(result.transactions) == 3
    assert result.field_completeness == 1.0
    assert result.avg_confidence == 1.0
    assert result.low_conf_ratio == 0.0

    first, second = result.transactions[0], result.transactions[1]
    assert first.txn_date == "2026-01-05"
    assert first.trade_time is None
    assert first.amount == Decimal("12500.00")
    assert first.balance == Decimal("13200.00")
    assert first.direction == "in"
    assert second.direction == "out"
    assert second.amount == Decimal("300.50")
    assert first.bbox is not None
    assert not any("不一致" in w for w in result.warnings)


def test_bank_statement_cross_page():
    page1 = BANK_ROWS[:2]
    page2 = [["2026-02-01", "还款", "某银行", "借", "2,000.00", "9,899.50"]]
    pdf = make_pdf([page1, page2], BANK_HEADER, BANK_XS, footer="共 3 笔记录")
    result = parse(pdf)

    assert result.page_count == 2
    assert len(result.transactions) == 3
    assert result.footer_count == 3
    assert result.transactions[2].page_no == 2
    assert result.transactions[2].row_no == 3


def test_wechat_style_statement_without_balance():
    header = ["交易时间", "交易类型", "交易对方", "商品", "收/支", "金额(元)", "支付方式", "当前状态", "交易单号"]
    xs = [30, 115, 190, 280, 355, 405, 465, 515, 560]
    rows = [
        ["2026-10-01", "商户消费", "某便利店", "饮料", "支出", "¥12.50", "零钱", "支付成功", "4200001"],
        ["2026-10-02", "转账", "李四", "转账", "收入", "¥200.00", "零钱", "已入账", "4200002"],
    ]
    pdf = make_pdf([rows], header, xs, footer="共 2 笔交易")
    result = parse(pdf)

    assert result.footer_count == 2
    assert len(result.transactions) == 2
    first, second = result.transactions
    assert first.direction == "out"
    assert first.amount == Decimal("12.50")
    assert first.balance is None
    assert "饮料" in first.summary
    assert second.direction == "in"


def test_template_maps_custom_header_aliases():
    header = ["发生日", "用途", "对手", "方向", "发生额", "结余"]
    rows = [["2026-03-01", "工资", "某公司", "贷", "8,000.00", "9,000.00"]]
    template = Template(
        bank_code="TEST",
        version=1,
        field_map={
            "txn_date": "发生日",
            "summary": "用途",
            "counterparty": "对手",
            "direction": "方向",
            "amount": "发生额",
            "balance": "结余",
        },
    )
    result = parse(make_pdf([rows], header, BANK_XS), template=template)

    assert len(result.transactions) == 1
    txn = result.transactions[0]
    assert txn.txn_date == "2026-03-01"
    assert txn.amount == Decimal("8000.00")
    assert txn.direction == "in"


def make_icbc_like_pdf(rows, per_page_footer):
    """模拟工行版式：合并表头、第二行时间、摘要/户名折行、按页笔数页脚。"""
    header = ["交易日期", "账号", "储种", "序号", "币种", "钞汇", "摘要", "地区", "收入/支出金额", "余额", "对方户名", "对方账号", "渠道"]
    xs = [40, 110, 200, 250, 290, 320, 350, 400, 440, 540, 600, 680, 760]
    doc = fitz.open()
    page = doc.new_page(width=800, height=1000)
    y = 90
    for label, x in zip(header, xs):
        page.insert_text((x, y), label, fontsize=7, fontname="china-s")
    last_y = y
    for row_index, row in enumerate(rows, start=1):
        last_y = y + 18 * row_index
        page.insert_text((xs[0], last_y), row["date"], fontsize=7, fontname="china-s")
        page.insert_text((xs[6], last_y), row["summary"], fontsize=7, fontname="china-s")
        page.insert_text((xs[8], last_y), row["amount"], fontsize=7, fontname="china-s")
        page.insert_text((xs[9], last_y), row["balance"], fontsize=7, fontname="china-s")
        page.insert_text((xs[10], last_y), row["counterparty"], fontsize=7, fontname="china-s")
        page.insert_text((xs[0], last_y + 7), row["time"], fontsize=7, fontname="china-s")
        if row.get("summary_extra"):
            page.insert_text((xs[6], last_y + 7), row["summary_extra"], fontsize=7, fontname="china-s")
        if row.get("counterparty_extra"):
            page.insert_text((xs[10], last_y + 7), row["counterparty_extra"], fontsize=7, fontname="china-s")
    page.insert_text((40, last_y + 24), "本页支出金额合计：29.00", fontsize=7, fontname="china-s")
    page.insert_text((40, last_y + 38), f"本页交易笔数：{per_page_footer}", fontsize=7, fontname="china-s")
    data = doc.tobytes()
    doc.close()
    return data


def test_icbc_like_layout_signed_amount_and_page_footer():
    rows = [
        {
            "date": "2026-05-01", "time": "09:41:20", "summary": "零钱通提",
            "summary_extra": "现", "amount": "+13.31", "balance": "37.89",
            "counterparty": "财付通支付科技有", "counterparty_extra": "限公司",
        },
        {
            "date": "2026-05-01", "time": "09:46:05", "summary": "消费",
            "amount": "-29.00", "balance": "8.89", "counterparty": "中移支付有限公司",
        },
    ]
    result = parse(make_icbc_like_pdf(rows, 2))

    assert len(result.transactions) == 2
    assert result.footer_count == 2
    first, second = result.transactions
    assert first.direction == "in"
    assert first.amount == Decimal("13.31")
    assert first.trade_time == "09:41:20"
    assert first.summary == "零钱通提现"
    assert first.counterparty_name == "财付通支付科技有限公司"
    assert second.direction == "out"
    assert second.amount == Decimal("29.00")
    assert second.trade_time == "09:46:05"
    assert second.balance == Decimal("8.89")


def test_trade_time_on_date_line_and_normalized():
    header = ["交易日期", "时间", "摘要", "借贷标志", "交易金额", "余额"]
    xs = [40, 150, 250, 420, 520, 600]
    rows = [
        ["2026-10-01", "9:41:20", "消费", "借", "12.50", "100.00"],
        ["2026-10-02", "15:39", "转账", "借", "8.00", "92.00"],
    ]
    result = parse(make_pdf([rows], header, xs))

    assert [txn.trade_time for txn in result.transactions] == ["09:41:20", "15:39:00"]
    assert result.transactions[0].txn_date == "2026-10-01"
    assert result.transactions[0].summary == "消费"


def test_parse_clock_rejects_non_time():
    from algorithm.ocr.parse import parse_clock

    assert parse_clock("15:39:23") == "15:39:23"
    assert parse_clock("23:59") == "23:59:00"
    assert parse_clock("9:05:03") == "09:05:03"
    assert parse_clock("2026-05-01") is None
    assert parse_clock("24:00:00") is None
    assert parse_clock("12:60:00") is None
    assert parse_clock("") is None


def test_encrypted_pdf_returns_e_encrypt_hint():
    raw = make_pdf([BANK_ROWS], BANK_HEADER, BANK_XS)
    doc = fitz.open(stream=raw, filetype="pdf")
    encrypted = doc.tobytes(
        encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user"
    )
    doc.close()

    result = parse(encrypted)

    assert result.transactions == []
    assert any("E_ENCRYPT" in warning for warning in result.warnings)


def test_falls_back_to_pdfplumber_when_fitz_finds_no_rows(monkeypatch):
    from importlib import import_module

    parse_module = import_module("algorithm.ocr.parse")

    raw = make_pdf([BANK_ROWS], BANK_HEADER, BANK_XS, footer="共 3 笔记录")
    monkeypatch.setattr(parse_module, "_fitz_extract", lambda _: ([], 1, 0, True, False))

    result = parse_module.parse(raw)

    assert len(result.transactions) == 3
    assert any("回退 pdfplumber" in warning for warning in result.warnings)


def test_invalid_image_raises_ocr_unavailable():
    with pytest.raises(OcrUnavailable):
        parse(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)


def test_empty_and_unsupported_input():
    assert parse(b"").warnings == ["空文件"]
    assert parse(b"hello").warnings == ["不支持的文件格式"]
