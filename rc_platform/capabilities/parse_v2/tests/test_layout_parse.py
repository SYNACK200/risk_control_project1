"""M2 验收：新几何驱动的解析，笔数不能比无模板的旧路少。

为什么用「笔数」当判据：版式检测对不对，最终体现在能不能把行读全。
只比列名会自欺——列名对但边界偏，行就丢了一半。
"""
from __future__ import annotations

import pathlib

import pytest

from rc_platform.core.context import JobContext
from rc_platform.core.contracts import SourceDocument
from rc_platform.core.registry import Registry, discover

ROOT = pathlib.Path(__file__).resolve().parents[4]
SAMPLES = ROOT / "algorithm" / "inputs" / "samples" / "synthetic"

pytestmark = pytest.mark.skipif(not SAMPLES.exists(), reason="合成样本未生成")


def run_with(contract_override: str, path: pathlib.Path) -> int:
    from rc_platform.core.pipeline import Pipeline

    registry = Registry()
    plan = registry.plan("statement", overrides={"statement": contract_override})
    result = Pipeline(registry, plan, on_error="degrade").run(
        JobContext(job_id=path.stem), {"document": SourceDocument(data=path.read_bytes())}
    )
    statement = result.get("statement")
    return len(statement.rows) if statement else 0


@pytest.fixture(scope="module", autouse=True)
def _discover():
    discover()


@pytest.mark.parametrize("name", ["icbc", "ccb", "cmb", "wechat"])
def test_layout_path_reads_at_least_as_many_rows(name):
    path = SAMPLES / "clean" / f"{name}.pdf"
    old_rows = run_with("parse.algorithm_compat", path)
    new_rows = run_with("parse.layout_v2", path)
    assert old_rows > 0, "旧路都读不出来，样本或环境有问题"
    assert new_rows >= old_rows, f"{name}：新几何读到的笔数少于无模板旧路（{new_rows} < {old_rows}）"


@pytest.mark.parametrize("name", ["icbc_amount_tamper", "icbc_row_deleted", "icbc_page_splice"])
def test_layout_path_on_forged_samples(name):
    path = SAMPLES / "forged" / f"{name}.pdf"
    old_rows = run_with("parse.algorithm_compat", path)
    new_rows = run_with("parse.layout_v2", path)
    assert new_rows >= old_rows, f"{name}：新几何笔数 {new_rows} < 旧路 {old_rows}"
