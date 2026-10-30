import json
from algorithm.algo.metrics import METRIC_SET_VERSION
from datetime import date
from decimal import Decimal

import pytest

from algorithm.algo.hits import detect_hits
from algorithm.algo.metrics import compute_metrics
from algorithm.algo.models import ContentLayerResult, Evidence, LayerConclusion
from algorithm.algo.report import build_report
from algorithm.algo.thresholds import ThresholdConfig
from algorithm.algo.verdict import VerdictResult, conclude
from algorithm.ocr.models import Transaction


def _txn(
    day: str,
    summary: str,
    *,
    direction: str,
    amount: str,
    row: int,
) -> Transaction:
    return Transaction(
        page_no=1,
        row_no=row,
        txn_date=day,
        summary=summary,
        counterparty_name="甲公司" if direction == "in" else "信用卡中心",
        direction=direction,
        amount=Decimal(amount),
        balance=Decimal("100"),
        bbox=(100.0, 200.0, 300.0, 240.0),
    )


def _history() -> list[Transaction]:
    return [
        _txn("2026-01-05", "工资", direction="in", amount="10000", row=1),
        _txn("2026-01-10", "还款", direction="out", amount="12000", row=2),
        _txn("2026-02-05", "工资", direction="in", amount="10000", row=3),
    ]


def _layer(name: str) -> LayerConclusion:
    return LayerConclusion(layer=name, status="pass", detail="ok")


def _verdict(carrier: str = "electronic", evidence: list[Evidence] | None = None):
    result = conclude(
        ContentLayerResult(status="pass"),
        carrier=carrier,
        file_layer=_layer("file"),
        ledger=_layer("ledger"),
        external=_layer("external"),
    )
    if evidence is not None:
        result.evidence = evidence
    return result


def _report(**kwargs):
    txns = kwargs.pop("transactions", _history())
    metrics = kwargs.pop("metrics", None)
    hits = kwargs.pop("hits", None)
    if metrics is None:
        metrics = compute_metrics(txns, hits=hits)
    defaults = dict(
        carrier="electronic",
        hits=hits,
        transactions=txns,
        txn_ids=list(range(11, 11 + len(txns))),
    )
    defaults.update(kwargs)
    return build_report(_verdict(), metrics, **defaults)


def test_report_matches_contract_shape():
    report = _report()
    data = json.loads(report.model_dump_json())
    assert list(data) == [
        "carrier",
        "verdict",
        "verdict_reason",
        "limitations",
        "layers",
        "metrics",
        "metric_set_version",
        "threshold_version",
        "conclusions",
        "trend",
        "evidence",
        "materials",
        "self_check",
        "version",
    ]
    assert data["carrier"] == "electronic"
    assert data["verdict"] == "未发现异常"
    assert len(data["layers"]) == 4
    assert [layer["layer"] for layer in data["layers"]] == [
        "file",
        "content",
        "ledger",
        "external",
    ]
    assert len(data["metrics"]) == 40
    assert data["metric_set_version"] == METRIC_SET_VERSION
    assert data["threshold_version"] == 2
    assert data["version"] == 1


def test_materials_passed_through_from_task_file():
    from algorithm.algo.report import ReportMaterial

    report = _report(materials=[
        ReportMaterial(file_id=7, role="original", pages=2, sha256="a" * 64),
        ReportMaterial(file_id=9, role="supplement", pages=1, sha256="b" * 64),
    ])
    data = json.loads(report.model_dump_json())
    assert [m["role"] for m in data["materials"]] == ["original", "supplement"]
    assert [m["file_id"] for m in data["materials"]] == [7, 9]
    assert data["materials"][1]["pages"] == 1
    assert not any("材料清单未提供" in item for item in data["limitations"])


def test_materials_empty_is_declared_in_limitations():
    report = _report()
    data = json.loads(report.model_dump_json())
    assert data["materials"] == []
    assert any("材料清单未提供" in item for item in data["limitations"])


def test_trend_uses_excluded_income_and_raw_expense():
    refund = _txn("2026-01-20", "退款", direction="in", amount="500", row=4)
    txns = _history() + [refund]
    metrics = compute_metrics(txns)
    report = build_report(_verdict(), metrics, carrier="electronic")
    assert report.trend[0].month == "2026-01"
    assert report.trend[0].income == Decimal("10000.00")
    assert report.trend[0].expense == Decimal("12000.00")
    assert report.trend[1].income == Decimal("10000.00")
    assert report.trend[1].expense == Decimal("0.00")


