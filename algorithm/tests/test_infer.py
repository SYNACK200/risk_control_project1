import fitz

from algorithm.ocr.infer import Mark, infer_template

HEADER = ["交易日期", "摘要", "对方户名", "借贷标志", "交易金额", "余额"]
XS = [40, 200, 380, 480, 560, 660]
ROWS = [
    ["2026-01-05", "工资", "某公司", "贷", "12,500.00", "13,500.00"],
    ["2026-01-06", "消费", "某超市", "借", "300.50", "13,199.50"],
    ["2026-01-07", "转账", "张三", "借", "1,000.00", "12,199.50"],
    ["2026-01-08", "退款", "某店", "贷", "50.00", "12,249.50"],
    ["2026-01-09", "消费", "某餐厅", "借", "88.00", "12,161.50"],
]


def make_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=800, height=1000)
    page.insert_text((40, 60), "银行账户交易明细", fontsize=12, fontname="china-s")
    y = 90
    for label, x in zip(HEADER, XS):
        page.insert_text((x, y), label, fontsize=7, fontname="china-s")
    last_y = y
    for row_index, row in enumerate(ROWS, start=1):
        last_y = y + 18 * row_index
        for value, x in zip(row, XS):
            page.insert_text((x, last_y), value, fontsize=7, fontname="china-s")
    page.insert_text((40, last_y + 24), f"共 {len(ROWS)} 笔记录", fontsize=7, fontname="china-s")
    data = doc.tobytes()
    doc.close()
    return data


def marks(date_x: float, amount_x: float, balance_x: float) -> list[Mark]:
    return [
        Mark(field="txn_date", page=0, x=date_x, y=108),
        Mark(field="amount", page=0, x=amount_x, y=108),
        Mark(field="balance", page=0, x=balance_x, y=108),
    ]


def test_correct_marks_produce_template():
    result = infer_template(make_pdf(), marks(40, 560, 660))

    assert result.valid is True
    assert result.template is not None
    assert {"txn_date", "amount", "balance"} <= set(result.template.field_map)
    assert result.warnings == []


def test_swapped_amount_and_balance_marks_are_rejected():
    result = infer_template(make_pdf(), marks(40, 660, 560))

    assert result.valid is False
    assert result.template is None
    assert any("余额链" in item for item in result.warnings)
    assert any("未生成模板" in item for item in result.warnings)


def test_amount_mark_on_text_column_is_rejected():
    result = infer_template(make_pdf(), marks(40, 200, 660))

    assert result.valid is False
    assert result.template is None
    assert any("金额列映射可疑" in item for item in result.warnings)


def make_pdf_without_balance() -> bytes:
    header = ["交易日期", "摘要", "借贷标志", "交易金额"]
    xs = [40, 200, 380, 560]
    rows = [
        ["2026-02-01", "消费", "借", "12.00"],
        ["2026-02-02", "消费", "借", "8.00"],
    ]
    doc = fitz.open()
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
    page.insert_text((40, last_y + 24), "共 2 笔记录", fontsize=7, fontname="china-s")
    data = doc.tobytes()
    doc.close()
    return data


def test_missing_required_field_is_rejected():
    only_date = [Mark(field="txn_date", page=0, x=40, y=108)]

    result = infer_template(make_pdf_without_balance(), only_date)

    assert result.valid is False
    assert result.template is None
    assert any("必需字段" in item for item in result.warnings)
