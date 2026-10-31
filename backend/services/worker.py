"""后台分析进程池：把「解析 + 核验 + 指标 + 报告」移出请求线程。

- ANALYSIS_BACKEND=process（默认）：ProcessPoolExecutor，绕过 GIL，真并行；
- ANALYSIS_BACKEND=inline：当前线程同步执行，供测试与调试；
- ANALYSIS_WORKERS：进程数，默认 2，建议 ≤ CPU 核数。
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import os
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

logger = logging.getLogger("risk_control.worker")

_executor: ProcessPoolExecutor | None = None


def backend_name() -> str:
    return os.getenv("ANALYSIS_BACKEND", "process").strip().lower()


def worker_count() -> int:
    try:
        return max(1, int(os.getenv("ANALYSIS_WORKERS", "2")))
    except ValueError:
        return 2


def _get_executor() -> ProcessPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ProcessPoolExecutor(
            max_workers=worker_count(),
            mp_context=mp.get_context("spawn"),
        )
        logger.info("分析进程池已启动：%d 个进程", worker_count())
    return _executor


def _mark_failed(task_id: int, reason: str) -> None:
    """子进程异常/崩溃时由父进程兜底置 FAILED。"""
    try:
        from db import session as db_session

        db_session.init_db()
        assert db_session.SessionLocal is not None
        with db_session.SessionLocal() as session:
            from db.models import AuditLog, Task  # noqa: PLC0415

            task = session.get(Task, task_id)
            if task is None or task.status in ("DONE", "FAILED"):
                return
            task.status = "FAILED"
            session.add(AuditLog(action="analyze_failed", object_type="task",
                                 object_id=task_id, detail=reason[:200]))
            session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("兜底置 FAILED 也失败了：task=%s", task_id)


def _on_done(task_id: int, future) -> None:
    try:
        future.result()
    except BrokenProcessPool:
        logger.exception("分析进程池已损坏：task=%s", task_id)
        _mark_failed(task_id, "分析进程异常退出（进程池损坏）")
    except Exception as exc:  # noqa: BLE001
        logger.warning("分析失败：task=%s %s", task_id, exc)
        _mark_failed(task_id, f"分析失败：{exc}")


def submit_task(task_id: int, password: str | None = None) -> str:
    """提交一次任务分析，返回执行方式（inline / queued）。"""
    from services.task_runner import run_task

    if backend_name() == "inline":
        run_task(task_id, password=password)
        return "inline"

    future = _get_executor().submit(run_task, task_id, password)
    future.add_done_callback(lambda f, tid=task_id: _on_done(tid, f))
    return "queued"


def warmup() -> None:
    """启动时提前拉起子进程并预热依赖（不阻塞太久）。"""
    if backend_name() != "process":
        return
    try:
        from services.task_runner import warmup as _warm

        # 只负责把子进程拉起来，不阻塞启动（首个任务仍可能略慢）
        for _ in range(worker_count()):
            _get_executor().submit(_warm)
        logger.info("已向进程池投递预热任务")
    except Exception:  # noqa: BLE001
        logger.warning("进程池预热未完成，首个任务会稍慢")


def shutdown() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None
