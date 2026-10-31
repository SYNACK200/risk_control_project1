import copy
import json
from decimal import Decimal

import fitz
import pytest

from algorithm.ocr import convert_annotation, parse

HEADER = ["记账日期", "货币", "交易金额", "联机余额", "交易摘要", "对手信息"]
XS = [40, 200, 360, 480, 600, 720]
ROWS = [
    ["2026-01-05", "人民币", "12,500.00", "13,200.00", "工资", "某公司"],
    ["2026-01-06", "人民币", "300.50", "12,899.50", "消费", "某超市"],
    ["2026-01-07", "人民币", "1,000.00", "11,899.50", "转账", "张三"],
]
COLUMNS = [
    ("txn_date", 0.005),
    ("currency", 0.19625),
    ("amount", 0.405),
    ("balance", 0.555),
    ("summary", 0.705),
    ("counterparty", 0.855),
]


def _page(doc: fitz.Document, header: bool = True, rows=ROWS) -> None:
    page = doc.new_page(width=800, height=1000)
    page.insert_text((40, 40), "6222 **** 1234", fontsize=7, fontname="china-s")
    page.insert_text((400, 40), "张三", fontsize=7, fontname="china-s")
    page.insert_text((40, 62), "2026-01-01 至 2026-12-31", fontsize=7, fontname="china-s")
    if header:
        for label, x in zip(HEADER, XS):
            page.insert_text((x, 90), label, fontsize=7, fontname="china-s")
    for index, row in enumerate(rows, start=1):
        for value, x in zip(row, XS):
            page.insert_text((x, 90 + 18 * index), value, fontsize=7, fontname="china-s")


def make_pdf(pages: int = 1) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        _page(doc)
    data = doc.tobytes()
    doc.close()
    return data


def box_export() -> dict:
    return {
        "schema_version": 1,
        "bank_code": "CMB",
        "page_size": {"w": 800, "h": 1000},
        "match_rule": {"bank_name_keywords": ["招商银行"], "header_fingerprint": list(HEADER)},
        "meta_boxes": [
            {"id": "m1", "field": "account_no", "page": 1, "rect": {"x": 0.0375, "y": 0.028, "w": 0.25, "h": 0.02}},
            {"id": "m2", "field": "account_name", "page": 1, "rect": {"x": 0.4875, "y": 0.028, "w": 0.1, "h": 0.02}},
            {"id": "m3", "field": "period", "page": 1, "rect": {"x": 0.0375, "y": 0.052, "w": 0.25, "h": 0.02}},
        ],
        "tables": [
            {
                "id": "t1",
                "page": 1,
                "area": {"x": 0.0, "y": 0.08, "w": 0.99, "h": 0.5},
                "header_y": 0.09,
                "columns": [
                    {"field": field, "x": x, "w": 0.125} for field, x in COLUMNS
                ],
            }
        ],
        "custom_fields": [],
        "meta": {},
    }


def test_full_export_converts_and_parses():
    pdf = make_pdf()
    result = convert_annotation(box_export(), pdf)

    assert result.ok
    assert result.errors == []
    assert result.template.field_map == {
        "txn_date": "记账日期",
        "currency": "货币",
        "amount": "交易金额",
        "balance": "联机余额",
        "summary": "交易摘要",
        "counterparty": "对手信息",
    }
    assert result.template.page_size == (800.0, 1000.0)

    parsed = parse(pdf, result.template)
    assert len(parsed.transactions) == 3
    assert [txn.amount for txn in parsed.transactions] == [
        Decimal("12500.00"),
        Decimal("300.50"),
        Decimal("1000.00"),
    ]
    assert [txn.balance for txn in parsed.transactions] == [
        Decimal("13200.00"),
        Decimal("12899.50"),
        Decimal("11899.50"),
    ]
    assert [txn.summary for txn in parsed.transactions] == ["工资", "消费", "转账"]
    assert [txn.counterparty_name for txn in parsed.transactions] == ["某公司", "某超市", "张三"]


def test_parse_accepts_export_dict_directly():
    pdf = make_pdf()
    direct = parse(pdf, box_export())
    converted = parse(pdf, convert_annotation(box_export(), pdf).template)

    assert [txn.model_dump() for txn in direct.transactions] == [
        txn.model_dump() for txn in converted.transactions
    ]
    assert len(direct.transactions) == 3


