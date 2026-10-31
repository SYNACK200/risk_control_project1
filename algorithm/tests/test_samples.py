import pytest

from algorithm.algo.content_layer import analyze_content
from algorithm.algo.file_layer import analyze_file
from algorithm.algo.samples import (
    SAMPLE_FORGERY_TYPES,
    SAMPLE_LAYOUTS,
    build_sample_set,
    load_manifest,
    load_samples,
    validate_manifest,
)
from algorithm.algo.verdict import conclude
from algorithm.ocr.parse import parse


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    directory = tmp_path_factory.mktemp("samples")
    samples = build_sample_set(directory)
    return directory, {sample.case.id: sample for sample in samples}


def test_build_sample_set_covers_four_layouts_and_four_forgeries(built):
    directory, samples = built
    manifest = load_manifest(directory)

    assert manifest.version == 2
    assert len(samples) == 8
    assert {case.layout for case in manifest.cases} == set(SAMPLE_LAYOUTS)
    assert {case.forgery for case in manifest.cases if case.forgery} == set(SAMPLE_FORGERY_TYPES)
    assert all(sample.path.is_file() for sample in samples.values())


def test_clean_samples_parse_and_verdict(built):
    _, samples = built
    for sample in samples.values():
        if sample.case.forgery is not None:
            continue
        raw = sample.read_bytes()
        parsed = parse(raw)
        content = analyze_content(parsed)
        verdict = conclude(content, file_layer=analyze_file(raw))

        assert len(parsed.transactions) == sample.case.expectation.txn_count, sample.case.id
        assert content.status == "limited", sample.case.id
        assert verdict.verdict == sample.case.expectation.verdict, sample.case.id
        assert not [check for check in content.checks if check.status == "fail"], sample.case.id


def test_clean_wechat_has_no_balance_but_counts_match(built):
    _, samples = built
    parsed = parse(samples["clean_wechat"].read_bytes())

    assert len(parsed.transactions) == 4
    assert all(txn.balance is None for txn in parsed.transactions)
    assert [txn.direction for txn in parsed.transactions] == ["out", "in", "out", "in"]


def test_forged_amount_breaks_balance_chain(built):
    _, samples = built
    sample = samples["forged_amount_icbc"]
    raw = sample.read_bytes()
    parsed = parse(raw)
    content = analyze_content(parsed)

    failed = [check.code for check in content.checks if check.status == "fail"]
    assert failed == ["C1"]
    verdict = conclude(content, file_layer=analyze_file(raw))
    assert verdict.verdict == "存在不一致"
    assert {item.rule_code for item in verdict.evidence} == {"C1"}


def test_forged_overlay_is_source_suspicious(built):
    _, samples = built
    sample = samples["forged_overlay_icbc"]
    raw = sample.read_bytes()
    file_layer = analyze_file(raw)

    failed = {check.code for check in file_layer.checks if check.status == "fail"}
    assert {"F3", "F7"} <= failed
    assert file_layer.outcome == "来源可疑"

    verdict = conclude(analyze_content(parse(raw)), file_layer=file_layer)
    assert verdict.verdict == "来源可疑"


def test_forged_row_delete_breaks_chain_and_totals(built):
    _, samples = built
    sample = samples["forged_row_deleted_icbc"]
    raw = sample.read_bytes()
    parsed = parse(raw)
    content = analyze_content(parsed)

    assert len(parsed.transactions) == 5
    assert {check.code for check in content.checks if check.status == "fail"} == {"C1", "C2", "C3"}
    assert conclude(content, file_layer=analyze_file(raw)).verdict == "存在不一致"


def test_forged_page_splice_breaks_chain_at_seam(built):
    _, samples = built
    sample = samples["forged_page_splice_icbc"]
    raw = sample.read_bytes()
    parsed = parse(raw)
    content = analyze_content(parsed)

    assert len(parsed.transactions) == 6
    failed = [check for check in content.checks if check.status == "fail"]
    assert [check.code for check in failed] == ["C1"]
    assert "-10000.00" in failed[0].detail
    assert conclude(content, file_layer=analyze_file(raw)).verdict == "存在不一致"


def test_manifest_rejects_missing_coverage(built):
    directory, _ = built
    manifest = load_manifest(directory)
    manifest.cases = [case for case in manifest.cases if case.forgery is None]

    with pytest.raises(ValueError, match="缺少伪造类型"):
        validate_manifest(manifest, directory)


def test_manifest_rejects_missing_file(built):
    directory, _ = built
    manifest = load_manifest(directory)
    manifest.cases[0].path = "clean/not-there.pdf"

    with pytest.raises(ValueError, match="文件不存在"):
        validate_manifest(manifest, directory)


def test_manifest_rejects_path_traversal(built):
    directory, _ = built
    manifest = load_manifest(directory)
    manifest.cases[0].path = "../outside.pdf"

    with pytest.raises(ValueError, match="路径越界"):
        validate_manifest(manifest, directory)


def test_load_samples_accepts_explicit_directory(built):
    directory, samples = built
    loaded = load_samples(directory)

    assert len(loaded) == len(samples)
    assert all(sample.path.is_absolute() for sample in loaded)