def test_default_threshold_conclusions():
    report = _report()
    codes = [item.code for item in report.conclusions]
    assert "DTI_HIGH" in codes
    assert "LOW_BALANCE" in codes
    dti = next(item for item in report.conclusions if item.code == "DTI_HIGH")
    assert dti.level == "info"
    assert dti.threshold == "0.5"
    assert dti.value == "0.6"
    lowest = next(item for item in report.conclusions if item.code == "LOW_BALANCE")
    from algorithm.algo.metrics import compute_metrics

    expected = compute_metrics(_history()).by_code("B01").value
    assert Decimal(lowest.threshold) == expected
    assert lowest.value == "100"
    assert any("B01 月还款近似月供" in note for note in report.limitations)


def test_custom_threshold_version_and_value():
    thresholds = ThresholdConfig(version=2, dti_high=Decimal("0.7"))
    report = _report(thresholds=thresholds)
    assert report.threshold_version == 2
    assert all(item.code != "DTI_HIGH" for item in report.conclusions)


def test_gambling_threshold_uses_hits():
    txns = _history() + [
        _txn("2026-02-10", "彩票充值", direction="out", amount="50", row=4)
    ]
    hits = detect_hits(txns)
    report = _report(transactions=txns, hits=hits)
    gambling = next(item for item in report.conclusions if item.code == "GAMBLING_HIT")
    assert gambling.value == "1"
    assert gambling.threshold == "1"


def test_missing_hits_adds_limitation():
    report = _report()
    assert any("未判定涉赌阈值" in note for note in report.limitations)


def test_evidence_maps_txn_id_and_dedupes():
    evidence = [
        Evidence(rule_code="C1", page_no=1, x=10.0, y=20.0, row_no=2),
        Evidence(rule_code="C1", page_no=1, x=10.0, y=20.0, row_no=2),
        Evidence(rule_code="F1", page_no=1, x=1.0, y=2.0, row_no=99),
    ]
    report = build_report(
        _verdict(evidence=evidence),
        compute_metrics(_history()),
        carrier="electronic",
        transactions=_history(),
        txn_ids=[11, 22, 33],
    )
    assert len([item for item in report.evidence if item.rule_code in ("C1", "F1")]) == 2
    c1 = next(item for item in report.evidence if item.rule_code == "C1")
    f1 = next(item for item in report.evidence if item.rule_code == "F1")
    assert c1.txn_id == 22
    assert f1.txn_id is None
    assert any("交易号未落库" in item for item in report.limitations)


def test_threshold_conclusions_carry_row_evidence():
    report = _report()
    codes = {item.code for item in report.conclusions}
    assert {"DTI_HIGH", "LOW_BALANCE"} <= codes
    evidence = [item for item in report.evidence if item.rule_code in codes]
    assert evidence
    for item in evidence:
        assert item.page_no == 1
        assert (item.x, item.y) == (200.0, 220.0)
        assert item.txn_id is not None


def test_conclusion_evidence_capped_per_code():
    day = "2026-01-05"
    txns = [
        _txn(day, "消费", direction="out", amount="1", row=index)
        for index in range(1, 31)
    ]
    report = _report(transactions=txns, thresholds=ThresholdConfig(counterparty_hhi=Decimal("0.5")))
    assert any(item.code == "COUNTERPARTY_CONCENTRATED" for item in report.conclusions)
    picked = [item for item in report.evidence if item.rule_code == "COUNTERPARTY_CONCENTRATED"]
    assert len(picked) == 20


def test_missing_counterparty_column_declared_in_limitations():
    txns = [
        _txn("2026-01-05", "消费", direction="out", amount="10", row=index).model_copy(
            update={"counterparty_name": ""}
        )
        for index in range(1, 4)
    ]
    report = _report(transactions=txns)
    assert any("明细无对手方名称" in item and "E01/E02" in item for item in report.limitations)


def test_missing_balance_column_declared_in_limitations():
    txns = [
        _txn("2026-01-05", "消费", direction="out", amount="10", row=index).model_copy(
            update={"balance": None}
        )
        for index in range(1, 4)
    ]
    report = _report(transactions=txns)
    assert any("明细无余额" in item and "C03–C06" in item for item in report.limitations)


def test_evidence_without_coordinates_declared_in_limitations():
    evidence = [Evidence(rule_code="F1", page_no=1, x=0.0, y=0.0)]
    report = build_report(
        _verdict(evidence=evidence),
        compute_metrics(_history()),
        carrier="electronic",
        transactions=_history(),
        txn_ids=[11, 22, 33],
    )
    assert any("无法跳转到页内位置" in item for item in report.limitations)


