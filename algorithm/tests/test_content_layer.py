from decimal import Decimal

from algorithm.algo import analyze_content
from algorithm.algo.models import CheckResult
from algorithm.ocr.models import HeaderField, PageHeader, PageSummary, ParseResult, Transaction


def txn(
    row_no: int,
    *,
    page_no: int = 1,
    direction: str = "in",
    amount: str | None = "100.00",
    balance: str | None = None,
    confidence: float = 1.0,
    txn_date: str | None = "2025-01-01",
    trade_time: str | None = None,
    reference_no: str | None = None,
    summary: str = "测试",
    counterparty: str | None = "某公司",
) -> Transaction:
    return Transaction(
        page_no=page_no,
        row_no=row_no,
        txn_date=txn_date,
        trade_time=trade_time,
        reference_no=reference_no,
        summary=summary,
        counterparty_name=counterparty,
        direction=direction,
        amount=None if amount is None else Decimal(amount),
        balance=None if balance is None else Decimal(balance),
        confidence=confidence,
        bbox=(10.0, float(row_no * 10), 100.0, float(row_no * 10 + 8)),
    )


def result(
    transactions: list[Transaction],
    *,
    summaries: list[PageSummary] | None = None,
    footer_count: int | None = None,
    page_count: int = 0,
    headers: list[PageHeader] | None = None,
) -> ParseResult:
    return ParseResult(
        transactions=transactions,
        page_summaries=summaries or [],
        footer_count=footer_count,
        page_count=page_count,
        headers=headers or [],
    )


def header(
    page_no: int,
    *,
    account: str | None = "6222021234567890",
    name: str | None = "张三",
    period: tuple[str, str] | None = ("2025-01-01", "2025-12-31"),
    account_confidence: float = 1.0,
) -> PageHeader:
    bbox = (20.0, 30.0, 300.0, 40.0)
    return PageHeader(
        page_no=page_no,
        account_no=(
            HeaderField(value=account, bbox=bbox, confidence=account_confidence)
            if account is not None
            else None
        ),
        account_name=HeaderField(value=name, bbox=bbox) if name is not None else None,
        period_start=HeaderField(value=period[0], bbox=bbox) if period else None,
        period_end=HeaderField(value=period[1], bbox=bbox) if period else None,
    )


def check(checks: list[CheckResult], code: str) -> CheckResult:
    return next(item for item in checks if item.code == code)


def test_clean_statement_passes_with_statistics_hint_only():
    txns = [
        txn(1, amount="100.00", balance="1100.00", trade_time="09:00:00", reference_no="1001"),
        txn(
            2,
            direction="out",
            amount="50.00",
            balance="1050.00",
            txn_date="2025-01-02",
            trade_time="10:00:00",
            reference_no="1002",
            summary="消费",
        ),
        txn(
            3,
            amount="200.00",
            balance="1250.00",
            txn_date="2025-01-03",
            trade_time="11:00:00",
            reference_no="1003",
            summary="转账",
        ),
    ]
    summaries = [
        PageSummary(
            page_no=1,
            printed_count=3,
            printed_in=Decimal("300.00"),
            printed_out=Decimal("50.00"),
        )
    ]
    out = analyze_content(
        result(
            txns,
            summaries=summaries,
            footer_count=3,
            page_count=2,
            headers=[header(1), header(2)],
        ),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1250.00"),
    )
    assert out.status == "pass"
    assert [item.code for item in out.checks] == [
        "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10",
    ]
    assert all(item.status == "pass" for item in out.checks if item.code != "C8")
    assert check(out.checks, "C8").status == "hint"
    assert out.limitations == ["提示（不影响结论）：C8 金额形态：" + check(out.checks, "C8").detail]


def test_balance_break_is_data_inconsistency_with_row_evidence():
    txns = [
        txn(1, amount="100.00", balance="1100.00"),
        txn(2, amount="100.00", balance="1300.00"),
    ]
    out = analyze_content(result(txns))
    c1 = check(out.checks, "C1")
    assert out.status == "inconsistent"
    assert c1.status == "fail"
    assert "1 处余额不连续" in c1.detail
    assert "+100.00" in c1.detail
    assert c1.attribution.cause == "data" and c1.attribution.action == "stop"
    assert [(e.page_no, e.row_no) for e in c1.evidence] == [(1, 2)]


