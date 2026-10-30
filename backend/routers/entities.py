"""实体与合并接口：账户/户名识别、冲突告警、多账户合并。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.session import get_session
from services.entities import METHODS, OVERLAP_MODES, collect_entities, merge_subject

router = APIRouter(prefix="/entities", tags=["entities"])


@router.get("")
def get_entities(db: Session = Depends(get_session)):
    """账户、户名、以及「一个账户多个户名」的冲突告警。"""
    return collect_entities(db)


@router.get("/methods")
def get_methods():
    """合并方式与重叠算法的说明（前端只渲染，不重复定义）。"""
    return {"methods": METHODS, "overlap_modes": OVERLAP_MODES}


@router.get("/merge")
def get_merge(
    subject: str,
    method: str = "union",
    overlap: str = "max",
    db: Session = Depends(get_session),
):
    try:
        return merge_subject(db, subject, method, overlap)
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "E_STATE", "message": str(exc)}) from exc
