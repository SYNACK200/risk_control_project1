"""任务状态机：所有后端状态变更都必须经由此模块。"""
from __future__ import annotations

from dataclasses import dataclass


TRANSITIONS: dict[str, frozenset[str]] = {
    "PENDING": frozenset({"CHECKING", "FAILED"}),
    "CHECKING": frozenset({"PARSING", "FAILED"}),
    "PARSING": frozenset({"VERIFYING", "NEED_SUPPLEMENT", "FAILED"}),
    "NEED_SUPPLEMENT": frozenset({"PARSING", "FAILED"}),
    "VERIFYING": frozenset({"REPORTING", "FAILED"}),
    "REPORTING": frozenset({"DONE", "FAILED"}),
    "DONE": frozenset(),
    "FAILED": frozenset({"PENDING"}),
}


@dataclass(frozen=True)
class InvalidTransition(ValueError):
    current: str
    target: str

    def __str__(self) -> str:
        return f"不允许任务状态从 {self.current} 转为 {self.target}"


def transition(task: object, target: str) -> None:
    """校验并迁移任意拥有 ``status`` 属性的任务对象。"""
    current = str(getattr(task, "status"))
    if target not in TRANSITIONS.get(current, frozenset()):
        raise InvalidTransition(current=current, target=target)
    setattr(task, "status", target)