def test_low_confidence_break_is_recognition_not_data():
    txns = [
        txn(1, amount="100.00", balance="1100.00"),
        txn(2, amount="100.00", balance="1300.00", confidence=0.55),
    ]
    out = analyze_content(result(txns))
    c1 = check(out.checks, "C1")
    assert c1.status == "fail"
    assert c1.attribution.cause == "recognition"
    assert c1.attribution.action == "manual"
    assert out.status == "undetermined"


def test_mixed_confidence_break_still_treated_as_data():
    txns = [
        txn(1, amount="100.00", balance="1100.00", confidence=0.55),
        txn(2, amount="100.00", balance="1300.00"),
    ]
    out = analyze_content(result(txns))
    c1 = check(out.checks, "C1")
    assert c1.attribution.cause == "data"
    assert out.status == "inconsistent"


def test_low_confidence_rows_are_skipped_not_failed():
    txns = [
        txn(1, amount="100.00", balance="1100.00"),
        txn(2, amount="100.00", balance="1200.00"),
        txn(3, amount="100.00", balance=None, confidence=0.5),
    ]
    out = analyze_content(result(txns))
    c1 = check(out.checks, "C1")
    assert c1.status == "skipped"
    assert c1.attribution.cause == "recognition"
    assert out.status == "limited"


def test_missing_balance_is_partial_not_fail():
    txns = [
        txn(1, amount="100.00", balance="1100.00"),
        txn(2, amount="100.00", balance="1200.00"),
        txn(3, amount="100.00", balance=None),
        txn(4, amount="100.00", balance="1400.00"),
    ]
    out = analyze_content(result(txns))
    c1 = check(out.checks, "C1")
    assert c1.status == "partial"
    assert "2 处字段缺失" in c1.detail
    assert out.status == "limited"


def test_page_total_mismatch_points_to_footer():
    txns = [
        txn(1, amount="100.00", balance="1100.00"),
        txn(2, amount="200.00", balance="1300.00"),
    ]
    summaries = [PageSummary(page_no=1, printed_count=2, printed_in=Decimal("999.00"), printed_out=Decimal("0.00"))]
    out = analyze_content(result(txns, summaries=summaries))
    c2 = check(out.checks, "C2")
    assert c2.status == "fail"
    assert "第 1 页合计不符" in c2.detail
    assert "收入 印 999.00 实 300.00" in c2.detail
    assert c2.attribution.cause == "data"
    assert out.status == "inconsistent"


def test_page_count_mismatch_fails():
    txns = [txn(1, amount="100.00", balance="1100.00")]
    summaries = [PageSummary(page_no=1, printed_count=3)]
    out = analyze_content(result(txns, summaries=summaries, footer_count=3))
    c3 = check(out.checks, "C3")
    assert c3.status == "fail"
    assert "第 1 页印 3 笔、解析 1 笔" in c3.detail
    assert c3.evidence[0].page_no == 1


def test_footer_total_count_mismatch_fails():
    txns = [txn(1, amount="100.00", balance="1100.00")]
    out = analyze_content(result(txns, footer_count=5))
    c3 = check(out.checks, "C3")
    assert c3.status == "fail"
    assert "页脚共 5 笔、解析 1 笔" in c3.detail


def test_opening_closing_skipped_when_absent():
    out = analyze_content(result([txn(1, amount="100.00", balance="1100.00")]))
    c4 = check(out.checks, "C4")
    assert c4.status == "skipped"
    assert "未标注期初/期末余额" in c4.detail
    assert out.status == "limited"


def test_opening_closing_closes():
    txns = [
        txn(1, amount="100.00", balance="1100.00"),
        txn(2, direction="out", amount="30.00", balance="1070.00"),
    ]
    out = analyze_content(
        result(txns),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1070.00"),
    )
    assert check(out.checks, "C4").status == "pass"


def test_opening_closing_mismatch_fails():
    txns = [txn(1, amount="100.00", balance="1100.00")]
    out = analyze_content(
        result(txns),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1200.00"),
    )
    c4 = check(out.checks, "C4")
    assert c4.status == "fail"
    assert "差 +100.00" in c4.detail


