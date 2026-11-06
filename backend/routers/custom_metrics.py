"""自定义指标口径（实验性）：管理员登记业务想看的维度，暂不参与自动计算。

为什么要它：业务提新维度（如"夜间小额高频占比"）时，先把它作为口径登记下来，
在看板与口径页可见、可讨论；等口径稳定后再进算法实现，避免只存在于口头或聊天记录。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import AuditLog, CustomMetric
from db.session import get_session
from helpers.security import require_admin, require_banker

router = APIRouter(prefix="/custom-metrics", tags=["custom-metrics"])


class CustomMetricIn(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    unit: str | None = Field(default=None, max_length=16)
    group_name: str | None = Field(default=None, max_length=32)
    formula: str | None = Field(default=None, max_length=255)
    inputs: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=255)


def _row(m: CustomMetric) -> dict:
    return {
        "id": m.id, "code": m.code, "name": m.name, "unit": m.unit,
        "group_name": m.group_name, "formula": m.formula, "inputs": m.inputs,
        "note": m.note, "enabled": bool(m.enabled),
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.get("", dependencies=[Depends(require_banker)])
def list_custom_metrics(db: Session = Depends(get_session)):
    rows = db.execute(select(CustomMetric).order_by(CustomMetric.id.desc())).scalars().all()
    return {"items": [_row(m) for m in rows], "note": "实验性：仅登记口径，暂不参与自动计算"}


@router.post("", dependencies=[Depends(require_admin)])
def create_custom_metric(payload: CustomMetricIn, db: Session = Depends(get_session)):
    code = payload.code.strip().upper()
    exists = db.execute(select(CustomMetric).where(CustomMetric.code == code)).scalars().first()
    if exists is not None:
        raise HTTPException(409, detail={"code": "E_EXISTS", "message": f"指标编码 {code} 已存在"})
    row = CustomMetric(code=code, name=payload.name.strip(), unit=payload.unit,
                       group_name=payload.group_name, formula=payload.formula,
                       inputs=payload.inputs, note=payload.note)
    db.add(row)
    db.add(AuditLog(action="add_metric", object_type="custom_metric", object_id=0,
                    detail=f"{code} {payload.name.strip()}"[:180]))
    db.commit()
    db.refresh(row)
    return _row(row)


@router.delete("/{metric_id}", dependencies=[Depends(require_admin)])
def delete_custom_metric(metric_id: int, db: Session = Depends(get_session)):
    row = db.get(CustomMetric, metric_id)
    if row is None:
        raise HTTPException(404, detail={"code": "E_NOT_FOUND", "message": "指标不存在"})
    db.add(AuditLog(action="remove_metric", object_type="custom_metric", object_id=row.id,
                    detail=f"{row.code} {row.name}"[:180]))
    db.delete(row)
    db.commit()
    return {"ok": True}