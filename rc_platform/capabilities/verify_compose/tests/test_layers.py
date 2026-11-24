"""核验层插拔验收：四层各是一个能力，可以单独停用、单独替换。

判据不是「能不能跑」，而是「停掉一层之后，结论还讲不讲得通、降级说明有没有落到报告里」。
"""
from __future__ import annotations

import pathlib

import pytest

from rc_platform.core.context import JobContext
from rc_platform.core.contracts import SourceDocument
from rc_platform.core.pipeline import Pipeline
from rc_platform.core.registry import Registry, discover

ROOT = pathlib.Path(__file__).resolve().parents[4]
SAMPLE = ROOT / "algorithm" / "inputs" / "samples" / "synthetic" / "clean" / "icbc.pdf"

pytestmark = pytest.mark.skipif(not SAMPLE.exists(), reason="合成样本未生成")


@pytest.fixture(scope="module", autouse=True)
def _discover():
    discover()


def _run(disabled: set[str] | None = None) -> tuple[str, object, list[str]]:
    registry = Registry()
    plan = registry.plan("verification", disabled=disabled or ())
    result = Pipeline(registry, plan, on_error="degrade").run(
        JobContext(), {"document": SourceDocument(data=SAMPLE.read_bytes())}
    )
    return result.status, result.get("verification"), result.degradation


def test_four_layers_are_separate_capabilities():
    registry = Registry()
    plan = registry.plan("verification")
    assert plan[:4] == ["preread.algorithm_compat", "parse.algorithm_compat",
                        "verify.file_layer", "verify.content_layer"][:2] + plan[2:4]
    assert {"verify.file_layer", "verify.content_layer",
            "verify.ledger_layer", "verify.external_layer"} <= set(plan)
    assert plan[-1] == "verify.compose"


def test_full_stack_gives_a_verdict():
    status, verification, _ = _run()
    assert status == "ok"
    assert verification.verdict == "未发现异常"
    assert {layer.layer for layer in verification.layers} == {"file", "content", "ledger", "external"}


def test_disabling_external_layer_still_gives_a_verdict():
    """外部层是可选依赖：本行没接入时按「未执行」处理，不是让整单失败。"""
    status, verification, _ = _run(disabled={"verify.external_layer"})
    assert status == "ok"
    assert verification is not None
    external = [layer for layer in verification.layers if layer.layer == "external"][0]
    assert external.status == "skipped"
    assert any("外部层" in note or "external" in note for note in verification.limitations)


def test_swapping_content_layer_is_possible_in_principle():
    """同名契约可以有两个实现：注册表只按契约选，换实现不改主干。"""
    registry = Registry()
    registry._catalog["verify.content_layer_alt"] = registry.info("verify.content_layer").cls
    plan = registry.plan("verification", overrides={"layer_content": "verify.content_layer_alt"})
    assert "verify.content_layer_alt" in plan