def test_page_headers_identical_pass():
    out = analyze_content(
        result(
            [txn(1, amount="100.00", balance="1100.00")],
            page_count=2,
            headers=[header(1), header(2)],
        )
    )
    c5 = check(out.checks, "C5")
    assert c5.status == "pass"
    assert "账号、户名、期间跨页一致" in c5.detail


def test_page_header_mismatch_fails_with_page_evidence():
    out = analyze_content(
        result(
            [txn(1, amount="100.00", balance="1100.00")],
            page_count=2,
            headers=[header(1, account="6222021234567890"), header(2, account="6222029999999999")],
        )
    )
    c5 = check(out.checks, "C5")
    assert c5.status == "fail"
    assert "页眉账号跨页不一致" in c5.detail
    assert c5.attribution.cause == "data" and c5.attribution.action == "stop"
    assert [(e.page_no, e.x, e.y) for e in c5.evidence] == [(1, 160.0, 35.0), (2, 160.0, 35.0)]
    assert out.status == "inconsistent"


def test_page_header_masked_positions_still_compare():
    out = analyze_content(
        result(
            [txn(1, amount="100.00", balance="1100.00")],
            page_count=2,
            headers=[header(1, account="5598****1234"), header(2, account="5598****5678")],
        )
    )
    c5 = check(out.checks, "C5")
    assert c5.status == "fail"
    assert "页眉账号跨页不一致" in c5.detail


def test_page_header_single_page_skipped():
    out = analyze_content(
        result([txn(1, amount="100.00", balance="1100.00")], page_count=1, headers=[header(1)])
    )
    c5 = check(out.checks, "C5")
    assert c5.status == "skipped"
    assert "单页无可比项" in c5.detail


def test_page_header_missing_on_one_page_skips_check():
    out = analyze_content(
        result(
            [txn(1, amount="100.00", balance="1100.00")],
            page_count=2,
            headers=[header(1), header(2, account=None, name=None, period=None)],
        )
    )
    c5 = check(out.checks, "C5")
    assert c5.status == "skipped"
    assert "第 2 页抬头未识别" in c5.detail
    assert out.status == "limited"


def test_page_header_all_masked_is_skipped_not_pass():
    masked = header(1, account="***", name="***", period=None)
    masked2 = header(2, account="***", name="***", period=None)
    out = analyze_content(
        result(
            [txn(1, amount="100.00", balance="1100.00")],
            page_count=2,
            headers=[masked, masked2],
        )
    )
    c5 = check(out.checks, "C5")
    assert c5.status == "skipped"
    assert "页眉字段均不可比" in c5.detail
    assert out.status == "limited"


def test_page_header_masked_name_is_partial_not_fail():
    out = analyze_content(
        result(
            [txn(1, amount="100.00", balance="1100.00")],
            page_count=2,
            headers=[header(1, name="***", period=None), header(2, name="***", period=None)],
        )
    )
    c5 = check(out.checks, "C5")
    assert c5.status == "partial"
    assert "已核对账号一致" in c5.detail
    assert "户名掩码不可比" in c5.detail
    assert out.status == "limited"


def test_page_header_low_confidence_field_is_not_failed():
    out = analyze_content(
        result(
            [txn(1, amount="100.00", balance="1100.00")],
            page_count=2,
            headers=[header(1), header(2, account="6222021234567890", account_confidence=0.5)],
        )
    )
    c5 = check(out.checks, "C5")
    assert c5.status == "partial"
    assert "账号第 2 页低置信" in c5.detail


