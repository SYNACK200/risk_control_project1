"""报告与指标查询。"""
from __future__ import annotations

from datetime import datetime
import html as _html
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import ApprovalRecord, AuditLog, MetricValue, Report, Task, Txn, User
from db.session import get_session
from helpers.security import current_user, require_banker

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algorithm.algo.metric_defs import definitions_version, metric_definitions  # noqa: E402
from algorithm.algo.verification_defs import verification_definitions  # noqa: E402

router = APIRouter(tags=["reports"])


def _check_task(db: Session, task_id: int, user: User, *, allow_trashed_for_banker: bool = False) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(404, detail={"code": "E_NOT_FOUND", "message": "任务不存在"})
    if task.deleted_at is not None and not (allow_trashed_for_banker and user.role == "banker"):
        raise HTTPException(404, detail={"code": "E_NOT_FOUND", "message": "任务不存在"})
    if user.role != "banker" and task.user_id != user.id:
        raise HTTPException(404, detail={"code": "E_NOT_FOUND", "message": "任务不存在"})
    return task


@router.get("/reports/{task_id}", dependencies=[Depends(require_banker)])
def get_report(task_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)):
    task = _check_task(db, task_id, user, allow_trashed_for_banker=True)
    rep = db.execute(select(Report).where(Report.task_id == task_id).order_by(Report.version.desc())).scalars().first()
    if rep is None:
        raise HTTPException(404, "报告不存在")
    payload = dict(rep.payload or {})
    payload["verification"] = rep.verification or {"status": "pending"}
    payload["in_trash"] = task.deleted_at is not None
    approvals = db.execute(
        select(ApprovalRecord)
        .where(ApprovalRecord.task_id == task_id)
        .order_by(ApprovalRecord.id.desc())
    ).scalars().all()
    payload["approvals"] = [
        {
            "id": a.id,
            "report_id": a.report_id,
            "report_version": a.report_version,
            "decision": a.decision,
            "comment": a.comment,
            "actor_name": a.actor_name or "银行审批员",
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in approvals
    ]
    return payload


class ApprovalIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject|supplement|hold)$")
    comment: str = Field(min_length=1, max_length=1000)


