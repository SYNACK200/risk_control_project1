from __future__ import annotations

from services.summary import _auth


def layers(**statuses):
    # 每个核心层给一条通过项，模拟「有逐项结果但没有阻断项」
    return [
        {"layer": name, "status": status,
         "checks": [{"code": "C1", "status": "pass"}] if name in ("file", "content", "ledger") else []}
        for name, status in statuses.items()
    ]


def with_checks(statuses: dict, checks: list[dict]):
    return [{"layer": name, "status": status, "checks": checks if name == "content" else []}
            for name, status in statuses.items()]


def test_all_pass_is_pass():
    result = _auth(layers(file="pass", content="pass", ledger="pass", external="pass"), "electronic")
    assert result["level"] == "pass"
    assert result["label"] == "合格"


def test_core_pass_external_unavailable_is_grant():
    result = _auth(layers(file="pass", content="pass", ledger="pass", external="unavailable"), "electronic")
    assert result["level"] == "grant"
    assert result["label"] == "可授信"


def test_core_limited_without_blocking_materials_is_grant():
    result = _auth(layers(file="limited", content="limited", ledger="limited", external="unavailable"), "electronic")
    assert result["level"] == "grant"
    assert result["missing_materials"] == []


def test_missing_page_total_is_supplement():
    checks = [{"code": "C2", "status": "skipped"}, {"code": "C3", "status": "skipped"}]
    result = _auth(with_checks({"file": "limited", "content": "limited",
                              "ledger": "limited", "external": "unavailable"}, checks), "electronic")
    assert result["level"] == "supplement"
    assert result["label"] == "需补充"
    assert set(result["missing_materials"]) == {"C2", "C3"}


def test_no_layers_is_unknown():
    assert _auth([], "electronic")["level"] == "unknown"


def test_no_checks_is_supplement():
    # 旧报告没有逐项结果，应提示补充/重算，而不是可授信
    bare = [{"layer": name, "status": "limited", "checks": []}
            for name in ("file", "content", "ledger", "external")]
    assert _auth(bare, "electronic")["level"] == "supplement"


def test_core_flagged_check_is_supplement():
    base = layers(file="limited", content="limited", ledger="limited", external="unavailable")
    for layer in base:
        if layer["layer"] == "file":
            layer["checks"] = [{"code": "F5", "status": "fail"}]
    assert _auth(base, "electronic")["level"] == "supplement"


def test_unverified_core_layer_is_supplement():
    base = layers(file="limited", content="limited", ledger="limited", external="unavailable")
    for layer in base:
        if layer["layer"] == "content":
            layer["checks"] = []
    assert _auth(base, "electronic")["level"] == "supplement"


def test_inconsistent_is_fail():
    result = _auth(layers(file="pass", content="inconsistent", ledger="pass", external="pass"), "electronic")
    assert result["level"] == "fail"


def test_screenshot_and_image():
    assert _auth(layers(file="pass", content="pass", ledger="pass"), "screenshot")["level"] == "fail"
    assert _auth(layers(file="pass", content="pass", ledger="pass"), "image")["level"] == "unknown"
