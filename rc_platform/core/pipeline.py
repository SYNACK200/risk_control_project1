"""编排执行：按注册表给出的顺序跑能力，产出进度事件与运行报告。

错误策略两种：
- fail   ：任何阶段失败即整单失败（默认，受理/落库这类不能带病继续的用它）
- degrade：记录失败、跳过缺契约的下游、整体标记 degraded，报告里写清降级原因
           （核验层必须用它：不可算 != 通过，这是旧版既有口径）
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .context import JobContext
from .errors import PipelineFailed
from .events import ProgressEvent
from .registry import Registry


@dataclass(slots=True)
class StageOutcome:
    capability: str
    provides: str
    status: str                 # ok / failed / skipped
    elapsed_ms: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {
            "capability": self.capability,
            "provides": self.provides,
            "status": self.status,
            "elapsed_ms": self.elapsed_ms,
        }
        if self.error:
            out["error"] = self.error
        return out


@dataclass(slots=True)
class RunResult:
    job_id: str
    status: str                 # ok / degraded / failed
    artifacts: dict[str, Any] = field(default_factory=dict)
    stages: list[StageOutcome] = field(default_factory=list)
    elapsed_ms: int = 0
    degradation: list[str] = field(default_factory=list)

    def get(self, contract: str, default: Any = None) -> Any:
        return self.artifacts.get(contract, default)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "elapsed_ms": self.elapsed_ms,
            "stages": [s.to_dict() for s in self.stages],
            "degradation": list(self.degradation),
        }


class Pipeline:
    def __init__(
        self,
        registry: Registry,
        plan: Iterable[str],
        *,
        on_error: str = "fail",
    ):
        if on_error not in ("fail", "degrade"):
            raise ValueError("on_error 只能是 fail 或 degrade")
        self.registry = registry
        self.plan = list(plan)
        self.on_error = on_error

    def run(self, ctx: JobContext, seed: Mapping[str, Any] | None = None) -> RunResult:
        started = time.perf_counter()
        artifacts: dict[str, Any] = dict(seed or {})
        stages: list[StageOutcome] = []
        degradation: list[str] = []
        total = len(self.plan)
        status = "ok"

        for index, name in enumerate(self.plan, 1):
            info = self.registry.info(name)
            missing = [need for need in info.requires if need not in artifacts]
            if missing:
                reason = f"缺上游契约 {','.join(missing)}"
                stages.append(StageOutcome(name, info.provides, "skipped", 0, reason))
                degradation.append(f"{name} 已跳过：{reason}")
                status = "degraded"
                ctx.emit(ProgressEvent(ctx.job_id, name, index, total, "skipped", 0, reason))
                continue

            inputs = {need: artifacts[need] for need in info.requires}
            inputs.update({need: artifacts[need] for need in info.optional_requires if need in artifacts})
            ctx.emit(ProgressEvent(ctx.job_id, name, index, total, "start"))
            t0 = time.perf_counter()
            try:
                instance = info.cls()
                output = instance.run(ctx, inputs)
            except Exception as exc:  # noqa: BLE001 - 由策略决定后果
                elapsed = int((time.perf_counter() - t0) * 1000)
                stages.append(StageOutcome(name, info.provides, "failed", elapsed, str(exc)))
                ctx.emit(ProgressEvent(ctx.job_id, name, index, total, "failed", elapsed, str(exc)))
                if self.on_error == "fail":
                    raise PipelineFailed(name, name, exc) from exc
                degradation.append(f"{name} 失败：{exc}")
                status = "degraded"
                continue

            elapsed = int((time.perf_counter() - t0) * 1000)
            if info.provides:
                artifacts[info.provides] = output
            stages.append(StageOutcome(name, info.provides, "ok", elapsed))
            ctx.emit(ProgressEvent(ctx.job_id, name, index, total, "ok", elapsed))

        return RunResult(
            job_id=ctx.job_id,
            status=status,
            artifacts=artifacts,
            stages=stages,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            degradation=degradation,
        )