@router.get("/reports/{task_id}/approvals", dependencies=[Depends(require_banker)])
def list_approvals(task_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)):
    _check_task(db, task_id, user, allow_trashed_for_banker=True)
    rows = db.execute(
        select(ApprovalRecord)
        .where(ApprovalRecord.task_id == task_id)
        .order_by(ApprovalRecord.id.desc())
    ).scalars().all()
    return {
        "items": [
            {
                "id": a.id,
                "report_id": a.report_id,
                "report_version": a.report_version,
                "decision": a.decision,
                "comment": a.comment,
                "actor_name": a.actor_name or "银行审批员",
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in rows
        ]
    }


@router.post("/reports/{task_id}/approvals", dependencies=[Depends(require_banker)])
def create_approval(
    task_id: int,
    payload: ApprovalIn,
    db: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """审批留痕：记录与当前报告版本绑定的审批决定与意见。"""
    task = _check_task(db, task_id, user, allow_trashed_for_banker=False)
    rep = db.execute(
        select(Report).where(Report.task_id == task_id).order_by(Report.version.desc())
    ).scalars().first()
    if rep is None:
        raise HTTPException(404, detail={"code": "E_STATE", "message": "该任务尚未生成报告，无法录入审批意见"})
    row = ApprovalRecord(
        task_id=task.id,
        report_id=rep.id,
        report_version=rep.version,
        decision=payload.decision,
        comment=payload.comment.strip(),
        actor_id=user.id,
        actor_name=user.display_name or user.username,
    )
    db.add(row)
    db.add(AuditLog(
        actor_id=user.id,
        action="approval_decision",
        object_type="report",
        object_id=rep.id,
        detail=f"task={task.id}; v={rep.version}; decision={payload.decision}; {payload.comment.strip()[:120]}",
    ))
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "report_id": row.report_id,
        "report_version": row.report_version,
        "decision": row.decision,
        "comment": row.comment,
        "actor_name": row.actor_name,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.post("/reports/{task_id}/export", dependencies=[Depends(require_banker)])
def export_report_printable(task_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)):
    """导出带操作人+时间水印的可打印结论版报告（HTML，支持浏览器直接存为 PDF），并写审计日志。"""
    task = _check_task(db, task_id, user, allow_trashed_for_banker=True)
    rep = db.execute(select(Report).where(Report.task_id == task_id).order_by(Report.version.desc())).scalars().first()
    if rep is None:
        raise HTTPException(404, detail={"code": "E_NOT_FOUND", "message": "报告不存在"})
    payload = dict(rep.payload or {})
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    wm = _html.escape(f"{user.display_name or user.username} · {ts} · {task.biz_no}")
    verdict = _html.escape(str(payload.get("verdict") or "—"))
    reason = _html.escape(str(payload.get("verdict_reason") or ""))
    trust_score = _html.escape(str(((payload.get("trust") or {}).get("score")) or "—"))
    overall = _html.escape(str(((payload.get("scores") or {}).get("overall")) or "—"))
    rows_html = "".join(
        f"<tr><td>{_html.escape(str(m.get('code', '')))}</td>"
        f"<td>{_html.escape(str(m.get('name', '')))}</td>"
        f"<td>{_html.escape(str(m.get('value') if m.get('value') is not None else '不可算'))}</td>"
        f"<td>{_html.escape(str(m.get('unit', '')))}</td></tr>"
        for m in (payload.get("metrics") or [])
    )
    html_doc = (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        f"<title>风控报告-{_html.escape(task.biz_no)}</title>"
        "<style>body{font-family:sans-serif;padding:28px;color:#111;}"
        ".wm{position:fixed;top:40%;left:15%;font-size:28px;color:rgba(0,0,0,.07);transform:rotate(-25deg);pointer-events:none;}"
        "table{width:100%;border-collapse:collapse;margin-top:16px;}th,td{border:1px solid #ddd;padding:6px 8px;font-size:13px;}"
        "</style></head><body>"
        f"<div class=\"wm\">{wm}</div>"
        f"<h1>银行流水核验与分析报告（{_html.escape(task.biz_no)}）</h1>"
        f"<p><strong>结论：</strong>{verdict} &nbsp;|&nbsp; <strong>真实性得分：</strong>{trust_score} &nbsp;|&nbsp; <strong>综合评分：</strong>{overall}</p>"
        f"<p>{reason}</p>"
        "<table><thead><tr><th>代号</th><th>指标</th><th>值</th><th>单位</th></tr></thead>"
        f"<tbody>{rows_html}</tbody></table>"
        f"<p style=\"margin-top:20px;color:#666;font-size:12px;\">导出水印：{wm}</p>"
        "</body></html>"
    )
    db.add(AuditLog(
        actor_id=user.id, action="report.export", object_type="report", object_id=rep.id,
        detail=f"format=printable_html; task_id={task.id}",
    ))
    db.commit()
    return Response(
        content=html_doc.encode("utf-8"),
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={task.biz_no}-report.html"},
    )


@router.get("/tasks/{task_id}/transactions", dependencies=[Depends(require_banker)])
def get_transactions(task_id: int, limit: int = 500, db: Session = Depends(get_session),
                     user: User = Depends(current_user)):
    _check_task(db, task_id, user)
    rows = db.execute(select(Txn).where(Txn.task_id == task_id).order_by(Txn.id).limit(min(limit, 2000))).scalars().all()
    return [{"id": r.id, "txn_date": r.txn_date, "direction": r.direction,
             "amount": None if r.amount is None else str(r.amount),
             "balance": None if r.balance is None else str(r.balance),
             "summary": r.summary, "counterparty_name": r.counterparty_name,
             "page_no": r.page_no, "confidence": None if r.confidence is None else str(r.confidence),
             "extra": r.extra} for r in rows]


@router.get("/tasks/{task_id}/metrics", dependencies=[Depends(require_banker)])
def get_metrics(task_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)):
    _check_task(db, task_id, user)
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