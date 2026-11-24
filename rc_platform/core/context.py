"""任务上下文：一次编排运行的可变状态与出口。"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

from .events import EventSink, ProgressEvent, null_sink


@dataclass
class JobContext:
    job_id: str = "local"
    config: Mapping[str, Any] = field(default_factory=dict)
    sink: EventSink = null_sink
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("rc_platform"))

    def setting(self, key: str, default: Any = None) -> Any:
        """点号取值：setting("parse.template") 先查扁平键再查嵌套。"""
        if key in self.config:
            return self.config[key]
        node: Any = self.config
        for part in key.split("."):
            if not isinstance(node, Mapping) or part not in node:
                return default
            node = node[part]
        return node

    def emit(self, event: ProgressEvent) -> None:
        try:
            self.sink(event)
        except Exception:  # noqa: BLE001 - 进度上报不得影响主流程
            self.logger.warning("进度上报失败：%s", event.stage)
