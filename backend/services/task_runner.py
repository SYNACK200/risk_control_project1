"""任务分析执行器：在任意进程内把一次「解析 + 核验 + 指标 + 报告 + 落库」跑完。

设计要点
- 自身不带全局状态：子进程里调用时会先 init_db() 建自己的连接池；
- 失败一律把任务置 FAILED 并写审计，不静默；
- 与 routers/tasks.py 解耦，便于放到进程池里跑（绕过 GIL）。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path


def _commit_with_retry(session, attempts: int = 3) -> None:
    """并发写 metric_value 可能触发 1213 死锁，退避重试。"""
    import time as _time

    from sqlalchemy.exc import OperationalError as _OpErr

    for i in range(attempts):
        try:
            session.commit()
            return
        except _OpErr as exc:
            if i == attempts - 1 or "1213" not in str(exc) and "Deadlock" not in str(exc):
                raise
            session.rollback()
            _time.sleep(0.05 * (i + 1))


def warmup() -> str:
    """进程预热：让子进程提前加载算法与数据库依赖，避免首个任务慢 1s+。"""
    from algorithm.algo.preread import run_preread  # noqa: F401
    from services.analysis import run_analysis  # noqa: F401
    from db import session as db_session

    db_session.init_db()
    return "ok"


def run_task(task_id: int, password: str | None = None) -> dict:
    """执行一次任务分析；返回 {"task_id", "status", "txn_count"}。异常时任务置 FAILED 后重新抛出。"""
    from db import session as db_session

    db_session.init_db()
    assert db_session.SessionLocal is not None
    session = db_session.SessionLocal()

    from db.models import (  # noqa: PLC0415
        AuditLog, FileObj, MetricValue, Report, Task, Template, Txn,
    )
    from algorithm.algo.preread import run_preread
    from services.analysis import run_analysis
    from services.workflow import transition
    from services import thresholds as threshold_service

    try:
        from sqlalchemy import text as _sql

        # 降低并发插入 metric_value 时的间隙锁冲突
        session.execute(_sql("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED"))
    except Exception:  # noqa: BLE001
        pass

    task = session.get(Task, task_id)
    if task is None:
        session.close()
        return {"task_id": task_id, "status": "MISSING", "txn_count": 0}
    try:
        file_row = session.get(FileObj, task.file_id) if task.file_id else None
        if file_row is None or not file_row.storage_path:
            raise RuntimeError("任务没有可用的原始文件")
        path = Path(file_row.storage_path)
        if not path.exists():
            raise RuntimeError("原始文件已被清理，无法分析")
        data = path.read_bytes()

        template = None
        template_row = None
        if task.template_id:
            template_row = session.get(Template, task.template_id)
            if template_row is not None and template_row.deleted_at is None:
                template = {"bank_code": template_row.bank_code,
                            "version": template_row.version,
                            "field_map": template_row.field_map}

        transition(task, "CHECKING")
        transition(task, "PARSING")
        session.commit()

        preread = run_preread(data, password=password)
        result = run_analysis(
            data, password=password, template=template, preread=preread,
            thresholds=threshold_service.build_config(session),
        )

        file_row.carrier = result["carrier"]
        file_row.pages = result["pages"]
        file_row.has_text_layer = result["has_text_layer"]
        if not file_row.storage_path:
            file_row.storage_path = str(path)

        task.carrier = result["carrier"]
        task.check_result = {
            **(task.check_result or {}),
            "warnings": result["warnings"],
            "self_check": result.get("self_check"),
            "preread": result.get("preread"),
        }
        task.finished_at = datetime.now()

        transition(task, "VERIFYING")
        transition(task, "REPORTING")

        session.query(Txn).filter(Txn.task_id == task.id).delete()
        session.query(MetricValue).filter(MetricValue.task_id == task.id).delete()
        session.query(Report).filter(Report.task_id == task.id).delete()

        for t in result["transactions"]:
            session.add(Txn(
                task_id=task.id, txn_date=t["txn_date"], direction=t["direction"],
                amount=None if t["amount"] is None else Decimal(t["amount"]),
                balance=None if t["balance"] is None else Decimal(t["balance"]),
                summary=t["summary"], counterparty_name=t["counterparty_name"],
                page_no=t["page_no"],
                confidence=None if t["confidence"] is None else Decimal(t["confidence"]),
            ))
        for m in result["metrics"]:
            session.add(MetricValue(
                task_id=task.id, metric_code=m["code"], metric_name=m["name"],
                value_num=None if m["value"] is None else Decimal(m["value"]),
                unit=m["unit"], note=m["note"], caliber_version=m["caliber_version"],
            ))
        report_row = result["report"]
        session.query(Report).filter(Report.task_id == task.id).delete()
        session.add(Report(
            task_id=task.id, version=1, carrier=report_row["carrier"],
            verdict=report_row["verdict"], verdict_reason=report_row["verdict_reason"],
            layers=report_row["layers"], limitations=report_row["limitations"],
            evidence=report_row["evidence"], materials=report_row["materials"],
            metric_set_version=report_row["metric_set_version"],
            threshold_version=report_row["threshold_version"], payload=report_row,
        ))
        transition(task, "DONE")
        session.add(AuditLog(action="analyze_done", object_type="task", object_id=task.id,
                             detail=f"txn={result['txn_count']}"))
        _commit_with_retry(session)
        return {"task_id": task.id, "status": task.status, "txn_count": result["txn_count"]}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        try:
            task = session.get(Task, task_id)
            if task is not None:
                target = "FAILED"
                if str(getattr(task, "status")) in ("QUEUED", "CHECKING", "PARSING",
                                                    "VERIFYING", "REPORTING", "NEED_SUPPLEMENT"):
                    try:
                        transition(task, target)
                    except Exception:  # noqa: BLE001
                        task.status = target
                session.add(AuditLog(action="analyze_failed", object_type="task",
                                     object_id=task_id, detail=str(exc)[:200]))
                session.commit()
        except Exception:  # noqa: BLE001
            session.rollback()
        raise
    finally:
        session.close()
