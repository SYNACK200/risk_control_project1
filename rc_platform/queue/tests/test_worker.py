"""worker 与并发演示：证明领到的都做完、一个不做两次。"""
from __future__ import annotations

import threading
import time
from datetime import timedelta

from rc_platform.core.events import ProgressEvent
from rc_platform.queue import run_loop, run_once
from rc_platform.queue.models import DONE, QUEUED


def handler_ok(job, emit):
    emit(ProgressEvent(job.id, "parse.layout", 1, 2, "start"))
    emit(ProgressEvent(job.id, "parse.layout", 2, 2, "ok"))


def test_run_once_marks_done(service):
    job = service.enqueue({"n": 1})
    assert run_once(service, "w1", handler_ok) is True
    stored = service.get(job.id)
    assert stored.status == DONE
    assert stored.stage == "parse.layout"
    assert stored.progress == 1.0
    assert stored.worker_id == "w1"


def test_run_once_returns_false_on_empty_queue(service):
    assert run_once(service, "w1", handler_ok) is False


def test_run_once_requeues_on_error(service, clock):
    job = service.enqueue({})

    def boom(job, emit):
        raise RuntimeError("解析失败")

    assert run_once(service, "w1", boom) is True
    stored = service.get(job.id)
    assert stored.status == QUEUED
    assert stored.attempts == 1
    assert "RuntimeError: 解析失败" in stored.error
    assert stored.next_run_at == clock.now + timedelta(seconds=2)


def test_run_loop_drains_queue(service):
    for index in range(5):
        service.enqueue({"n": index})
    processed = run_loop(service, "w1", handler_ok, idle_limit=2, idle_sleep=0.0)
    assert processed == 5
    assert service.stats()[DONE] == 5


def test_50_concurrent_demo(service):
    """50 个任务 + 8 个 worker 线程：0 丢失、0 重复执行。"""
    total, workers = 50, 8
    for index in range(total):
        service.enqueue({"n": index}, priority=index % 3)

    executed: list[str] = []
    guard = threading.Lock()

    def handler(job, emit):
        emit(ProgressEvent(job.id, "parse.layout", 1, 1, "ok"))
        time.sleep(0.001)  # 制造一点点真实工作量，让领取与完成交错
        with guard:
            executed.append(job.id)

    started = time.perf_counter()
    threads = [
        threading.Thread(
            target=run_loop,
            args=(service, f"w{index}", handler),
            kwargs={"idle_limit": 5, "idle_sleep": 0.005},
        )
        for index in range(workers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    elapsed_ms = (time.perf_counter() - started) * 1000

    stats = service.stats()
    duplicates = len(executed) - len(set(executed))
    print(
        f"\n[50 并发演示] 入队 {total} / 执行 {len(executed)} / 去重后 {len(set(executed))} / "
        f"完成 {stats[DONE]} / 重复 {duplicates} / 耗时 {elapsed_ms:.0f}ms"
    )

    assert len(executed) == total
    assert duplicates == 0
    assert stats[DONE] == total
    assert stats[QUEUED] == 0 and stats["running"] == 0