def test_screenshot_verdict_and_limitation_passthrough():
    report = build_report(
        _verdict(carrier="screenshot"),
        compute_metrics(_history()),
        carrier="screenshot",
    )
    assert report.verdict == "来源可疑"
    assert any("截图件" in item for item in report.limitations)


def test_invalid_report_version():
    with pytest.raises(ValueError):
        _report(version=0)


def test_txn_ids_length_must_match():
    with pytest.raises(ValueError):
        build_report(
            _verdict(),
            compute_metrics(_history()),
            carrier="electronic",
            transactions=_history(),
            txn_ids=[1],
        )


def test_period_and_monthly_flow_present():
    metrics = compute_metrics(_history())
    assert metrics.period_start == date(2026, 1, 5)
    assert metrics.period_end == date(2026, 2, 5)
    assert len(metrics.trend) == 2


def test_net_outflow_two_consecutive_months():
    txns = [
        _txn("2026-01-05", "工资", direction="in", amount="5000", row=1),
        _txn("2026-01-10", "消费", direction="out", amount="6000", row=2),
        _txn("2026-02-05", "工资", direction="in", amount="5000", row=3),
        _txn("2026-02-10", "消费", direction="out", amount="7000", row=4),
        _txn("2026-03-05", "工资", direction="in", amount="5000", row=5),
        _txn("2026-03-10", "消费", direction="out", amount="1000", row=6),
    ]
    report = _report(transactions=txns)
    item = next(i for i in report.conclusions if i.code == "NET_OUTFLOW")
    assert item.value == "2 个月"
    assert "连续 2 个月" in item.threshold


def test_net_outflow_ratio_branch():
    txns = [
        _txn("2026-01-05", "工资", direction="in", amount="1000", row=1),
        _txn("2026-01-10", "消费", direction="out", amount="1400", row=2),
    ]
    report = _report(transactions=txns)
    item = next(i for i in report.conclusions if i.code == "NET_OUTFLOW")
    assert item.threshold == "0.3"
    assert item.value == "0.4"


def test_net_outflow_month_floor_blocks_small_months():
    txns = [
        _txn("2026-01-05", "工资", direction="in", amount="1000", row=1),
        _txn("2026-01-10", "消费", direction="out", amount="1050", row=2),
        _txn("2026-02-05", "工资", direction="in", amount="1000", row=3),
        _txn("2026-02-10", "消费", direction="out", amount="1050", row=4),
    ]
    report = _report(transactions=txns)
    assert all(i.code != "NET_OUTFLOW" for i in report.conclusions)


def test_balance_decline_triggers():
    txns = []
    row = 1
    for month, balance in ((1, 1000), (2, 1000), (3, 1000), (4, 80), (5, 80), (6, 80)):
        txns.append(
            _txn(f"2026-{month:02d}-05", "工资", direction="in", amount="1000", row=row)
            .model_copy(update={"balance": Decimal(balance)})
        )
        row += 1
        txns.append(
            _txn(f"2026-{month:02d}-10", "还款", direction="out", amount="100", row=row)
            .model_copy(update={"balance": Decimal(balance)})
        )
        row += 1
    report = _report(transactions=txns)
    item = next(i for i in report.conclusions if i.code == "BALANCE_DECLINE")
    assert "期末" in item.value
    assert "月均余额降 10%" in item.threshold


def test_balance_decline_needs_six_months():
    report = _report(transactions=_history())
    assert all(i.code != "BALANCE_DECLINE" for i in report.conclusions)
    assert any("未判定月均余额下降" in n for n in report.limitations)


def test_fast_in_out_triggers():
    txns = []
    row = 1
    for day in ("2026-03-01", "2026-03-02", "2026-03-03"):
        txns += [
            _txn(day, "转账", direction="in", amount="600", row=row),
            _txn(day, "消费", direction="out", amount="600", row=row + 1),
            _txn(day, "转账", direction="in", amount="5", row=row + 2),
            _txn(day, "消费", direction="out", amount="5", row=row + 3),
        ]
        row += 4
    report = _report(transactions=txns)
    item = next(i for i in report.conclusions if i.code == "FAST_IN_OUT")
    assert item.value == "1"


