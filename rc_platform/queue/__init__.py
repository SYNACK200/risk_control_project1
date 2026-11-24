"""队列与并发（M5）。

注意：这是运行时基础设施，不是流水线能力——所以这里没有 @capability、不产出契约，
core 的注册表也不需要认识它。银行侧队列页只读 service 的 position/stats 与 job 的
stage/progress。

分工：
- models  数据与状态常量、退避公式
- store   QueueStore 契约 + 两套实现（内存 / SQLAlchemy）
- service 状态机、租约心跳、重试、统计
- worker  领取→执行→收尾的固定流程与进程内循环
"""
from .models import (
    CANCELLED,
    DEAD,
    DONE,
    FAILED,
    QUEUED,
    RUNNING,
    STATUSES,
    TERMINAL,
    Job,
    backoff_seconds,
    utcnow,
)
from .service import QueueService
from .store import MemoryStore, QueueStore, SqlAlchemyStore
from .worker import run_loop, run_once

__all__ = [
    "CANCELLED",
    "DEAD",
    "DONE",
    "FAILED",
    "QUEUED",
    "RUNNING",
    "STATUSES",
    "TERMINAL",
    "Job",
    "MemoryStore",
    "QueueService",
    "QueueStore",
    "SqlAlchemyStore",
    "backoff_seconds",
    "run_loop",
    "run_once",
    "utcnow",
]
