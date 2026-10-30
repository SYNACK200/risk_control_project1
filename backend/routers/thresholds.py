"""阈值（超参）配置接口：银行可改，改后新版本生效，旧报告不重写。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.models import AuditLog
from db.session import get_session
from helpers.security import require_local_access
from services import thresholds as svc

router = APIRouter(prefix="/thresholds", tags=["thresholds"], dependencies=[Depends(require_local_access)])


class ThresholdPayload(BaseModel):
    values: dict
    note: str | None = None


@router.get("")
def get_thresholds(db: Session = Depends(get_session)):
    version, values = svc.active_version(db)
    return {
        "version": version,
        "values": values,
        "defaults": svc.default_values(),
        "defs": svc.definitions(),
        "history": svc.history(db),
    }


@router.put("")
def put_thresholds(payload: ThresholdPayload, db: Session = Depends(get_session)):
    try:
        row = svc.save_version(db, payload.values, payload.note)
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "E_PARAM", "message": str(exc)}) from exc
    db.add(AuditLog(action="save_thresholds", object_type="threshold", object_id=row.version,
                    detail=(payload.note or "更新阈值")[:180]))
    db.commit()
    version, values = svc.active_version(db)
    return {"version": version, "values": values, "saved_version": row.version}


@router.post("/reset")
def reset_thresholds(db: Session = Depends(get_session)):
    row = svc.save_version(db, svc.default_values(), "恢复算法默认值")
    db.add(AuditLog(action="reset_thresholds", object_type="threshold", object_id=row.version,
                    detail="恢复默认阈值"))
    db.commit()
    version, values = svc.active_version(db)
    return {"version": version, "values": values, "saved_version": row.version}
