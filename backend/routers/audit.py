"""审计日志查询：审计记录只读且不提供修改、删除接口。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import AuditLog
from db.session import get_session
from helpers.security import require_local_access

router = APIRouter(prefix="/audit", tags=["audit"], dependencies=[Depends(require_local_access)])


def _parse_time(value: str | None, name: str) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "E_FORMAT", "message": f"{name} 必须是 ISO-8601 时间"}) from exc


@router.get("")
def list_audit_logs(
    object_type: str | None = None,
    object_id: int | None = None,
    actor_id: int | None = None,
    action: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_session),
):
    """按对象、操作人、动作和时间分页检索；不返回任何口令字段。"""
    start = _parse_time(created_from, "created_from")
    end = _parse_time(created_to, "created_to")
    if start and end and start > end:
        raise HTTPException(400, detail={"code": "E_FORMAT", "message": "created_from 不得晚于 created_to"})

    statement = select(AuditLog)
    if object_type:
        statement = statement.where(AuditLog.object_type == object_type)
    if object_id is not None:
        statement = statement.where(AuditLog.object_id == object_id)
    if actor_id is not None:
        statement = statement.where(AuditLog.actor_id == actor_id)
    if action:
        statement = statement.where(AuditLog.action == action)
    if start:
        statement = statement.where(AuditLog.created_at >= start)
    if end:
        statement = statement.where(AuditLog.created_at <= end)

    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = db.execute(
        statement.order_by(AuditLog.id.desc()).offset((page - 1) * size).limit(size)
    ).scalars().all()
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            {
                "id": row.id,
                "actor_id": row.actor_id,
                "action": row.action,
                "object_type": row.object_type,
                "object_id": row.object_id,
                "detail": row.detail,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }
