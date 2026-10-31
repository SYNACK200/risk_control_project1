from decimal import Decimal
from pathlib import Path

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


def make_pdf_with_page_headers(header_lines, pages):
    """表头上方按行插入页眉，用于验证账号/户名/期间抽取。"""
    doc = fitz.open()
    for page_index, rows in enumerate(pages):
        page = doc.new_page(width=800, height=1000)
        for offset, text in enumerate(header_lines[page_index]):
            page.insert_text((40, 30 + 12 * offset), text, fontsize=9, fontname="china-s")
        page.insert_text((40, 60), "银行账户交易明细", fontsize=12, fontname="china-s")
        y = 90
        for label, x in zip(BANK_HEADER, BANK_XS):
            page.insert_text((x, y), label, fontsize=7, fontname="china-s")
        for row_index, row in enumerate(rows, start=1):
            for value, x in zip(row, BANK_XS):
                page.insert_text((x, y + 18 * row_index), value, fontsize=7, fontname="china-s")
    data = doc.tobytes()
    doc.close()
    return data


def test_page_header_fields_extracted_per_page():
    lines = ["卡号 6222 **** **** 1234 户名： 张三", "期间： 2026-01-01 至 2026-12-31"]
    pdf = make_pdf_with_page_headers([lines, lines], [BANK_ROWS[:2], BANK_ROWS[2:]])
    result = parse(pdf)

    assert len(result.headers) == 2
    for header in result.headers:
        assert header.account_no.value == "6222********1234"
        assert header.account_name.value == "张三"
        assert (header.period_start.value, header.period_end.value) == (
            "2026-01-01",
            "2026-12-31",
        )
        assert header.account_no.bbox is not None


def test_page_header_period_with_time_component():
    line = "交易明细对应时间段 2026-07-29 00:00:00 至 2026-10-29 14:33:31"
    result = parse(make_pdf_with_page_headers([[line]], [BANK_ROWS]))

    header = result.headers[0]
    assert (header.period_start.value, header.period_end.value) == (
        "2026-07-29",
        "2026-10-29",
    )
    assert header.account_no is None and header.account_name is None


def test_page_without_header_is_recorded_empty():
    line = "卡号 6222 **** **** 1234 户名： 张三"
    pdf = make_pdf_with_page_headers([[line], []], [BANK_ROWS[:2], BANK_ROWS[2:]])
    result = parse(pdf)

    assert result.headers[0].account_no.value == "6222********1234"
    assert result.headers[1].is_empty


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


def test_reference_number_column_extracted():
    header = ["交易日期", "摘要", "借贷标志", "交易金额", "余额", "交易流水号"]
    xs = [40, 140, 300, 400, 500, 620]
    rows = [
        ["2026-01-05", "工资", "贷", "100.00", "1100.00", "202601050001"],
        ["2026-01-06", "消费", "借", "50.00", "1050.00", "202601060002"],
    ]
    result = parse(make_pdf([rows], header, xs))

    assert [txn.reference_no for txn in result.transactions] == [
        "202601050001",
        "202601060002",
    ]


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


CMB_HEADER = ["记账日期", "货币", "交易金额", "联机余额", "交易摘要", "对手信息"]
CMB_XS = [40, 160, 240, 340, 440, 530]


def make_cmb_like_pdf(rows, footer_y=None, footer_lines=None):
    doc = fitz.open()
    page = doc.new_page(width=800, height=1000)
    page.insert_text((40, 60), "招商银行交易流水", fontsize=12, fontname="china-s")
    y = 110
    for label, x in zip(CMB_HEADER, CMB_XS):
        page.insert_text((x, y), label, fontsize=7, fontname="china-s")
    last_y = y
    for index, row in enumerate(rows, start=1):
        last_y = y + 20 * index
        for value, x in zip(row, CMB_XS):
            page.insert_text((x, last_y), value, fontsize=7, fontname="china-s")
    for line in footer_lines or []:
        page.insert_text((470, footer_y), line, fontsize=7, fontname="china-s")
        footer_y = (footer_y or 0) + 14
    data = doc.tobytes()
    doc.close()
    return data


