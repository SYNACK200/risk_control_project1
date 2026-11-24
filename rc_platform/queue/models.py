"""队列任务的领域模型：一份 Job 就是一次待执行的单据执行。

字段分三类，用途不同：
- 身份与展示：id/biz_no/stage/progress，银行侧队列页直接读这几个渲染一行；
- 调度：priority/attempts/max_attempts/next_run_at/lease_until，只由 service 写；
- 时间戳：排障用（等了多久、跑了多久、心跳停了多久）。

进度复用 core/events.py 的 ProgressEvent，不另造一种进度结构：队列页、任务详情、
日志三处口径必须一致。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from ..core.events import ProgressEvent

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"
DEAD = "dead"

# 顺序即队列页的展示顺序，别随手调整
STATUSES = (QUEUED, RUNNING, DONE, FAILED, CANCELLED, DEAD)
TERMINAL = frozenset({DONE, FAILED, CANCELLED, DEAD})

# 退避基数与上限：2s -> 4s -> 8s ... 封顶 300s。改这里等于改所有业务的重试节奏
RETRY_BASE_SECONDS = 2.0
RETRY_CAP_SECONDS = 300.0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """统一成带时区的 UTC：库里存的是 naive（MySQL DATETIME 不带时区），读回来要补齐，
    否则 aware 与 naive 混比会直接抛 TypeError。"""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def backoff_seconds(
    attempts: int,
    *,
    base: float = RETRY_BASE_SECONDS,
    cap: float = RETRY_CAP_SECONDS,
) -> float:
    """第 attempts 次尝试失败后的等待秒数：base * 2^(attempts-1)，封顶 cap。"""
    if attempts < 1:
        attempts = 1
    # 先截断指数再算，避免 attempts 特别大时 2**n 把 float 撑成 inf
    if attempts > 32:
        return float(cap)
    return float(min(cap, base * (2 ** (attempts - 1))))


@dataclass(slots=True)
class Job:
    id: str
    biz_no: str | None = None
    status: str = QUEUED
    priority: int = 0
    attempts: int = 0
    max_attempts: int = 3
    stage: str = ""
    progress: float = 0.0
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    worker_id: str | None = None
    # seq 是存储层发的自增序号：同一优先级按它 FIFO。时间戳会撞在同一微秒，不能当次序用
    seq: int = 0
    enqueued_at: datetime = field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    heartbeat_at: datetime | None = None
    next_run_at: datetime | None = None
    lease_until: datetime | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL

    def apply_event(self, event: ProgressEvent) -> None:
        """把一条进度事件压成队列页要读的两个字段。"""
        self.stage = event.stage
        if event.total > 0:
            self.progress = max(0.0, min(1.0, event.index / event.total))

    def wait_seconds(self, now: datetime) -> float:
        """入队到现在（已开始则为到开始）等了多久。"""
        end = as_utc(self.started_at) if self.started_at else as_utc(now)
        start = as_utc(self.enqueued_at)
        if end is None or start is None:
            return 0.0
        return max(0.0, (end - start).total_seconds())

    def copy(self) -> "Job":
        """跨存储/跨线程传递一律给副本，防止调用方改了对象却没落库。"""
        return replace(self, payload=dict(self.payload))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "biz_no": self.biz_no,
            "status": self.status,
            "priority": self.priority,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "stage": self.stage,
            "progress": round(self.progress, 4),
            "payload": dict(self.payload),
            "error": self.error,
            "worker_id": self.worker_id,
        }
        for name in ("enqueued_at", "started_at", "finished_at", "heartbeat_at", "next_run_at", "lease_until"):
            value = getattr(self, name)
            out[name] = as_utc(value).isoformat() if value else None
        return out


def new_job(
    payload: dict[str, Any] | None = None,
    *,
    priority: int = 0,
    biz_no: str | None = None,
    max_attempts: int = 3,
    now: datetime | None = None,
) -> Job:
    """造一个待入队任务；id 用 uuid4 hex，免得 worker 之间还要为发号同步。"""
    if max_attempts < 1:
        raise ValueError("max_attempts 至少为 1")
    stamp = as_utc(now) or utcnow()
    return Job(
        id=uuid.uuid4().hex,
        biz_no=biz_no,
        status=QUEUED,
        priority=int(priority),
        max_attempts=int(max_attempts),
        payload=dict(payload or {}),
        enqueued_at=stamp,
        next_run_at=stamp,
    )


def lease_deadline(now: datetime, lease_seconds: float) -> datetime:
    if lease_seconds <= 0:
        raise ValueError("lease_seconds 必须为正数")
    return as_utc(now) + timedelta(seconds=lease_seconds)