def test_duplicate_group_hints_without_changing_status():
    txns = [
        txn(
            1, amount="100.00", balance="1100.00", trade_time="09:00:00",
            reference_no="1001", summary="工资", counterparty="甲公司",
        ),
        txn(
            2, direction="out", amount="50.00", balance="1050.00",
            txn_date="2025-01-02", trade_time="10:00:00", reference_no="1002",
            summary="消费", counterparty="超市",
        ),
        txn(
            3, amount="100.00", balance="1150.00", trade_time="11:00:00",
            reference_no="1003", summary="工资", counterparty="甲公司",
        ),
    ]
    summaries = [PageSummary(page_no=1, printed_count=3, printed_in=Decimal("200.00"), printed_out=Decimal("50.00"))]
    out = analyze_content(
        result(txns, summaries=summaries, footer_count=3, page_count=2, headers=[header(1), header(2)]),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1150.00"),
    )
    c10 = check(out.checks, "C10")
    assert c10.status == "hint"
    assert "1 组重复记录" in c10.detail
    assert "第 1 页第 1 行、第 1 页第 3 行" in c10.detail
    assert [(e.page_no, e.row_no) for e in c10.evidence] == [(1, 1), (1, 3)]
    assert c10.attribution is None
    assert out.status == "pass"
    assert any(item.startswith("提示（不影响结论）：C10 重复记录") for item in out.limitations)


def test_duplicate_hint_keeps_not_found_verdict():
    from algorithm.algo import conclude
    from algorithm.algo.verdict import LayerConclusion

    txns = [
        txn(
            1, amount="100.00", balance="1100.00", trade_time="09:00:00",
            reference_no="1001", summary="工资", counterparty="甲公司",
        ),
        txn(
            2, amount="100.00", balance="1200.00", trade_time="10:00:00",
            reference_no="1002", summary="工资", counterparty="甲公司",
        ),
        txn(
            3, direction="out", amount="30.00", balance="1170.00",
            txn_date="2025-01-02", trade_time="11:00:00", reference_no="1003",
            summary="消费", counterparty="超市",
        ),
    ]
    content = analyze_content(
        result(
            txns,
            page_count=2,
            headers=[header(1), header(2)],
            summaries=[
                PageSummary(
                    page_no=1,
                    printed_count=3,
                    printed_in=Decimal("200.00"),
                    printed_out=Decimal("30.00"),
                )
            ],
            footer_count=3,
        ),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1170.00"),
    )
    passing = lambda name: LayerConclusion(layer=name, status="pass", detail="通过")  # noqa: E731
    verdict = conclude(
        content,
        file_layer=passing("file"),
        ledger=passing("ledger"),
        external=passing("external"),
    )
    assert content.status == "pass"
    assert verdict.verdict == "未发现异常"
    assert verdict.verdict_reason == "内容层核对通过，未发现矛盾"
    assert any("提示（不影响结论）：C10" in item for item in verdict.limitations)


def test_duplicate_group_ignores_whitespace():
    txns = [
        txn(1, summary="工 资", counterparty="甲 公司"),
        txn(2, summary="工资", counterparty="甲公司"),
    ]
    c10 = check(analyze_content(result(txns)).checks, "C10")
    assert c10.status == "hint"
    assert "1 组重复记录" in c10.detail


def test_same_amount_but_different_date_is_not_duplicate():
    txns = [
        txn(1, txn_date="2025-01-01"),
        txn(2, txn_date="2025-01-02"),
    ]
    c10 = check(analyze_content(result(txns)).checks, "C10")
    assert c10.status == "pass"
    assert "无重复记录" in c10.detail


def test_same_amount_but_different_summary_or_direction_not_duplicate():
    txns = [
        txn(1, summary="工资"),
        txn(2, summary="转账"),
        txn(3, direction="out", summary="工资"),
    ]
    c10 = check(analyze_content(result(txns)).checks, "C10")
    assert c10.status == "pass"


def test_missing_counterparty_skips_duplicate_check():
    txns = [txn(1, counterparty=None), txn(2, counterparty=None)]
    c10 = check(analyze_content(result(txns)).checks, "C10")
    assert c10.status == "skipped"
    assert "对手方缺失 2 笔" in c10.detail


def test_pure_mask_counterparty_skips_duplicate_check():
    txns = [txn(1, counterparty="***"), txn(2, counterparty="***")]
    c10 = check(analyze_content(result(txns)).checks, "C10")
    assert c10.status == "skipped"
    assert "对手方为纯掩码 2 笔" in c10.detail


def test_partial_duplicate_coverage_is_partial():
    txns = [
        txn(1, summary="工资", counterparty="甲公司"),
        txn(2, summary="消费", counterparty="超市"),
        txn(3, summary="转账", counterparty=None),
    ]
    c10 = check(analyze_content(result(txns)).checks, "C10")
    assert c10.status == "partial"
    assert "已比对 2 笔，无重复记录" in c10.detail
    assert "另有 1 笔未参与比对" in c10.detail


