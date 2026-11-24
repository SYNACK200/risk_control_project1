"""进度事件：队列页、任务详情、日志三处共用一种事件，避免各自拼字符串。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(slots=True)
class ProgressEvent:
    job_id: str
    stage: str                     # 能力名
    index: int                     # 第几个阶段，1 起
    total: int
    status: str                    # start / ok / failed / skipped
    elapsed_ms: int = 0
    message: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out = {
            "job_id": self.job_id,
            "stage": self.stage,
            "index": self.index,
            "total": self.total,
            "status": self.status,
            "elapsed_ms": self.elapsed_ms,
            "message": self.message,
        }
        if self.extra:
            out["extra"] = self.extra
        return out


EventSink = Callable[[ProgressEvent], None]


def null_sink(_: ProgressEvent) -> None:
    return None
