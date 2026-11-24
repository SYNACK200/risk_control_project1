"""能力级验收：注册表能发现它，编排能把它跑出 FeatureSet，配置能改它的定义集合。"""
from __future__ import annotations

from decimal import Decimal

from rc_platform.core.context import JobContext
from rc_platform.core.contracts import FeatureSet, Statement
from rc_platform.core.pipeline import Pipeline
from rc_platform.core.registry import Registry, discover

from ..defs import BUILTIN_FEATURES
from ..plugin import FeatureDerivation
from . import sample_rows


def registry() -> Registry:
    discover()
    return Registry()


def test_registry_finds_the_feature_capability():
    info = registry().info("features.derivation")
    assert info.provides == "features"
    assert info.requires == ("statement",)
    assert info.priority == 0
    assert info.version == "1.0"
    assert "features.derivation" in registry().providers("features")


def test_pipeline_turns_a_statement_into_a_feature_set():
    reg = registry()
    plan = reg.plan("features")
    result = Pipeline(reg, plan, on_error="degrade").run(
        JobContext(job_id="m3"), {"statement": Statement(rows=sample_rows())}
    )
    artifact = result.get("features")
    assert isinstance(artifact, FeatureSet)
    assert len(artifact.records) == len(BUILTIN_FEATURES)
    filled = [record for record in artifact.records if record["value"] is not None]
    assert len(filled) >= 12, [r["code"] for r in artifact.records if r["value"] is None]
    assert any(record["value"] == Decimal("13050.75") for record in filled)


def test_capability_skips_when_statement_is_missing():
    reg = registry()
    result = Pipeline(reg, reg.plan("features"), on_error="degrade").run(JobContext(job_id="m3-empty"))
    assert result.get("features") is None
    assert result.status == "degraded"


def test_capability_reads_config_definitions_and_filter():
    ctx = JobContext(config={
        "features.defs": [{"code": "x_mine", "name": "自定义夜间笔数", "unit": "笔",
                           "expr": "count(where=(hour>=22) or (hour<=5))"}],
        "features.only": ["x_mine", "f_txn_count"],
    })
    artifact = FeatureDerivation().run(ctx, {"statement": Statement(rows=sample_rows())})
    assert [record["code"] for record in artifact.records] == ["f_txn_count", "x_mine"]
    values = {record["code"]: record["value"] for record in artifact.records}
    assert values == {"f_txn_count": 8, "x_mine": 3}
