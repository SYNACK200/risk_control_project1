"""内核自测：注册表的发现/校验/装配，编排的进度事件与错误策略。

这些测试不碰任何文件与数据库：证明「骨架本身」成立，不证明业务口径。
业务口径由 test_parity_compat.py 对着封存版本比对。
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from rc_platform.core import contracts
from rc_platform.core.context import JobContext
from rc_platform.core.errors import CapabilityError, ContractCycle, ContractMissing, PipelineFailed
from rc_platform.core.events import ProgressEvent
from rc_platform.core.pipeline import Pipeline
from rc_platform.core.registry import Registry, capability, discover


def make(name, provides, requires=(), *, output=None, fail=False, priority=0):
    """造一个最小能力类；不走装饰器，避免污染全局目录。"""
    cls = type(name.replace(".", "_"), (), {})
    cls.name = name
    cls.version = "0"
    cls.provides = provides
    cls.requires = tuple(requires)
    cls.priority = priority

    def run(self, ctx, inputs):
        if fail:
            raise RuntimeError("boom")
        return output if output is not None else {"from": name, "inputs": sorted(inputs)}

    cls.run = run
    return cls


def catalog(*classes):
    return {c.name: c for c in classes}


# ---- 装饰器校验 ----

def test_decorator_rejects_missing_run():
    cls = make("t.no_run", "profile")
    del cls.run
    with pytest.raises(CapabilityError):
        capability(cls)


def test_decorator_rejects_unknown_contract():
    cls = make("t.unknown_contract", "not_a_contract")
    with pytest.raises(CapabilityError):
        capability(cls)


def test_decorator_rejects_duplicate_name():
    first = type("First", (), dict(name="t.dup", version="0", provides="profile", requires=(), run=lambda s, c, i: None))
    second = type("Second", (), dict(name="t.dup", version="0", provides="profile", requires=(), run=lambda s, c, i: None))
    capability(first)
    with pytest.raises(CapabilityError):
        capability(second)


# ---- 发现与装配 ----

def test_discover_finds_compat_capabilities():
    discover()
    reg = Registry()
    for expected in (
        "preread.algorithm_compat",
        "parse.algorithm_compat",
        "verify.algorithm_compat",
        "metrics.algorithm_compat",
        "report.algorithm_compat",
    ):
        assert expected in reg.names()


def test_plan_puts_dependencies_first():
    reg = Registry(catalog(
        make("a.profile", "profile", ("document",)),
        make("a.statement", "statement", ("document", "profile")),
        make("a.verification", "verification", ("document", "profile", "statement")),
        make("a.metrics", "metrics", ("statement",)),
        make("a.report", "report", ("profile", "statement", "verification", "metrics")),
    ))
    plan = reg.plan("report")
    assert plan[-1] == "a.report"
    assert plan.index("a.profile") < plan.index("a.statement") < plan.index("a.verification")
    assert plan.index("a.metrics") < plan.index("a.report")


def test_plan_honours_override_between_two_providers():
    reg = Registry(catalog(
        make("p.fast", "statement", ("document",), priority=10),
        make("p.slow", "statement", ("document",), priority=0),
    ))
    assert reg.plan("statement") == ["p.fast"]
    assert reg.plan("statement", overrides={"statement": "p.slow"}) == ["p.slow"]


def test_plan_refuses_when_every_provider_is_disabled():
    reg = Registry(catalog(make("p.only", "statement", ("document",))))
    with pytest.raises(ContractMissing):
        reg.plan("statement", disabled={"p.only"})


def test_plan_detects_cycle():
    reg = Registry(catalog(
        make("c.one", "profile", ("statement",)),
        make("c.two", "statement", ("profile",)),
    ))
    with pytest.raises(ContractCycle):
        reg.plan("statement")


def test_describe_is_json_safe():
    reg = Registry(catalog(make("d.x", "profile")))
    described = reg.describe()
    assert described == [{
        "name": "d.x", "version": "0", "provides": "profile",
        "requires": [], "optional_requires": [], "priority": 0, "doc": "",
    }]


# ---- 编排 ----

def test_pipeline_runs_chain_and_emits_events():
    reg = Registry(catalog(
        make("r.profile", "profile", ("document",), output="PROFILE"),
        make("r.statement", "statement", ("profile",), output="STATEMENT"),
    ))
    events: list[ProgressEvent] = []
    ctx = JobContext(job_id="j1", sink=events.append)
    result = Pipeline(reg, reg.plan("statement")).run(ctx, {"document": "DOC"})

    assert result.status == "ok"
    assert result.get("statement") == "STATEMENT"
    assert [e.status for e in events] == ["start", "ok", "start", "ok"]
    assert [e.index for e in events] == [1, 1, 2, 2]
    assert all(e.total == 2 and e.job_id == "j1" for e in events)


def test_pipeline_degrade_skips_downstream_and_records_reason():
    reg = Registry(catalog(
        make("g.profile", "profile", ("document",), fail=True),
        make("g.statement", "statement", ("profile",), output="S"),
    ))
    ctx = JobContext()
    result = Pipeline(reg, reg.plan("statement"), on_error="degrade").run(ctx, {"document": "D"})

    assert result.status == "degraded"
    assert [s.status for s in result.stages] == ["failed", "skipped"]
    assert "g.profile" in result.degradation[0]
    assert result.get("statement") is None


def test_pipeline_fail_policy_raises_with_stage_name():
    reg = Registry(catalog(make("f.profile", "profile", ("document",), fail=True)))
    with pytest.raises(PipelineFailed) as info:
        Pipeline(reg, reg.plan("profile")).run(JobContext(), {"document": "D"})
    assert info.value.stage == "f.profile"


def test_context_dotted_setting_reads_flat_and_nested():
    ctx = JobContext(config={"parse.template": {"bank_code": "ICBC"}, "ocr": {"workers": 2}})
    assert ctx.setting("parse.template")["bank_code"] == "ICBC"
    assert ctx.setting("ocr.workers") == 2
    assert ctx.setting("missing.key", "fallback") == "fallback"


# ---- 架构守卫 ----

def test_core_never_imports_concrete_capabilities():
    """主干只允许依赖内核；一旦 import 具体能力，插件式就名存实亡。"""
    core = pathlib.Path(__file__).resolve().parents[1] / "core"
    offenders = []
    for path in core.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "capabilities" in node.module:
                offenders.append(f"{path.name}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "capabilities" in alias.name:
                        offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


def test_contract_names_are_complete():
    assert set(contracts.contract_names()) == {
        "document", "profile", "layout", "statement",
        "layer_file", "layer_content", "layer_ledger", "layer_external",
        "verification", "metrics", "features", "report",
    }
