"""worker：把「领取 → 执行 → 收尾」固定下来，业务只写 handler。

handler 通过 emit 上报进度：每来一个 ProgressEvent 就落一次 job.stage/progress，
同时续一次租约——长任务靠这条路径保命，不必另开心跳线程。handler 抛异常即视为
本次尝试失败，按 service 的重试策略排队或进死信。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Protocol

from ..core.events import ProgressEvent
from .models import Job
from .service import QueueService

Emitter = Callable[[ProgressEvent], None]
Handler = Callable[[Job, Emitter], Any]

_log = logging.getLogger("rc_platform.queue")


class _Service(Protocol):
    def claim(self, worker_id: str, lease_seconds: float = 60) -> Job | None: ...
    def heartbeat(self, job_id: str, worker_id: str, *, lease_seconds: float = 60) -> Job | None: ...
    def record_progress(self, job_id: str, event: ProgressEvent) -> Job | None: ...
    def complete(self, job_id: str, *, worker_id: str | None = None) -> Job | None: ...
    def fail(self, job_id: str, error: str, retryable: bool = True, *, worker_id: str | None = None) -> Job | None: ...


def _emitter(service: _Service, job: Job, worker_id: str, lease_seconds: float) -> Emitter:
    def emit(event: ProgressEvent) -> None:
        service.record_progress(job.id, event)
        if service.heartbeat(job.id, worker_id, lease_seconds=lease_seconds) is None:
            # 任务已被回收/取消：这里只记一笔，handler 下次 emit 会再发现，收尾时以状态机为准
            _log.warning("任务 %s 已不归 worker %s，续租失败", job.id, worker_id)

    return emit


def run_once(
    service: _Service,
    worker_id: str,
    handler: Handler,
    *,
    lease_seconds: float = 60,
) -> bool:
    """领一个任务并执行；队列空则返回 False（本轮什么都没干）。"""
    job = service.claim(worker_id, lease_seconds=lease_seconds)
    if job is None:
        return False
    emit = _emitter(service, job, worker_id, lease_seconds)
    try:
        handler(job, emit)
    except Exception as exc:  # noqa: BLE001 - 失败是正常路径，交给重试策略判定
        service.fail(job.id, f"{type(exc).__name__}: {exc}", retryable=True, worker_id=worker_id)
        return True
    service.complete(job.id, worker_id=worker_id)
    return True


def run_loop(
    service: _Service,
    worker_id: str,
    handler: Handler,
    *,
    lease_seconds: float = 60,
    idle_sleep: float = 0.02,
    idle_limit: int | None = None,
) -> int:
    """进程内 worker 循环，返回本 worker 处理的任务数。

    idle_limit 是「连续空转多少轮就退出」：测试与一次性批处理用它收尾；
    常驻进程传 None 就只靠 stop 信号停（本版不内置信号处理，交给调用方线程管理）。
    """
    done = 0
    idle = 0
    while True:
        if run_once(service, worker_id, handler, lease_seconds=lease_seconds):
            done += 1
            idle = 0
            continue
        idle += 1
        if idle_limit is not None and idle >= idle_limit:
            return done
        time.sleep(idle_sleep)
