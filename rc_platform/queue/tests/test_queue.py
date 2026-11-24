"""队列行为自测：每个用例都在 MemoryStore 与 SqlAlchemyStore 上各跑一次。

参数化是本文件的核心手段——换存储不改行为，靠同一套断言压两遍来证明。
"""
from __future__ import annotations

import threading
from datetime import timedelta

import pytest

from rc_platform.core.events import ProgressEvent
from rc_platform.queue import QueueService
from rc_platform.queue.models import CANCELLED, DEAD, DONE, FAILED, QUEUED, RUNNING, STATUSES

from .conftest import Clock


# ---- 入队 ----

def test_enqueue_defaults(service, clock):
    job = service.enqueue({"biz_no": "B1"}, biz_no="B1")
    assert len(job.id) == 32
    assert job.status == QUEUED
    assert (job.priority, job.attempts, job.max_attempts) == (0, 0, 3)
    assert job.payload == {"biz_no": "B1"}
    assert job.enqueued_at == clock.now
    assert job.next_run_at == clock.now
    assert job.seq >= 1
    assert service.get(job.id).status == QUEUED


def test_enqueue_rejects_zero_attempts(service):
    with pytest.raises(ValueError):
        service.enqueue({}, max_attempts=0)


# ---- 领取顺序 ----

def test_priority_then_fifo(service):
    service.enqueue({"n": "low"}, priority=0)
    service.enqueue({"n": "high"}, priority=9)
    service.enqueue({"n": "mid_a"}, priority=5)
    service.enqueue({"n": "mid_b"}, priority=5)
    order = [service.claim("w1").payload["n"] for _ in range(4)]
    assert order == ["high", "mid_a", "mid_b", "low"]
    assert service.claim("w1") is None


def test_claim_sets_running_and_lease(service, clock):
    job = service.enqueue({"x": 1})
    got = service.claim("w1", lease_seconds=30)
    assert got.id == job.id
    assert got.status == RUNNING
    assert got.attempts == 1
    assert got.worker_id == "w1"
    assert got.started_at == clock.now
    assert got.lease_until == clock.now + timedelta(seconds=30)


def test_claim_respects_next_run_at(service, clock):
    job = service.enqueue({})
    service.claim("w1")
    failed = service.fail(job.id, "boom")
    assert failed.status == QUEUED
    assert failed.next_run_at == clock.now + timedelta(seconds=2)
    assert service.claim("w1") is None, "退避未到点不该被领走"
    clock.advance(2)
    again = service.claim("w1")
    assert again.id == job.id and again.attempts == 2


# ---- 心跳 ----

def test_heartbeat_renews_lease(service, clock):
    job = service.enqueue({})
    service.claim("w1", lease_seconds=30)
    clock.advance(20)
    renewed = service.heartbeat(job.id, "w1", lease_seconds=30)
    assert renewed.heartbeat_at == clock.now
    assert renewed.lease_until == clock.now + timedelta(seconds=30)
    assert service.get(job.id).lease_until == renewed.lease_until


def test_heartbeat_rejects_other_worker(service, clock):
    job = service.enqueue({})
    service.claim("w1")
    clock.advance(1)
    assert service.heartbeat(job.id, "w2") is None


# ---- 收尾 ----

def test_complete_moves_to_done(service, clock):
    job = service.enqueue({})
    service.claim("w1")
    done = service.complete(job.id, worker_id="w1")
    assert done.status == DONE
    assert done.finished_at == clock.now
    assert done.progress == 1.0
    assert done.lease_until is None


def test_cancel_beats_late_complete(service):
    job = service.enqueue({})
    service.claim("w1")
    assert service.cancel(job.id).status == CANCELLED
    assert service.complete(job.id, worker_id="w1") is None
    assert service.heartbeat(job.id, "w1") is None
    assert service.get(job.id).status == CANCELLED


def test_cancel_queued_and_idempotent(service, clock):
    job = service.enqueue({})
    cancelled = service.cancel(job.id)
    assert cancelled.status == CANCELLED
    assert cancelled.finished_at == clock.now
    assert service.cancel(job.id) is None
    assert service.claim("w1") is None


# ---- 重试 ----

def test_fail_backoff_is_exponential(service, clock):
    job = service.enqueue({}, max_attempts=5)
    delays = []
    for _ in range(3):
        service.claim("w1")
        before = clock.now
        failed = service.fail(job.id, "再试")
        assert failed.status == QUEUED
        delays.append((failed.next_run_at - before).total_seconds())
        clock.advance(delays[-1])
    assert delays == [2.0, 4.0, 8.0]
    assert service.get(job.id).attempts == 3


def test_fail_exhausted_lands_in_dead(service, clock):
    job = service.enqueue({}, max_attempts=2)
    service.claim("w1")
    service.fail(job.id, "第一次")
    clock.advance(2)
    service.claim("w1")
    dead = service.fail(job.id, "第二次")
    assert dead.status == DEAD
    assert dead.error == "第二次"
    assert dead.attempts == 2
    assert dead.finished_at == clock.now
    assert service.claim("w1") is None


def test_fail_not_retryable_is_failed(service):
    job = service.enqueue({})
    service.claim("w1")
    failed = service.fail(job.id, "数据格式不对", retryable=False)
    assert failed.status == FAILED
    assert failed.error == "数据格式不对"
    assert service.claim("w1") is None


# ---- 名次与统计 ----

