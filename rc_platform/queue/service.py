"""队列服务：状态机、重试策略、租约与统计都收在这一层。

一次任务的生命周期（括号里是谁写的状态）：

    enqueue ──────────────> queued
    claim   ──────────────> running        (store 原子领取，attempts + 1)
    heartbeat ────────────> running        (续租，不推进状态)
    complete ─────────────> done
    fail(retryable=True)  ─> queued + 退避 (attempts < max_attempts)
                          ─> dead         (attempts >= max_attempts，保留最后一次错误)
    fail(retryable=False) ─> failed        (不可重试，不再排队)
    cancel     ───────────> cancelled      (排队中或运行中都能取消)
    reclaim_expired ──────> 同 fail(retryable=True)：租约过期 = 这次尝试失败

所有写回都带期望条件（status/attempts），拿不到就返回 None：
worker 与「取消」「回收」撞车时，先到的一方赢，后到的一方拿到 None 后安静退出，
不会把已取消的任务改回 done。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Mapping

from ..core.events import ProgressEvent
from .models import (
    CANCELLED,
    DEAD,
    DONE,
    FAILED,
    QUEUED,
    RUNNING,
    STATUSES,
    Job,
    as_utc,
    backoff_seconds,
    lease_deadline,
    new_job,
    utcnow,
)
from .store import QueueStore

Clock = Callable[[], datetime]


class QueueService:
    def __init__(self, store: QueueStore, *, clock: Clock = utcnow):
        # clock 可注入：退避/租约过期这类时间相关的用例不该靠 sleep 等真时间
        self.store = store
        self._clock = clock

    # ---- 入队与查询 ----
    def enqueue(
        self,
        payload: Mapping[str, Any] | None = None,
        priority: int = 0,
        biz_no: str | None = None,
        max_attempts: int = 3,
    ) -> Job:
        """priority 数值越大越先被领取；同优先级按入队先后。"""
        job = new_job(
            dict(payload or {}),
            priority=priority,
            biz_no=biz_no,
            max_attempts=max_attempts,
            now=self._clock(),
        )
        return self.store.add(job)

    def get(self, job_id: str) -> Job | None:
        return self.store.get(job_id)

    def position(self, job_id: str) -> int | None:
        """排队名次，1 起；不在 queued 里（运行中/已结束/不存在）返回 None。

        名次按领取顺序算，退避等待中的任务仍占一个位置：它们确实还排在队里，
        只是到点之前不可被领取。
        """
        job = self.store.get(job_id)
        if job is None or job.status != QUEUED:
            return None
        for index, queued in enumerate(self.store.list(QUEUED), 1):
            if queued.id == job_id:
                return index
        return None

    def stats(self) -> dict[str, Any]:
        """队列页顶部卡片要的五个数字。全量扫描在单行任务量的场景够用，
        量大时应把计数下推成 SQL 聚合（见 README「已知限制」）。"""
        now = as_utc(self._clock())
        jobs = self.store.list()
        counts = {status: 0 for status in STATUSES}
        for job in jobs:
            counts[job.status] = counts.get(job.status, 0) + 1
        enqueued = [as_utc(job.enqueued_at) for job in jobs if job.enqueued_at]
        workers = {job.worker_id for job in jobs if job.status == RUNNING and job.worker_id}
        waits = [
            (as_utc(job.started_at) - as_utc(job.enqueued_at)).total_seconds()
            for job in jobs
            if job.started_at and job.enqueued_at
        ]
        return {
            "total": len(jobs),
            **counts,
            "oldest_enqueued_at": min(enqueued).isoformat() if enqueued else None,
            "running_workers": len(workers),
            "avg_wait_seconds": round(sum(waits) / len(waits), 3) if waits else 0.0,
        }

    # ---- 领取与续租 ----
    def claim(self, worker_id: str, lease_seconds: float = 60) -> Job | None:
        now = as_utc(self._clock())
        return self.store.claim(worker_id, now, lease_deadline(now, lease_seconds))

    def heartbeat(self, job_id: str, worker_id: str, *, lease_seconds: float = 60) -> Job | None:
        """续租。返回 None 表示任务已不属于这个 worker（被回收/被取消/已完成），
        worker 应当停手——这就是取消能生效的路径。"""
        job = self.store.get(job_id)
        if job is None or job.status != RUNNING or job.worker_id != worker_id:
            return None
        now = as_utc(self._clock())
        job.heartbeat_at = now
        job.lease_until = lease_deadline(now, lease_seconds)
        return job if self.store.write(job, {"status": RUNNING, "worker_id": worker_id}) else None

    # ---- 进度 ----
    def record_progress(self, job_id: str, event: ProgressEvent) -> Job | None:
        """把 ProgressEvent 落到 job.stage/progress，供银行侧队列页读取。

        只写进度、不动租约：续租由 heartbeat 负责，两个动作分开才能各自单独测。
        """
        job = self.store.get(job_id)
        if job is None or job.status != RUNNING:
            return None
        job.apply_event(event)
        return job if self.store.write(job, {"status": RUNNING}) else None

    # ---- 收尾 ----
    def complete(self, job_id: str, *, worker_id: str | None = None) -> Job | None:
        job = self.store.get(job_id)
        if job is None or job.status != RUNNING:
            return None
        if worker_id is not None and job.worker_id != worker_id:
            return None
        now = as_utc(self._clock())
        job.status = DONE
        job.finished_at = now
        job.heartbeat_at = now
        job.lease_until = None
        job.error = None
        job.progress = 1.0
        return job if self.store.write(job, {"status": RUNNING}) else None

    def fail(
        self,
        job_id: str,
        error: str,
        retryable: bool = True,
        *,
        worker_id: str | None = None,
    ) -> Job | None:
        job = self.store.get(job_id)
        if job is None or job.status != RUNNING:
            return None
        if worker_id is not None and job.worker_id != worker_id:
            return None
        attempts = job.attempts
        now = as_utc(self._clock())
        job.error = str(error)
        job.heartbeat_at = now
        job.lease_until = None
        job.worker_id = None
        if retryable and attempts < job.max_attempts:
            job.status = QUEUED
            job.next_run_at = now + timedelta(seconds=backoff_seconds(attempts))
            job.progress = 0.0
            job.stage = ""
        elif retryable:
            # 次数耗尽：进死信队列，最后一次错误留在 error 上给人工排查
            job.status = DEAD
            job.finished_at = now
        else:
            # 不可重试（数据本身错了，再跑还是错）：failed 终态
            job.status = FAILED
            job.finished_at = now
        guarded: Mapping[str, Any] = {"status": RUNNING, "attempts": attempts}
        return job if self.store.write(job, guarded) else None

    def reclaim_expired(self) -> int:
        """把租约过期（worker 失联）的任务按「这次尝试失败」处理，返回回收条数。

        直接复用 fail 的重试策略：次数没用完就排队重试，用完了进死信——
        回收与失败必须走同一套规则，否则两条路径的重试节奏会漂移。
        """
        now = as_utc(self._clock())
        reclaimed = 0
        for job in self.store.list(RUNNING):
            if job.lease_until is not None and as_utc(job.lease_until) > now:
                continue
            reason = f"租约过期：worker {job.worker_id or '-'} 未续租"
            if self.fail(job.id, reason, retryable=True, worker_id=job.worker_id) is not None:
                reclaimed += 1
        return reclaimed

    def cancel(self, job_id: str) -> Job | None:
        job = self.store.get(job_id)
        if job is None or job.status not in (QUEUED, RUNNING):
            return None
        previous = job.status
        now = as_utc(self._clock())
        job.status = CANCELLED
        job.finished_at = now
        job.lease_until = None
        job.worker_id = None
        return job if self.store.write(job, {"status": previous}) else None
