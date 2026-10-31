import json
from dataclasses import replace

import pytest

from algorithm.algo.eval import (
    EvalReport,
    EvalSummary,
    evaluate_case,
    evaluate_samples,
    format_report,
    main,
)
from algorithm.algo.samples import SampleExpectation, build_sample_set


@pytest.fixture(scope="module")
def sample_dir(tmp_path_factory):
    directory = tmp_path_factory.mktemp("eval-samples")
    build_sample_set(directory)
    return directory


@pytest.fixture(scope="module")
def samples(sample_dir):
    from algorithm.algo.samples import load_samples

    return {sample.case.id: sample for sample in load_samples(sample_dir)}


def test_current_sample_set_passes(sample_dir):
    report = evaluate_samples(sample_dir)
    summary = report.summary

    assert summary.total == 9
    assert summary.passed == 9
    assert summary.failed == 0
    assert summary.sample_pass_rate == 1.0
    assert summary.verdict_accuracy == 1.0
    assert summary.txn_count_accuracy == 1.0
    assert summary.required_code_recall == 1.0
    assert summary.forgery_recall == 1.0
    assert summary.clean_false_positive_rate == 0.0
    assert summary.by_cause == {}


def test_eval_is_deterministic(sample_dir):
    first = evaluate_samples(sample_dir)
    second = evaluate_samples(sample_dir)

    assert first.model_dump() == second.model_dump()


def test_missing_rule_is_attributed_to_parameter_gap(samples):
    sample = samples["clean_icbc"]
    case = sample.case.model_copy(
        update={"expectation": SampleExpectation(verdict="未发现异常", txn_count=6, fail_codes=["A1"])}
    )
    result = evaluate_case(replace(sample, case=case))

    assert not result.passed
    assert result.missing_codes == ["A1"]
    assert result.issues[0].cause == "parameter_missing"
    assert result.issues[0].action == "add_parameter"


def test_clean_sample_with_tampering_is_false_positive(samples):
    sample = samples["forged_amount_icbc"]
    case = sample.case.model_copy(
        update={
            "forgery": None,
            "expectation": SampleExpectation(verdict="未发现异常", txn_count=6),
        }
    )
    result = evaluate_case(replace(sample, case=case))

    assert not result.passed
    assert result.extra_codes == ["C1"]
    assert result.issues[0].cause == "false_positive"
    assert result.issues[0].rule_codes == ["C1"]


def test_txn_count_mismatch_is_attributed_to_parsing(samples):
    sample = samples["clean_icbc"]
    case = sample.case.model_copy(
        update={"expectation": SampleExpectation(verdict="未发现异常", txn_count=7)}
    )
    result = evaluate_case(replace(sample, case=case))

    assert not result.passed
    assert result.issues[0].cause == "parsing"
    assert "7" in result.issues[0].detail


def test_verdict_mismatch_is_attributed_to_verdict_logic(samples):
    sample = samples["clean_icbc"]
    case = sample.case.model_copy(
        update={"expectation": SampleExpectation(verdict="存在不一致", txn_count=6)}
    )
    result = evaluate_case(replace(sample, case=case))

    assert not result.passed
    assert result.issues[0].cause == "verdict_logic"


def test_cli_writes_json_report(sample_dir, tmp_path, capsys):
    target = tmp_path / "report.json"
    code = main(["--samples", str(sample_dir), "--json", str(target)])

    assert code == 0
    output = capsys.readouterr().out
    assert "AL-16 样本评测报告" in output
    report = json.loads(target.read_text(encoding="utf-8"))
    assert report["summary"]["total"] == 9
    assert report["summary"]["passed"] == 9
    assert report["sample_set_version"] == 3


def test_cli_missing_samples_returns_error(tmp_path, capsys):
    code = main(["--samples", str(tmp_path / "missing")])

    assert code == 2
    assert "先生成样本" in capsys.readouterr().out


def test_format_report_contains_attribution(samples):
    sample = samples["clean_icbc"]
    case = sample.case.model_copy(
        update={"expectation": SampleExpectation(verdict="未发现异常", txn_count=6, fail_codes=["A1"])}
    )
    result = evaluate_case(replace(sample, case=case))
    report = EvalReport(
        sample_set_version=1,
        samples=".",
        cases=[result],
        summary=EvalSummary(
            total=1,
            passed=0,
            failed=1,
            sample_pass_rate=0.0,
            verdict_accuracy=1.0,
            txn_count_accuracy=1.0,
            required_code_recall=0.0,
            forgery_recall=0.0,
            clean_false_positive_rate=1.0,
            by_cause={"parameter_missing": 1},
        ),
    )
    text = format_report(report)

    assert "FAIL" in text
    assert "parameter_missing/add_parameter" in text
