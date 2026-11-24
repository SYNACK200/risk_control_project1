"""慢通道调度：系统空闲时用另一个引擎复核已出报告。

见 docs/快慢双通道解析设计.md。

为什么不放进 worker 的进程池：复核是「有就做、没有就算」的活，
和用户上传的分析任务抢进程会拖慢感知响应。这里用独立线程串行跑，
并且只在快通道队列为空时才动手。
"""
from __future__ import annotations

import threading
import time

from sqlalchemy import func, select

from db.models import Report, Task
from logging import getLogger

log = getLogger(__name__)

_IDLE_SECONDS = 5.0     # 快通道安静这么久才允许复核
_POLL_SECONDS = 20.0    # 多久看一次有没有待复核
_stop = threading.Event()
_thread: threading.Thread | None = None


def _fast_busy() -> bool:
    """快通道是否还有活。有就跳过这一轮，不抢资源。

    之前读的是 worker._PENDING，那个变量根本不存在，导致这里永远返回 False——
    慢通道会一直和用户上传的任务抢资源。现在读真实的在跑计数。
    """
    try:
        from services import worker  # noqa: PLC0415

        return int(worker.active_count()) > 0
    except Exception:  # noqa: BLE001
        return False

def _fast_last_finished() -> float:
    try:
        from services import worker  # noqa: PLC0415

        return float(worker.last_finished_at())
    except Exception:  # noqa: BLE001
        return 0.0


def _pick_one() -> int | None:
    """取一个待复核的任务。直接按 status='pending' 过滤，避免超过 50 条历史报告后永久卡死。"""
    from db.session import SessionLocal  # noqa: PLC0415

    if SessionLocal is None:
        return None
    with SessionLocal() as db:
        # 优先在数据库层用 JSON_EXTRACT 精确过滤 pending，避免全表拉取
        candidates = None
        try:
            status_expr = func.json_unquote(func.json_extract(Report.verification, "$.status"))
            candidates = db.execute(
                select(Report)
                .where(Report.verification.isnot(None), status_expr == "pending")
                .order_by(Report.id.asc())
                .limit(50)
            ).scalars().all()
        except Exception:  # noqa: BLE001 - 非 MySQL 或方言不支持时回退游标分页扫描
            candidates = None

        if candidates is not None:
            for rep in candidates:
                if (rep.carrier or "").lower() not in ("", "electronic", "image"):
                    continue
                task = db.get(Task, rep.task_id)
                if task is None or task.deleted_at is not None:
                    continue
                return rep.task_id
            return None

        # 回退游标分页扫描：每次最多扫 100 条，确保历史报告 >50 条时新报告依然能被扫到
        last_id = 0
        while True:
            rows = db.execute(
                select(Report)
                .where(Report.verification.isnot(None), Report.id > last_id)
                .order_by(Report.id.asc())
                .limit(100)
            ).scalars().all()
            if not rows:
                break
            last_id = rows[-1].id
            for rep in rows:
                v = rep.verification or {}
                if v.get("status") != "pending":
                    continue
                if (rep.carrier or "").lower() not in ("", "electronic", "image"):
                    continue
                task = db.get(Task, rep.task_id)
                if task is None or task.deleted_at is not None:
                    continue
                return rep.task_id
    return None


def _loop() -> None:
    from services.verify import verify_task  # noqa: PLC0415

    last_fast = time.time()
    while not _stop.is_set():
        try:
            now_ts = time.time()
            if _fast_busy():
                last_fast = now_ts
            else:
                # 同步读取快通道真实结束时间戳，防止 20s 轮询间隔内跑完的任务绕过 5s 空闲约束
                last_fast = max(last_fast, _fast_last_finished())
                if now_ts - last_fast >= _IDLE_SECONDS:
                    tid = _pick_one()
                    if tid is not None:
                        log.info("慢通道复核 task=%s", tid)
                        verify_task(tid)
                        continue
        except Exception as exc:  # noqa: BLE001
            log.warning("慢通道异常：%s", exc)
        _stop.wait(_POLL_SECONDS)


def start() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="slow-verify", daemon=True)
    _thread.start()
    log.info("慢通道已启动")


def stop() -> None:
    _stop.set()