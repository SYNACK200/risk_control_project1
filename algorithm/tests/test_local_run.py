import json

import pytest

from algorithm.local_run import load_template


def test_loads_legacy_field_map(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            {"bank_code": "ICBC", "version": 3, "field_map": {"amount": 8}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    template = load_template(path)
    assert template.bank_code == "ICBC"
    assert template.version == 3
    assert template.field_map == {"amount": 8}


def _box_export(**extra):
    data = {
        "bank_code": "CMB",
        "schema_version": 1,
        "match_rule": {"header_fingerprint": ["记账日期", "摘要", "交易金额", "联机余额"]},
        "meta_boxes": [
            {"field": "account_no", "page": 1, "rect": {"x": 0.05, "y": 0.04, "w": 0.2, "h": 0.02}},
            {"field": "period", "page": 1, "rect": {"x": 0.05, "y": 0.07, "w": 0.3, "h": 0.02}},
        ],
        "tables": [
            {
                "page": 1,
                "columns": [
                    {"field": "txn_date", "x": 0.05, "w": 0.1},
                    {"field": "summary", "x": 0.3, "w": 0.2},
                    {"field": "amount", "x": 0.55, "w": 0.15},
                    {"field": "balance", "x": 0.75, "w": 0.2},
                ],
            }
        ],
    }
    data.update(extra)
    return data


def test_box_template_uses_header_fingerprint(tmp_path):
    path = tmp_path / "box.json"
    path.write_text(json.dumps(_box_export(), ensure_ascii=False), encoding="utf-8")

    template = load_template(path)

    assert template.version == 1
    assert template.field_map == {
        "txn_date": "记账日期",
        "summary": "摘要",
        "amount": "交易金额",
        "balance": "联机余额",
    }
    assert {box.field for box in template.meta_boxes} == {"account_no", "period"}


def test_box_template_without_fingerprint_is_rejected(tmp_path):
    export = _box_export()
    export["match_rule"]["header_fingerprint"] = []
    path = tmp_path / "box.json"
    path.write_text(json.dumps(export, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="T009"):
        load_template(path)


def test_template_without_mapping_is_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"bank_code": "X"}), encoding="utf-8")
    with pytest.raises(ValueError, match="field_map"):
        load_template(path)


def test_summary_limitations_only_truncates_with_count():
    from algorithm.local_run import summary_limitations

    short = [f"项{i}" for i in range(3)]
    assert summary_limitations(short) == short

    shown = summary_limitations([f"项{i}" for i in range(25)])
    assert len(shown) == 11
    assert shown[0] == "项0" and shown[9] == "项9"
    assert "其余 15 条" in shown[-1] and "共 25 条" in shown[-1]
