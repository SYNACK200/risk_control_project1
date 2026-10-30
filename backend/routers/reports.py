"""报告与指标查询。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import MetricValue, Report, Txn
from db.session import get_session
from helpers.security import require_local_access

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algorithm.algo.metric_defs import definitions_version, metric_definitions  # noqa: E402
from algorithm.algo.verification_defs import verification_definitions  # noqa: E402

router = APIRouter(tags=["reports"], dependencies=[Depends(require_local_access)])


@router.get("/reports/{task_id}")
def get_report(task_id: int, db: Session = Depends(get_session)):
    rep = db.execute(select(Report).where(Report.task_id == task_id).order_by(Report.version.desc())).scalars().first()
    if rep is None:
        raise HTTPException(404, "报告不存在")
    return rep.payload


@router.get("/tasks/{task_id}/transactions")
def get_transactions(task_id: int, limit: int = 500, db: Session = Depends(get_session)):
    rows = db.execute(select(Txn).where(Txn.task_id == task_id).order_by(Txn.id).limit(min(limit, 2000))).scalars().all()
    return [{"id": r.id, "txn_date": r.txn_date, "direction": r.direction,
             "amount": None if r.amount is None else str(r.amount),
             "balance": None if r.balance is None else str(r.balance),
             "summary": r.summary, "counterparty_name": r.counterparty_name,
             "page_no": r.page_no, "confidence": None if r.confidence is None else str(r.confidence)} for r in rows]


@router.get("/tasks/{task_id}/metrics")
def get_metrics(task_id: int, db: Session = Depends(get_session)):
    rows = db.execute(select(MetricValue).where(MetricValue.task_id == task_id).order_by(MetricValue.metric_code)).scalars().all()
    return [{"code": r.metric_code, "name": r.metric_name,
             "value": None if r.value_num is None else str(r.value_num),
             "unit": r.unit, "note": r.note, "caliber_version": r.caliber_version} for r in rows]


@router.get("/metric-definitions")
def get_metric_definitions():
    """40 项指标的定义（公式/输入/可视图类型），供银行侧展开查看。"""
    return {"metric_set_version": definitions_version(), "items": metric_definitions()}


@router.get("/verification-definitions")
def get_verification_definitions():
    """36 个真实性校验点：所属层与检验方法。运行结果随报告返回。"""
    return {"items": verification_definitions()}