def test_fast_in_out_min_amount_blocks():
    txns = []
    row = 1
    for day in ("2026-03-01", "2026-03-02", "2026-03-03"):
        txns += [
            _txn(day, "转账", direction="in", amount="50", row=row),
            _txn(day, "消费", direction="out", amount="50", row=row + 1),
        ]
        row += 2
    report = _report(transactions=txns)
    assert all(i.code != "FAST_IN_OUT" for i in report.conclusions)


def test_counterparty_gating_and_missing_alert():
    txns = [
        Transaction(
            page_no=1,
            row_no=index,
            txn_date="2026-01-05",
            summary="消费",
            counterparty_name="",
            direction="out",
            amount=Decimal("10"),
            balance=Decimal("100"),
            bbox=(1.0, 2.0, 3.0, 4.0),
        )
        for index in range(30)
    ]
    report = _report(transactions=txns)
    assert all(i.code != "COUNTERPARTY_CONCENTRATED" for i in report.conclusions)
    assert any("对手方缺失率 100%" in n for n in report.limitations)
    assert any("有效对手方笔数 0 < 20" in n for n in report.limitations)


def test_counterparty_hhi_uncalibrated_skips():
    txns = [
        _txn("2026-01-05", "消费", direction="out", amount="10", row=index)
        .model_copy(update={"counterparty_name": f"对手{index}"})
        for index in range(25)
    ]
    report = _report(transactions=txns)
    assert all(i.code != "COUNTERPARTY_CONCENTRATED" for i in report.conclusions)
    assert any("HHI 阈值未校准" in n for n in report.limitations)


def test_counterparty_hhi_triggers_with_calibrated_threshold():
    txns = [
        _txn("2026-01-05", "消费", direction="out", amount="10", row=index)
        .model_copy(update={"counterparty_name": "甲公司"})
        for index in range(25)
    ]
    report = _report(
        transactions=txns, thresholds=ThresholdConfig(counterparty_hhi=Decimal("0.5"))
    )
    item = next(i for i in report.conclusions if i.code == "COUNTERPARTY_CONCENTRATED")
    assert item.threshold == "0.5"
    assert item.value == "1"


def test_new_loan_amount_condition():
    txns = [
        _txn("2026-01-05", "工资", direction="in", amount="1000", row=1),
        _txn("2026-01-10", "贷款发放", direction="in", amount="400", row=2),
    ]
    report = _report(transactions=txns)
    item = next(i for i in report.conclusions if i.code == "NEW_LOAN")
    assert item.value == "1 笔 400 元"


def test_new_loan_below_amount_only_notes():
    txns = [
        _txn("2026-01-05", "工资", direction="in", amount="1000", row=1),
        _txn("2026-01-10", "贷款发放", direction="in", amount="200", row=2),
    ]
    report = _report(transactions=txns)
    assert all(i.code != "NEW_LOAN" for i in report.conclusions)
    assert any("仅记录不提示" in n for n in report.limitations)


def test_small_loan_repay_monthly_frequency():
    txns = [
        _txn("2026-01-05", "工资", direction="in", amount="1000", row=1),
        _txn("2026-01-10", "借呗", direction="out", amount="100", row=2),
        _txn("2026-02-05", "工资", direction="in", amount="1000", row=3),
        _txn("2026-02-10", "借呗", direction="out", amount="100", row=4),
    ]
    report = _report(transactions=txns)
    item = next(i for i in report.conclusions if i.code == "SMALL_LOAN_REPAY")
    assert item.value == "2 笔"
    assert "月均≥1 笔" in item.threshold


def test_crypto_hit_amount_condition():
    txns = [
        _txn("2026-01-05", "工资", direction="in", amount="1000", row=1),
        _txn("2026-01-10", "USDT", direction="out", amount="2000", row=2),
    ]
    report = _report(transactions=txns)
    item = next(i for i in report.conclusions if i.code == "CRYPTO_HIT")
    assert item.value == "1 笔 2000 元"


def test_crypto_below_amount_only_notes():
    txns = [
        _txn("2026-01-05", "工资", direction="in", amount="1000", row=1),
        _txn("2026-01-10", "USDT", direction="out", amount="50", row=2),
    ]
    report = _report(transactions=txns)
    assert all(i.code != "CRYPTO_HIT" for i in report.conclusions)
    assert any("涉币交易金额 50 元" in n for n in report.limitations)


def test_net_outflow_does_not_bridge_missing_month():
    txns = [
        _txn("2026-01-05", "工资", direction="in", amount="5000", row=1),
        _txn("2026-01-10", "消费", direction="out", amount="6000", row=2),
        _txn("2026-03-05", "工资", direction="in", amount="5000", row=3),
        _txn("2026-03-10", "消费", direction="out", amount="6000", row=4),
    ]
    report = _report(transactions=txns)
    assert all(i.code != "NET_OUTFLOW" for i in report.conclusions)


