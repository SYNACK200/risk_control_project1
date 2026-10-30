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


def test_box_template_uses_header_fingerprint(tmp_path):
    path = tmp_path / "box.json"
    path.write_text(
        json.dumps(
            {
                "bank_code": "CMB",
                "schema_version": 1,
                "match_rule": {"header_fingerprint": ["记账日期", "交易金额"]},
                "tables": [
                    {
                        "columns": [
                            {"field": "txn_date", "x": 0.06, "w": 0.1},
                            {"field": "amount", "x": 0.26, "w": 0.13},
                        ]
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    template = load_template(path)
    assert template.version == 1
    assert template.field_map == {"txn_date": "记账日期", "amount": "交易金额"}


def test_box_template_without_fingerprint_falls_back_to_index(tmp_path):
    path = tmp_path / "box.json"
    path.write_text(
        json.dumps(
            {
                "bank_code": "CMB",
                "tables": [{"columns": [{"field": "txn_date"}, {"field": "balance"}]}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert load_template(path).field_map == {"txn_date": 0, "balance": 1}


def test_template_without_mapping_is_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"bank_code": "X"}), encoding="utf-8")
    with pytest.raises(ValueError, match="field_map"):
        load_template(path)