def test_meta_boxes_fill_header_without_text_labels():
    """合成件页眉没有「账号/户名」标签，值只能从标注框取到。"""
    pdf = make_pdf()
    header = parse(pdf, box_export()).headers[0]

    assert header.account_no.value == "6222****1234"
    assert header.account_name.value == "张三"
    assert (header.period_start.value, header.period_end.value) == (
        "2026-01-01",
        "2026-12-31",
    )
    assert header.account_no.bbox is not None


def test_column_boxes_win_over_fingerprint_order():
    export = box_export()
    export["match_rule"]["header_fingerprint"] = list(reversed(HEADER))

    result = convert_annotation(export, make_pdf())

    assert result.ok
    assert result.template.field_map["txn_date"] == "记账日期"
    assert result.template.field_map["counterparty"] == "对手信息"
    assert len(parse(make_pdf(), result.template).transactions) == 3


def test_export_without_sample_uses_fingerprint_order():
    export = box_export()
    picked = [COLUMNS[index] for index in (0, 2, 3, 4)]
    export["tables"][0]["columns"] = [
        {"field": field, "x": x, "w": 0.125} for field, x in picked
    ]
    export["match_rule"]["header_fingerprint"] = ["记账日期", "交易金额", "联机余额", "交易摘要"]

    result = convert_annotation(export, None)

    assert result.ok
    assert result.template.field_map == {
        "txn_date": "记账日期",
        "amount": "交易金额",
        "balance": "联机余额",
        "summary": "交易摘要",
    }
    assert any("表头指纹顺序" in note for note in result.notes)


def test_legacy_field_map_passes_through():
    result = convert_annotation({"bank_code": "ICBC", "version": 2, "field_map": {"amount": 8}})

    assert result.ok
    assert result.template.field_map == {"amount": 8}
    assert result.template.version == 2


def _mutations():
    def drop_bank(export):
        export["bank_code"] = ""

    def drop_annotations(export):
        export["meta_boxes"] = []
        export["tables"] = []

    def drop_required(export):
        export["meta_boxes"] = [box for box in export["meta_boxes"] if box["field"] != "account_no"]

    def empty_columns(export):
        export["tables"][0]["columns"] = []

    def duplicate_column(export):
        export["tables"][0]["columns"][1]["field"] = "txn_date"

    def out_of_range(export):
        export["meta_boxes"][0]["rect"]["x"] = 0.95

    def bad_custom(export):
        export["custom_fields"] = [{"code": "Verify", "label": "验真码"}]

    def column_outside_area(export):
        export["tables"][0]["area"]["w"] = 0.5

    def empty_fingerprint(export):
        export["match_rule"]["header_fingerprint"] = []

    return {
        "T001": drop_bank,
        "T002": drop_annotations,
        "T003": drop_required,
        "T004": empty_columns,
        "T005": duplicate_column,
        "T006": out_of_range,
        "T007": bad_custom,
        "T008": column_outside_area,
        "T009": empty_fingerprint,
    }


@pytest.mark.parametrize("code,mutate", list(_mutations().items()))
def test_invalid_export_yields_no_template(code, mutate):
    export = copy.deepcopy(box_export())
    mutate(export)

    result = convert_annotation(export, make_pdf())

    assert result.template is None
    assert any(message.startswith(code) for message in result.errors)


def test_unmappable_columns_block_template():
    export = box_export()
    export["match_rule"]["header_fingerprint"] = HEADER[:2]

    result = convert_annotation(export, None)

    assert result.template is None
    assert any("T003" in message and "列未能定位表头" in message for message in result.errors)


def test_overlapping_columns_warn_but_do_not_block():
    export = box_export()
    export["tables"][0]["columns"][1]["x"] = 0.30

    result = convert_annotation(export, make_pdf())

    assert result.ok
    assert any(message.startswith("W002") for message in result.warnings)


def test_missing_page_size_warns_and_uses_sample_size():
    export = box_export()
    del export["page_size"]

    result = convert_annotation(export, make_pdf())

    assert result.ok
    assert result.template.page_size == (800.0, 1000.0)
    assert any(message.startswith("W004") for message in result.warnings)


def test_single_page_annotation_on_multi_page_sample_warns():
    result = convert_annotation(box_export(), make_pdf(pages=2))

    assert result.ok
    assert any(message.startswith("W005") for message in result.warnings)


def test_json_roundtrip_export_still_converts():
    export = json.loads(json.dumps(box_export(), ensure_ascii=False))

    assert convert_annotation(export, make_pdf()).ok
