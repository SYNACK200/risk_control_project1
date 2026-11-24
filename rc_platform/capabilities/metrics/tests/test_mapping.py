"""映射表自测：清单必须完整，已映射的必须与旧实现逐值一致。

这条测试的意义不是「测一下函数」，而是把「两套口径」的漂移变成红灯：
旧实现改了口径、或特征算子改了语义，这里会立刻红。
"""
from __future__ import annotations

import pathlib
import sys
from decimal import Decimal

import pytest

from rc_platform.capabilities.metrics.mapping import ALL_CODES, coverage, evaluate, registry
from rc_platform.core.context import JobContext
from rc_platform.core.contracts import SourceDocument
from rc_platform.core.pipeline import Pipeline
from rc_platform.core.registry import default_registry

ROOT = pathlib.Path(__file__).resolve().parents[4]
SAMPLE = ROOT / "algorithm" / "inputs" / "samples" / "synthetic" / "clean" / "icbc.pdf"


def test_every_metric_is_accounted_for():
    table = registry()
    assert set(table) == set(ALL_CODES)
    for code, item in table.items():
        assert item.mapped or item.blocked, f"{code} 既没映射也没写原因"
        if item.blocked:
            assert len(item.blocked) >= 8, f"{code} 的原因太含糊：{item.blocked}"


def test_blocked_reasons_are_specific():
    reasons = {item.blocked for item in registry().values() if item.blocked}
    assert "尚未映射：等映射表补齐后再动旧实现" not in reasons, "还有指标没写具体原因"


def test_coverage_numbers():
    stats = coverage()
    assert stats["total"] == 40
    assert stats["mapped"] + stats["blocked"] == 40


@pytest.mark.skipif(not SAMPLE.exists(), reason="合成样本未生成")
def test_mapped_metrics_match_the_sealed_implementation():
    backend = str(ROOT / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from services.analysis import run_analysis

    data = SAMPLE.read_bytes()
    old = {item["code"]: item["value"] for item in run_analysis(data)["metrics"]}

    registry_ = default_registry()
    result = Pipeline(registry_, registry_.plan("statement"), on_error="degrade").run(
        JobContext(), {"document": SourceDocument(data=data)}
    )
    new = evaluate(result.get("statement"))

    mappings = {code: item for code, item in registry().items() if item.mapped}
    assert mappings, "至少要有一些已映射的指标"
    for code, item in mappings.items():
        expected = old.get(code)
        actual = new.get(code)
        if expected is None and actual is None:
            continue
        left = None if expected in (None, "") else Decimal(str(expected)).quantize(Decimal(10) ** -item.scale)
        right = None if actual is None else Decimal(actual).quantize(Decimal(10) ** -item.scale)
        assert left == right, f"{code} {item.name}：旧 {expected} / 新 {actual}"