def test_reference_same_number_on_two_rows_fails():
    txns = [
        txn(1, reference_no="A1001", amount="10.00"),
        txn(2, reference_no="A1001", amount="20.00"),
        txn(3, reference_no="A1002", amount="30.00"),
    ]
    out = analyze_content(result(txns))
    c6 = check(out.checks, "C6")
    assert c6.status == "fail"
    assert "参考号「A1001」出现在 2 笔完整明细" in c6.detail
    assert c6.attribution.cause == "data" and c6.attribution.action == "stop"
    assert [(e.page_no, e.row_no) for e in c6.evidence] == [(1, 1), (1, 2)]
    assert out.status == "inconsistent"


def test_reference_adjacent_duplicate_with_missing_field_is_continuation_hint():
    txns = [
        txn(1, reference_no="A1001"),
        txn(2, reference_no="A1001", amount=None),
        txn(3, reference_no="A1002"),
    ]
    c6 = check(analyze_content(result(txns)).checks, "C6")
    assert c6.status == "hint"
    assert "疑似续行未合并" in c6.detail
    assert c6.attribution is None


def test_reference_format_mismatch_is_hint():
    txns = [
        txn(1, reference_no="1001"),
        txn(2, reference_no="1002"),
        txn(3, reference_no="A1003"),
    ]
    c6 = check(analyze_content(result(txns)).checks, "C6")
    assert c6.status == "hint"
    assert "参考号格式不一致" in c6.detail


def test_reference_gap_is_hint():
    txns = [
        txn(1, reference_no="1001"),
        txn(2, reference_no="1003"),
        txn(3, reference_no="1009"),
    ]
    c6 = check(analyze_content(result(txns)).checks, "C6")
    assert c6.status == "hint"
    assert "参考号跳号 2 处" in c6.detail


def test_reference_too_few_rows_is_skipped():
    txns = [txn(1, reference_no="1001"), txn(2, reference_no="1002")]
    c6 = check(analyze_content(result(txns)).checks, "C6")
    assert c6.status == "skipped"
    assert "不足 3 笔" in c6.detail


def test_reference_single_value_is_not_one_per_row():
    txns = [txn(row, reference_no="1001") for row in (1, 2, 3)]
    c6 = check(analyze_content(result(txns)).checks, "C6")
    assert c6.status == "skipped"
    assert "疑似非一笔一号" in c6.detail


def test_reference_missing_is_skipped():
    txns = [txn(row) for row in (1, 2, 3)]
    c6 = check(analyze_content(result(txns)).checks, "C6")
    assert c6.status == "skipped"
    assert "未识别到参考号" in c6.detail


def test_reference_partial_coverage_is_partial():
    txns = [
        txn(1, reference_no="1001"),
        txn(2, reference_no="1002"),
        txn(3, reference_no="1003"),
        txn(4, reference_no=None),
    ]
    c6 = check(analyze_content(result(txns)).checks, "C6")
    assert c6.status == "partial"
    assert "已核对 3 笔参考号" in c6.detail
    assert "另有 1 笔缺参考号未参与" in c6.detail


def test_time_missing_is_skipped():
    c7 = check(analyze_content(result([txn(1)])).checks, "C7")
    assert c7.status == "skipped"
    assert "无交易时间" in c7.detail


def test_night_trade_is_hint():
    txns = [
        txn(1, trade_time="23:30:00"),
        txn(2, trade_time="09:00:00"),
        txn(3, trade_time="12:00:00"),
    ]
    c7 = check(analyze_content(result(txns)).checks, "C7")
    assert c7.status == "hint"
    assert "夜间（22:00–06:00）1 笔" in c7.detail
    assert [(e.page_no, e.row_no) for e in c7.evidence] == [(1, 1)]


def test_same_second_burst_is_hint_with_rows():
    txns = [
        txn(1, trade_time="09:00:00"),
        txn(2, trade_time="09:00:00"),
        txn(3, trade_time="10:00:00"),
    ]
    c7 = check(analyze_content(result(txns)).checks, "C7")
    assert c7.status == "hint"
    assert "同日同秒 1 组" in c7.detail
    assert [(e.page_no, e.row_no) for e in c7.evidence] == [(1, 1), (1, 2)]


