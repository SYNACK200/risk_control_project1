"""任务接口：上传受理、列表、详情。"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import AuditLog, FileObj, MetricValue, Report, Task, TaskFile, Txn
from db.session import get_session
from algorithm.algo.preread import run_preread
from services.analysis import EncryptedFile, run_analysis

router = APIRouter(prefix="/tasks", tags=["tasks"])
STORAGE = Path(__file__).resolve().parents[1] / "storage" / "uploads"
STORAGE.mkdir(parents=True, exist_ok=True)


@router.post("")
def create_task(
    file: UploadFile = File(...),
    password: str | None = Form(None),
    period_start: str | None = Form(None),
    period_end: str | None = Form(None),
    source_ref: str | None = Form(None),
    bank_code: str | None = Form(None),
    db: Session = Depends(get_session),
):
    data = file.file.read()
    if not data:
        raise HTTPException(400, "文件为空")
    digest = hashlib.sha256(data).hexdigest()

    path = STORAGE / f"{uuid.uuid4().hex}{Path(file.filename or '').suffix or '.pdf'}"
    path.write_bytes(data)

    template = None
    template_row = None
    if bank_code:
        from db.models import Template

        row = db.execute(
            select(Template).where(Template.bank_code == bank_code.upper(), Template.status == "enabled")
        ).scalars().first()
        if row:
            template_row = row
            template = {"bank_code": row.bank_code, "version": row.version, "field_map": row.field_map}

    # 预读取：不看模板，先判断「是不是流水」，并抓基础信息
    preread = run_preread(data, password=password)
    if preread.verdict == "reject":
        db.add(AuditLog(action="preread_rejected", object_type="file", object_id=0,
                        detail=f"not_statement; rows={preread.txn_like_rows}; reasons={'；'.join(preread.reasons)[:180]}"))
        db.commit()
        raise HTTPException(422, detail={
            "code": "E_NOT_STATEMENT",
            "message": "这不是银行流水/对账单文件" + ("：" + "；".join(preread.reasons[:3]) if preread.reasons else ""),
            "preread": preread.to_dict(),
        })

    try:
        result = run_analysis(data, password=password, template=template, preread=preread)
    except EncryptedFile as exc:
        raise HTTPException(400, detail={"code": "E_ENCRYPT", "message": str(exc)}) from exc
    except Exception as exc:  # 解析失败也要留任务与审计
        task = Task(
            biz_no=f"T{datetime.now():%Y%m%d%H%M%S}{uuid.uuid4().hex[:4]}",
            status="FAILED",
            failure_code="E_PARSE",
            created_at=datetime.now(),
            period_start=period_start,
            period_end=period_end,
        )
        db.add(task); db.commit(); db.refresh(task)
        db.add(AuditLog(action="create_task_failed", object_type="task", object_id=task.id, detail=str(exc)[:200]))
        db.commit()
        raise HTTPException(500, detail={"code": "E_PARSE", "message": str(exc)[:200]}) from exc

    file_obj = db.execute(select(FileObj).where(FileObj.sha256 == digest)).scalars().first()
    if file_obj is None:
        file_obj = FileObj(
            sha256=digest, mime=file.content_type, carrier=result["carrier"],
            pages=result["pages"], has_text_layer=result["has_text_layer"], storage_path=str(path),
        )
        db.add(file_obj); db.flush()

    task = Task(
        biz_no=f"T{datetime.now():%Y%m%d%H%M%S}{uuid.uuid4().hex[:4]}",
        task_type="credit", channel="upload", file_id=file_obj.id,
        carrier=result["carrier"], status="DONE",
        template_id=template_row.id if template_row else None,
        template_version=template_row.version if template_row else None,
        period_start=period_start, period_end=period_end,
        check_result={
            "warnings": result["warnings"],
            "self_check": result.get("self_check"),
            "preread": result.get("preread"),
        },
        finished_at=datetime.now(),
    )
    db.add(task); db.flush()
    db.add(TaskFile(task_id=task.id, file_id=file_obj.id, role="original", seq=1))

    for i, t in enumerate(result["transactions"], start=1):
        db.add(Txn(
            task_id=task.id, txn_date=t["txn_date"], direction=t["direction"],
            amount=None if t["amount"] is None else Decimal(t["amount"]),
            balance=None if t["balance"] is None else Decimal(t["balance"]),
            summary=t["summary"], counterparty_name=t["counterparty_name"], page_no=t["page_no"],
            confidence=None if t["confidence"] is None else Decimal(t["confidence"]),
        ))
    for m in result["metrics"]:
        db.add(MetricValue(
            task_id=task.id, metric_code=m["code"], metric_name=m["name"],
            value_num=None if m["value"] is None else Decimal(m["value"]),
            unit=m["unit"], note=m["note"], caliber_version=m["caliber_version"],
        ))
    rep = result["report"]
    db.add(Report(
        task_id=task.id, version=1, carrier=rep["carrier"], verdict=rep["verdict"],
        verdict_reason=rep["verdict_reason"], layers=rep["layers"], limitations=rep["limitations"],
        evidence=rep["evidence"], materials=rep["materials"],
        metric_set_version=rep["metric_set_version"], threshold_version=rep["threshold_version"],
        payload=rep,
    ))
    db.add(AuditLog(action="create_task", object_type="task", object_id=task.id,
                   detail=f"source_ref={source_ref or '-'} carrier={rep['carrier']}"))
    db.commit(); db.refresh(task)

    return {"task_id": task.id, "biz_no": task.biz_no, "status": task.status,
            "carrier": task.carrier, "txn_count": result["txn_count"],
            "preread": result.get("preread")}


@router.get("")
def list_tasks(status: str | None = None, limit: int = 20, db: Session = Depends(get_session)):
    stmt = select(Task).order_by(Task.id.desc()).limit(min(limit, 100))
    if status:
        stmt = stmt.where(Task.status == status)
    rows = db.execute(stmt).scalars().all()
    return [{"id": t.id, "biz_no": t.biz_no, "status": t.status, "carrier": t.carrier,
             "created_at": t.created_at.isoformat() if t.created_at else None} for t in rows]


@router.post("/{task_id}/reanalyze")
def reanalyze_task(
    task_id: int,
    password: str | None = Form(None),
    db: Session = Depends(get_session),
):
    """用原文件重跑一次分析，补齐逐项明细（旧版报告没有 checks）。"""
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    if task.file_id is None:
        raise HTTPException(400, detail={"code": "E_STATE", "message": "任务没有关联文件"})
    f = db.get(FileObj, task.file_id)
    if f is None or not f.storage_path:
        raise HTTPException(400, detail={"code": "E_STATE", "message": "原文件已不在存储中，无法重算"})
    path = Path(f.storage_path)
    if not path.exists():
        raise HTTPException(400, detail={"code": "E_STATE", "message": "原文件已被清理，无法重算"})
    data = path.read_bytes()

    template = None
    if task.template_id:
        from db.models import Template
        row = db.get(Template, task.template_id)
        if row is not None:
            template = {"bank_code": row.bank_code, "version": row.version, "field_map": row.field_map}

    preread = run_preread(data, password=password)
    try:
        result = run_analysis(data, password=password, template=template, preread=preread)
    except EncryptedFile as exc:
        raise HTTPException(400, detail={"code": "E_ENCRYPT", "message": str(exc)}) from exc

    latest = db.execute(
        select(Report).where(Report.task_id == task_id).order_by(Report.version.desc())
    ).scalars().first()
    new_version = (latest.version + 1) if latest else 1
    payload = dict(result["report"])
    payload["version"] = new_version  # 对外可见的报告版本，只增不改
    db.add(Report(task_id=task_id, version=new_version, payload=payload))

    task.check_result = {
        "warnings": result["warnings"],
        "self_check": result.get("self_check"),
        "preread": result.get("preread"),
    }
    db.add(AuditLog(action="reanalyze_task", object_type="task", object_id=task_id,
                    detail="report v" + str(new_version)))
    db.commit()
    return {"task_id": task_id, "version": new_version, "layers": [
        {"layer": l["layer"], "status": l["status"], "checks": len(l.get("checks") or [])}
        for l in result["report"].get("layers", [])
    ]}


@router.get("/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_session)):
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    return {"id": task.id, "biz_no": task.biz_no, "status": task.status, "carrier": task.carrier,
            "period_start": task.period_start, "period_end": task.period_end,
            "failure_code": task.failure_code,
            "check_result": task.check_result,
            "created_at": task.created_at.isoformat() if task.created_at else None}

