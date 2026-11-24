"""任务队列观测与控制接口（B2 + F7）：查看排队位次、当前阶段、失败重试与取消。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import AuditLog, Task, User
from db.session import get_session
from helpers.security import current_user, require_banker
from services import worker
from services.workflow import InvalidTransition, transition

router = APIRouter(prefix="/queue", tags=["queue"], dependencies=[Depends(require_banker)])

_ACTIVE_STATUSES = ("QUEUED", "CHECKING", "PARSING", "VERIFYING", "REPORTING")


@router.get("/stats")
def queue_stats(db: Session = Depends(get_session)):
    """返回任务队列实时统计与进程池占用情况。"""
    rows = db.execute(
        select(Task.status, func.count(Task.id))
        .where(Task.deleted_at.is_(None))
        .group_by(Task.status)
    ).all()
    counts = {str(st): int(cnt) for st, cnt in rows}
    queued = counts.get("QUEUED", 0)
    running = sum(counts.get(st, 0) for st in ("CHECKING", "PARSING", "VERIFYING", "REPORTING"))
    failed = counts.get("FAILED", 0)
    done = counts.get("DONE", 0)
    return {
        "queued": queued,
        "running": running,
        "failed": failed,
        "done": done,
        "need_supplement": counts.get("NEED_SUPPLEMENT", 0),
        "active_workers": worker.active_count(),
        "max_workers": worker.worker_count(),
        "last_finished_at": worker.last_finished_at(),
    }


@router.get("/jobs")
def list_queue_jobs(
    include_failed: bool = True,
    limit: int = 100,
    db: Session = Depends(get_session),
):
    """列出当前排队、处理中及失败的任务，并计算排队位次。"""
    wanted = list(_ACTIVE_STATUSES) + (["FAILED"] if include_failed else [])
    rows = db.execute(
        select(Task)
        .where(Task.deleted_at.is_(None), Task.status.in_(wanted))
        .order_by(Task.id.asc())
        .limit(min(max(1, limit), 300))
    ).scalars().all()

    queue_pos = 0
    items: list[dict] = []
    for t in rows:
        pos = None
        if t.status == "QUEUED":
            queue_pos += 1
            pos = queue_pos
        items.append({
            "task_id": t.id,
            "biz_no": t.biz_no,
            "status": t.status,
            "queue_position": pos,
            "carrier": t.carrier,
            "failure_code": t.failure_code,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })
    return {"items": items, "total": len(items)}


@router.post("/jobs/{task_id}/retry")
def retry_queue_job(
    task_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """重试失败或已取消的任务。"""
    task = db.get(Task, task_id)
    if task is None or task.deleted_at is not None:
        raise HTTPException(404, detail={"code": "E_NOT_FOUND", "message": "任务不存在"})
    if task.status != "FAILED":
        raise HTTPException(409, detail={"code": "E_STATE", "message": f"当前状态 {task.status} 不可重试"})
    try:
        transition(task, "QUEUED")
    except InvalidTransition as exc:
        raise HTTPException(400, detail={"code": "E_STATE", "message": str(exc)}) from exc
    task.failure_code = None
    db.add(AuditLog(
        actor_id=user.id, action="queue.retry", object_type="task", object_id=task.id,
        detail="从队列页手动重试",
    ))
    db.commit()
    mode = worker.submit_task(task.id)
    return {"task_id": task.id, "status": task.status, "mode": mode}


@router.post("/jobs/{task_id}/cancel")
def cancel_queue_job(
    task_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """取消仍在排队中的任务。"""
    task = db.get(Task, task_id)
    if task is None or task.deleted_at is not None:
        raise HTTPException(404, detail={"code": "E_NOT_FOUND", "message": "任务不存在"})
    if task.status != "QUEUED":
        raise HTTPException(409, detail={"code": "E_STATE", "message": "仅排队中的任务允许取消"})
    try:
        transition(task, "FAILED")
    except InvalidTransition as exc:
        raise HTTPException(400, detail={"code": "E_STATE", "message": str(exc)}) from exc
    task.failure_code = "E_CANCELLED"
    db.add(AuditLog(
        actor_id=user.id, action="queue.cancel", object_type="task", object_id=task.id,
        detail="从队列页手动取消",
    ))
    db.commit()
    return {"task_id": task.id, "status": task.status, "cancelled": True}
