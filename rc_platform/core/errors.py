"""平台异常：能力层不抛裸 Exception，便于上层区分可重试与不可重试。"""
from __future__ import annotations


class PlatformError(Exception):
    """平台自身错误。"""


class CapabilityError(PlatformError):
    """能力定义或注册有误（名字重复、契约缺失、缺 run）。"""


class ContractMissing(PlatformError):
    """编排时找不到能产出某个契约的能力。"""


class ContractCycle(PlatformError):
    """能力依赖成环。"""


class PipelineFailed(PlatformError):
    """阶段执行失败（on_error=fail 时抛出）。"""

    def __init__(self, stage: str, capability: str, cause: BaseException):
        super().__init__(f"阶段 {stage}（能力 {capability}）失败：{cause}")
        self.stage = stage
        self.capability = capability
        self.cause = cause
