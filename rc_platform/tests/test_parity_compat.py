"""行为对照：新骨架跑出来的结论必须和封存版本一模一样。

M1 的验收标准只有一条：容器换了，判据没换。
对照物是封存版本的 production 入口 backend/services/analysis.run_analysis。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "algorithm" / "inputs" / "samples" / "synthetic" / "clean" / "icbc.pdf"

pytestmark = pytest.mark.skipif(not SAMPLE.exists(), reason="合成样本未生成：python -m algorithm.algo.samples --out ...")


def _old_analysis():
    """旧版 production 入口；只在测试里 import，确保新骨架不依赖 backend/。"""
    backend = str(ROOT / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from services.analysis import run_analysis  # noqa: PLC0415

    return run_analysis


def test_new_pipeline_matches_sealed_analysis():
    from rc_platform.core.context import JobContext
    from rc_platform.core.contracts import SourceDocument
    from rc_platform.core.pipeline import Pipeline
    from rc_platform.core.registry import default_registry

    data = SAMPLE.read_bytes()
    old = _old_analysis()(data)

    registry = default_registry()
    plan = registry.plan("report")
    result = Pipeline(registry, plan, on_error="degrade").run(
        JobContext(job_id="parity"), {"document": SourceDocument(data=data)}
    )

    assert result.status == "ok", result.to_dict()
    assert result.get("verification").verdict == old["report"]["verdict"]
    assert len(result.get("statement").rows) == old["txn_count"]

    new_metrics = {
        item.code: (None if item.value is None else str(item.value))
        for item in result.get("metrics").items
    }
    old_metrics = {item["code"]: item["value"] for item in old["metrics"]}
    assert new_metrics == old_metrics


def test_pipeline_reports_stage_timings():
    from rc_platform.core.context import JobContext
    from rc_platform.core.contracts import SourceDocument
    from rc_platform.core.pipeline import Pipeline
    from rc_platform.core.registry import default_registry

    registry = default_registry()
    result = Pipeline(registry, registry.plan("report"), on_error="degrade").run(
        JobContext(job_id="timing"), {"document": SourceDocument(data=SAMPLE.read_bytes())}
    )
    names = [stage.capability for stage in result.stages]
    assert names[0].startswith("preread.")
    assert names[-1].startswith("report.")
    assert all(stage.elapsed_ms >= 0 for stage in result.stages)