def test_invalid_time_is_recognition_skip():
    c7 = check(analyze_content(result([txn(1, trade_time="9:00")])).checks, "C7")
    assert c7.status == "skipped"
    assert c7.attribution.cause == "recognition"
    assert "时间格式非 HH:MM:SS" in c7.detail


def test_time_without_date_is_recognition_skip():
    c7 = check(
        analyze_content(result([txn(1, trade_time="09:00:00", txn_date=None)])).checks,
        "C7",
    )
    assert c7.status == "skipped"
    assert c7.attribution.cause == "recognition"
    assert "日期缺失" in c7.detail


def test_amount_shape_without_amounts_is_skipped():
    c8 = check(analyze_content(result([txn(1, amount=None)])).checks, "C8")
    assert c8.status == "skipped"
    assert "无交易金额" in c8.detail


def test_amount_shape_statistics_hint_with_repeat_rows():
    txns = [
        txn(1, amount="100.00"),
        txn(2, amount="100.00"),
        txn(3, amount="100.50"),
        txn(4, amount="33.33"),
    ]
    c8 = check(analyze_content(result(txns)).checks, "C8")
    assert c8.status == "hint"
    assert "整数金额 2 笔（50.0%）" in c8.detail
    assert "同额重复 1 组（100.00 ×2）" in c8.detail
    assert [(e.page_no, e.row_no) for e in c8.evidence] == [(1, 1), (1, 2)]


def test_amount_shape_small_sample_is_noted():
    txns = [txn(1, amount="10.00"), txn(2, amount="20.00"), txn(3, amount="30.00")]
    c8 = check(analyze_content(result(txns)).checks, "C8")
    assert "样本少于 10 笔" in c8.detail


def test_semantics_interest_debit_is_hint():
    txns = [
        txn(1, direction="out", summary="结息"),
        txn(2, summary="转账"),
        txn(3, summary="消费", direction="out"),
    ]
    c9 = check(analyze_content(result(txns)).checks, "C9")
    assert c9.status == "hint"
    assert "规则1" in c9.detail
    assert "结息" in c9.detail


def test_semantics_loan_interest_excluded():
    txns = [txn(1, direction="out", summary="贷款利息"), txn(2, summary="转账")]
    c9 = check(analyze_content(result(txns)).checks, "C9")
    assert c9.status == "pass"
    assert "未命中" in c9.detail


def test_semantics_salary_to_person_is_hint():
    txns = [
        txn(1, summary="工资", counterparty="张三"),
        txn(2, summary="转账"),
        txn(3, summary="消费", direction="out"),
    ]
    c9 = check(analyze_content(result(txns)).checks, "C9")
    assert c9.status == "hint"
    assert "规则7" in c9.detail
    assert "张三" not in c9.detail


def test_semantics_no_rule_executable_is_skipped():
    txns = [txn(1, summary=None, counterparty=None)]
    c9 = check(analyze_content(result(txns)).checks, "C9")
    assert c9.status == "skipped"
    assert "无规则可执行" in c9.detail


def test_duplicate_with_same_valid_reference_fails():
    txns = [
        txn(1, reference_no="1001"),
        txn(2, reference_no="1001"),
        txn(3, reference_no="1002", txn_date="2025-01-02"),
    ]
    out = analyze_content(result(txns))
    c10 = check(out.checks, "C10")
    assert c10.status == "fail"
    assert "同一参考号「1001」" in c10.detail
    assert c10.attribution.cause == "data" and c10.attribution.action == "stop"
    assert [(e.page_no, e.row_no) for e in c10.evidence] == [(1, 1), (1, 2)]
    assert out.status == "inconsistent"


def test_duplicate_with_unusable_reference_stays_hint():
    txns = [txn(1, reference_no="1001"), txn(2, reference_no="1001")]
    c10 = check(analyze_content(result(txns)).checks, "C10")
    assert c10.status == "hint"
    assert "不足以确认" in c10.detail


def test_empty_statement_is_undetermined():
    out = analyze_content(result([]))
    assert out.status == "undetermined"
    assert "未解析到交易明细，无法核对" in out.limitations
