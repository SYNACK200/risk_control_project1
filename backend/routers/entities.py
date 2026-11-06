"""实体与合并接口：账户/户名识别、冲突告警、多账户合并。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import AuditLog, SubjectDecision
from db.session import get_session
from helpers.security import current_user, require_banker
from services.entities import METHODS, OVERLAP_MODES, collect_entities, merge_subject


class ResolveConflictIn(BaseModel):
    account_key: str = Field(min_length=1, max_length=128)
    subject: str = Field(min_length=1, max_length=128)
    note: str | None = Field(default=None, max_length=255)

router = APIRouter(prefix="/entities", tags=["entities"], dependencies=[Depends(require_banker)])


@router.get("")
def get_entities(db: Session = Depends(get_session)):
    """账户、户名、以及「一个账户多个户名」的冲突告警。"""
    return collect_entities(db)


@router.post("/conflicts/resolve")
def resolve_conflict(payload: ResolveConflictIn, db: Session = Depends(get_session),
                     user=Depends(current_user)):
    """人工确认「这个账号实际属于哪个户名」。

    冲突只展示没用，必须有人签字；判定要能追溯到人和时间，所以写 subject_decision 并留审计。
    """
    row = db.execute(
        select(SubjectDecision).where(SubjectDecision.account_key == payload.account_key)
    ).scalars().first()
    if row is None:
        row = SubjectDecision(account_key=payload.account_key, subject=payload.subject,
                              action="confirm", note=payload.note, created_by=user.id)
        db.add(row)
    else:
        row.subject = payload.subject
        row.action = "confirm"
        row.note = payload.note
        row.created_by = user.id
    db.add(AuditLog(action="resolve_conflict", object_type="account", object_id=0,
                    detail=f"account_key={payload.account_key[:60]}; subject={payload.subject}"[:1000]))
    db.commit()
    return {"ok": True, "account_key": payload.account_key, "subject": payload.subject}


@router.delete("/conflicts/resolve")
def undo_conflict(account_key: str, db: Session = Depends(get_session), user=Depends(current_user)):
    """撤销判定：把账户重新标回「待核查」。"""
    row = db.execute(
        select(SubjectDecision).where(SubjectDecision.account_key == account_key)
    ).scalars().first()
    if row is not None:
        db.delete(row)
        db.add(AuditLog(action="undo_conflict", object_type="account", object_id=0,
                        detail=f"account_key={account_key[:60]}"[:1000]))
        db.commit()
    return {"ok": True}


@router.get("/methods")
def get_methods():
    """合并方式说明：统一取自 algorithm.algo.merge 的 MODES，前端只渲染。"""
    try:
        from algorithm.algo.merge import mode_catalog

        items = [
            {
                "id": m["key"],
                "label": m["label"],
                "question": m.get("question", m["one_line"]),
                "approach": m.get("approach", m["formula"]),
                "impact": m.get("impact", m["when"]),
                "when_to_use": m.get("when_to_use", m["caveat"]),
                "tier": m.get("tier", "advanced"),
                # 兼容旧字段（报告/其它页面仍在用）
                "short": m["one_line"],
                "detail": m["when"],
                "formula": m["formula"],
                "assumption": m["caveat"],
                "level": m["level"],
            }
            for m in mode_catalog()
        ]
    except Exception:  # 引擎不可用时退回本地定义，保证页面可用
        items = [{"id": m["id"], "label": m["label"], "short": m["short"],
                  "detail": m["detail"], "formula": m["formula"],
                  "assumption": m["assumption"], "level": "flow"} for m in METHODS]
    return {
        "methods": items,
        "overlap_modes": [{"id": "auto", "label": "按期间自动处理", "detail": "合并引擎按各账户期间取并集，重叠不重复计数。"}],
    }


@router.get("/merge")
def get_merge(
    subject: str,
    method: str = "net_internal",
    overlap: str = "max",
    db: Session = Depends(get_session),
):
    try:
        return merge_subject(db, subject, method, overlap)
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "E_STATE", "message": str(exc)}) from exc