def test_signed_amount_column_fills_direction():
    rows = [
        ["2026-08-30", "CNY", "1,850.00", "1,850.00", "网联收款", "某公司"],
        ["2026-08-31", "CNY", "-100.00", "1,750.00", "快捷支付", "某商户"],
        ["2026-09-01", "CNY", "1.00", "1,751.00", "账户结息", "某银行"],
    ]
    result = parse(make_cmb_like_pdf(rows))

    assert [txn.direction for txn in result.transactions] == ["in", "out", "in"]
    assert result.transactions[0].amount == Decimal("1850.00")
    assert result.transactions[1].amount == Decimal("100.00")
    assert any("正负号约定" in warning for warning in result.warnings)


def test_signed_amount_without_negative_stays_undetermined():
    rows = [
        ["2026-08-30", "CNY", "1,850.00", "1,850.00", "网联收款", "某公司"],
        ["2026-09-01", "CNY", "1.00", "1,851.00", "账户结息", "某银行"],
    ]
    result = parse(make_cmb_like_pdf(rows))

    assert [txn.direction for txn in result.transactions] == [None, None]
    assert not any("正负号约定" in warning for warning in result.warnings)


def test_blank_direction_column_prevents_sign_inference():
    header = ["交易日期", "摘要", "借贷标志", "交易金额", "余额"]
    xs = [40, 180, 340, 460, 560]
    rows = [
        ["2026-09-01", "收款", "", "1,000.00", "1,000.00"],
        ["2026-09-02", "消费", "", "-200.00", "800.00"],
    ]
    result = parse(make_pdf([rows], header, xs))

    assert [txn.direction for txn in result.transactions] == [None, "out"]
    assert not any("正负号约定" in warning for warning in result.warnings)


def test_far_footer_is_not_merged_into_last_row():
    rows = [
        ["2026-08-30", "CNY", "1,850.00", "1,850.00", "网联收款", "某公司"],
        ["2026-09-01", "CNY", "-500.00", "1,350.00", "快捷支付", "某商户"],
    ]
    pdf = make_cmb_like_pdf(rows, footer_y=900, footer_lines=["温馨提示：请核对明细", "1/2"])
    result = parse(pdf)

    last = result.transactions[-1]
    assert last.summary == "快捷支付"
    assert last.counterparty_name == "某商户"
    assert len(result.transactions) == 2


def test_image_block_before_text_keeps_fitz_words():
    doc = fitz.open()
    page = doc.new_page(width=800, height=1000)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 32, 32), False)
    pix.clear_with(240)
    page.insert_image(fitz.Rect(20, 20, 220, 60), pixmap=pix)
    page.insert_text((40, 90), "银行账户交易明细", fontsize=12, fontname="china-s")
    for index, label in enumerate(BANK_HEADER):
        page.insert_text((BANK_XS[index], 110), label, fontsize=7, fontname="china-s")
    for row_index, row in enumerate(BANK_ROWS, start=1):
        for index, value in enumerate(row):
            page.insert_text((BANK_XS[index], 110 + 18 * row_index), value, fontsize=7, fontname="china-s")
    data = doc.tobytes()
    doc.close()

    result = parse(data)

    assert len(result.transactions) == 3
    assert not any("回退 pdfplumber" in warning for warning in result.warnings)


ICBC_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "algorithm"
    / "integration"
    / "samples"
    / "icbc_template.json"
)


def test_icbc_template_maps_counterparty_not_channel():
    """模板曾把渠道指到 10（实际是对方户名），导致带模板时对手方整列为空。"""
    from algorithm.local_run import load_template

    header = [
        "交易日期", "账号", "储种", "序号", "币种", "钞汇", "摘要",
        "地区", "收入/支出金额", "余额", "对方户名", "对方账号", "渠道",
    ]
    xs = [40, 130, 200, 250, 300, 350, 400, 460, 520, 640, 720, 830, 900]
    row = [
        "2026-01-05", "12", "活期", "00000", "人民币", "钞", "消费",
        "4301", "-29.00", "210.59", "中移支付有限公司", "2353****0115", "快捷支付",
    ]
    data = make_pdf([[row]], header, xs)

    result = parse(data, load_template(ICBC_TEMPLATE))

    assert len(result.transactions) == 1
    txn = result.transactions[0]
    assert txn.counterparty_name == "中移支付有限公司"
    assert txn.amount == Decimal("29.00")
    assert txn.direction == "out"
    assert txn.balance == Decimal("210.59")
    assert txn.reference_no is None