def test_position_follows_claim_order(service):
    a = service.enqueue({}, priority=1)
    b = service.enqueue({}, priority=5)
    c = service.enqueue({}, priority=3)
    assert [service.position(x.id) for x in (a, b, c)] == [3, 1, 2]
    service.claim("w1")
    assert service.position(b.id) is None, "领取之后不再占名次"
    assert service.position(a.id) == 2


def test_stats_counts_workers_and_wait(service, clock):
    first = service.enqueue({})
    service.enqueue({})
    service.enqueue({})
    clock.advance(3)
    service.claim("w1")
    service.claim("w2")
    stats = service.stats()
    assert stats["total"] == 3
    assert stats[QUEUED] == 1 and stats[RUNNING] == 2
    assert stats["running_workers"] == 2
    assert stats["oldest_enqueued_at"] == first.enqueued_at.isoformat()
    assert stats["avg_wait_seconds"] == 3.0
    service.complete(first.id)
    assert service.stats()[DONE] == 1


def test_stats_exposes_every_status(service):
    stats = service.stats()
    assert set(STATUSES) <= set(stats)
    assert stats["total"] == 0
    assert stats["oldest_enqueued_at"] is None
    assert stats["avg_wait_seconds"] == 0.0


# ---- 租约回收 ----

def test_reclaim_requeues_expired_lease(service, clock):
    job = service.enqueue({})
    service.claim("w1", lease_seconds=30)
    assert service.reclaim_expired() == 0, "租约还活着不能回收"
    clock.advance(31)
    assert service.reclaim_expired() == 1
    reloaded = service.get(job.id)
    assert reloaded.status == QUEUED
    assert "租约过期" in reloaded.error
    assert reloaded.next_run_at == clock.now + timedelta(seconds=2)
    assert service.claim("w1") is None
    clock.advance(2)
    assert service.claim("w2").attempts == 2


def test_reclaim_exhausted_goes_dead(service, clock):
    job = service.enqueue({}, max_attempts=1)
    service.claim("w1", lease_seconds=10)
    clock.advance(11)
    assert service.reclaim_expired() == 1
    assert service.get(job.id).status == DEAD


# ---- 进度 ----

def test_progress_from_event(service, store):
    job = service.enqueue({})
    service.claim("w1")
    updated = service.record_progress(job.id, ProgressEvent(job.id, "parse.layout_v2", 3, 7, "start"))
    assert updated.stage == "parse.layout_v2"
    assert updated.progress == pytest.approx(3 / 7, rel=1e-6)
    stored = store.get(job.id)
    assert stored.stage == "parse.layout_v2"
    assert stored.progress == pytest.approx(3 / 7, rel=1e-6)


def test_progress_ignored_outside_running(service):
    job = service.enqueue({})
    assert service.record_progress(job.id, ProgressEvent(job.id, "parse", 1, 2, "start")) is None


# ---- 存储原语 ----

def test_write_refuses_stale_expectation(service, store):
    job = service.enqueue({})
    stale = store.get(job.id)
    assert store.write(stale, {"status": RUNNING}) is False
    stale.status = DONE
    assert store.write(stale, {"status": QUEUED}) is True
    assert store.get(job.id).status == DONE


def test_claim_is_atomic_across_threads(store):
    """8 个线程抢 40 个任务：每个任务只能被领到一次。"""
    service = QueueService(store)
    total, workers = 40, 8
    for index in range(total):
        service.enqueue({"n": index})
    claimed: list[str] = []
    guard = threading.Lock()
    barrier = threading.Barrier(workers)

    def work(worker_id: str) -> None:
        barrier.wait()
        while True:
            job = service.claim(worker_id, lease_seconds=60)
            if job is None:
                return
            with guard:
                claimed.append(job.id)

    threads = [threading.Thread(target=work, args=(f"w{i}",)) for i in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert len(claimed) == total
    assert len(set(claimed)) == total
    assert service.stats()[RUNNING] == total


# ---- 两套实现的一致性 ----

def test_memory_and_sqlalchemy_agree():
    """同一串操作跑两遍，除随机 id 外所有可观察字段必须逐字相同。"""

    def snapshot(store) -> dict:
        clock = Clock()
        service = QueueService(store, clock=clock)
        j1 = service.enqueue({"n": 1}, priority=1)
        j2 = service.enqueue({"n": 2}, priority=9)
        j3 = service.enqueue({"n": 3}, biz_no="B3", max_attempts=1)
        claimed = service.claim("wA", lease_seconds=30)
        service.record_progress(claimed.id, ProgressEvent(claimed.id, "parse.layout", 2, 5, "start"))
        service.heartbeat(claimed.id, "wA", lease_seconds=30)
        service.fail(claimed.id, "boom")
        clock.advance(4)
        second = service.claim("wB")
        service.complete(second.id, worker_id="wB")
        third = service.claim("wC")
        service.cancel(third.id)
        clock.advance(60)
        reclaimed = service.reclaim_expired()
        jobs = []
        for job in store.list():
            payload = job.to_dict()
            payload.pop("id")
            jobs.append(payload)
        positions = [service.position(j.id) for j in (j1, j2, j3)]
        return {"jobs": jobs, "positions": positions, "reclaimed": reclaimed, "stats": service.stats()}

    from rc_platform.queue import MemoryStore, SqlAlchemyStore

    memory = snapshot(MemoryStore())
    sql = snapshot(SqlAlchemyStore("sqlite:///:memory:"))
    assert memory == sql