def test_balance_decline_uses_latest_date_balance():
    txns = []
    row = 1
    for month in (1, 2, 3):
        txns += [
            _txn(f"2026-{month:02d}-05", "工资", direction="in", amount="1000", row=row).model_copy(
                update={"balance": Decimal("1000")}
            ),
            _txn(f"2026-{month:02d}-25", "消费", direction="out", amount="10", row=row + 1).model_copy(
                update={"balance": Decimal("1000")}
            ),
        ]
        row += 2
    for month in (4, 5):
        txns += [
            _txn(f"2026-{month:02d}-05", "消费", direction="out", amount="10", row=row).model_copy(
                update={"balance": Decimal("50")}
            ),
            _txn(f"2026-{month:02d}-25", "工资", direction="in", amount="1000", row=row + 1).model_copy(
                update={"balance": Decimal("200")}
            ),
        ]
        row += 2
    txns += [
        _txn("2026-06-25", "工资", direction="in", amount="1000", row=row).model_copy(
            update={"balance": Decimal("200")}
        ),
        _txn("2026-06-05", "消费", direction="out", amount="10", row=row + 1).model_copy(
            update={"balance": Decimal("50")}
        ),
    ]
    report = _report(transactions=txns, monthly_payment=Decimal("100"))
    assert all(i.code != "BALANCE_DECLINE" for i in report.conclusions)


def test_crypto_hit_uses_labels_for_counterparty_only():
    txns = [
        _txn("2026-01-05", "工资", direction="in", amount="5000", row=1),
        _txn("2026-01-10", "转账", direction="out", amount="2000", row=2).model_copy(
            update={"counterparty_name": "某虚拟币交易所"}
        ),
    ]
    hits = detect_hits(txns)
    report = _report(transactions=txns, hits=hits)
    item = next(i for i in report.conclusions if i.code == "CRYPTO_HIT")
    assert item.value == "1 笔 2000 元"


def test_counterparty_mask_names_alert():
    txns = [
        Transaction(
            page_no=1,
            row_no=index,
            txn_date="2026-01-05",
            summary="消费",
            counterparty_name="***",
            direction="out",
            amount=Decimal("10"),
            balance=Decimal("100"),
            bbox=(1.0, 2.0, 3.0, 4.0),
        )
        for index in range(25)
    ]
    report = _report(
        transactions=txns, thresholds=ThresholdConfig(counterparty_hhi=Decimal("0.5"))
    )
    assert any("掩码名称" in n for n in report.limitations)


def _self_check(*items):
    from algorithm.algo.self_check import SelfCheckItem, SelfCheckResult

    parsed = [
        SelfCheckItem(code=code, name=name, status=status, detail=detail, ratio=ratio)
        for code, name, status, detail, ratio in items
    ]
    status = "pass" if all(i.status == "pass" for i in parsed) else "limited"
    return SelfCheckResult(status=status, items=parsed)


def test_self_check_passed_through_to_report():
    report = _report(
        self_check=_self_check(
            ("S1", "金额回查", "pass", "102/102 笔金额能在原文定位", 1.0),
            ("S5", "行数守恒", "pass", "声明 102 笔 vs 解析 102 笔", None),
        )
    )
    data = json.loads(report.model_dump_json())
    assert data["self_check"]["status"] == "pass"
    assert [item["code"] for item in data["self_check"]["items"]] == ["S1", "S5"]
    assert data["self_check"]["summary"] == "全部通过"
    assert not any("识别自检" in n for n in data["limitations"])


def test_missing_self_check_declared_in_limitations():
    data = json.loads(_report().model_dump_json())
    assert data["self_check"] is None
    assert any("未执行识别自检" in n for n in data["limitations"])


def test_self_check_failure_declared_in_limitations():
    data = json.loads(
        _report(
            self_check=_self_check(
                ("S1", "金额回查", "pass", "102/102 笔金额能在原文定位", 1.0),
                ("S4", "跨引擎一致", "limited", "94/102 笔金额在两个引擎文本中均可定位", 0.92),
            )
        ).model_dump_json()
    )
    assert data["self_check"]["status"] == "limited"
    assert data["self_check"]["summary"] == "未通过：跨引擎一致"
    assert "识别自检 S4 跨引擎一致：94/102 笔金额在两个引擎文本中均可定位" in data["limitations"]
