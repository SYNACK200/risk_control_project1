"""实体与合并接口：账户/户名识别、冲突告警、多账户合并。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.session import get_session
from helpers.security import require_local_access
from services.entities import METHODS, OVERLAP_MODES, collect_entities, merge_subject

router = APIRouter(prefix="/entities", tags=["entities"], dependencies=[Depends(require_local_access)])


@router.get("")
def get_entities(db: Session = Depends(get_session)):
    """账户、户名、以及「一个账户多个户名」的冲突告警。"""
    return collect_entities(db)


@router.get("/methods")
def get_methods():
    """合并方式说明：统一取自 algorithm.algo.merge 的 MODES，前端只渲染。"""
    try:
        from algorithm.algo.merge import mode_catalog

        items = [
            {
                "id": m["key"],
                "label": m["label"],
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
