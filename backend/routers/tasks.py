"""任务接口：上传受理、列表、详情。"""
from __future__ import annotations

import csv
import io
import hashlib
import json
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import AuditLog, BankAccount, FileObj, MetricValue, Report, Task, TaskFile, Txn
from db.session import get_session
from algorithm.algo.preread import run_preread
from algorithm.algo.merge import AccountInput, merge_accounts, mode_catalog
from algorithm.ocr.models import Transaction
from datetime import date as _date
from helpers.security import require_local_access
from services import thresholds as threshold_service
from services.analysis import EncryptedFile, is_password_protected, run_analysis
from services.workflow import transition

router = APIRouter(prefix="/tasks", tags=["tasks"])
STORAGE = Path(__file__).resolve().parents[1] / "storage" / "uploads"
STORAGE.mkdir(parents=True, exist_ok=True)
PASSWORD_ATTEMPT_LIMIT = 3


def _safe_file_name(filename: str | None) -> str:
    return Path(filename or "材料文件").name[:120] or "材料文件"


def _find_or_create_file(
    db: Session,
    *,
    digest: str,
    mime: str | None,
    storage_path: Path,
) -> FileObj:
    row = db.execute(select(FileObj).where(FileObj.sha256 == digest)).scalars().first()
    if row is None:
        row = FileObj(sha256=digest, mime=mime, storage_path=str(storage_path))
        db.add(row)
        db.flush()
    return row


def _password_failure_count(db: Session, file_id: int) -> int:
    return int(db.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.action == "password_attempt_failed",
            AuditLog.object_type == "file",
            AuditLog.object_id == file_id,
        )
    ) or 0)


def _record_password_attempt(
    db: Session,
    *,
    file_id: int,
    file_name: str,
    outcome: str,
) -> None:
    """审计只记录材料名与结果，绝不记录口令或其派生值。"""
    db.add(AuditLog(
        action=f"password_attempt_{outcome}",
        object_type="file",
        object_id=file_id,
        detail=f"file={file_name}; result={outcome}",
    ))


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_task(
    file: UploadFile = File(...),
    password: str | None = Form(None),
    period_start: str | None = Form(None),
    period_end: str | None = Form(None),
    source_ref: str | None = Form(None),
    bank_code: str | None = Form(None),
    db: Session = Depends(get_session),
    _: None = Depends(require_local_access),
):
    data = file.file.read()
    if not data:
        raise HTTPException(400, "文件为空")
    digest = hashlib.sha256(data).hexdigest()

    path = STORAGE / f"{uuid.uuid4().hex}{Path(file.filename or '').suffix or '.pdf'}"
    path.write_bytes(data)
    file_name = _safe_file_name(file.filename)

    protected = is_password_protected(data)
    password_file: FileObj | None = None
    if protected:
        password_file = _find_or_create_file(
            db, digest=digest, mime=file.content_type, storage_path=path,
        )
        if not password:
            _record_password_attempt(
                db, file_id=password_file.id, file_name=file_name, outcome="cancelled",
            )
            db.commit()
            raise HTTPException(400, detail={"code": "E_ENCRYPT", "message": "PDF 需要打开口令"})
        if _password_failure_count(db, password_file.id) >= PASSWORD_ATTEMPT_LIMIT:
            raise HTTPException(429, detail={"code": "E_LIMIT", "message": "该材料口令尝试次数已达上限"})

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
    threshold_config = threshold_service.build_config(db)
    matched_template = None
    if template is None and preread.bank_code:
        from db.models import Template

        row = db.execute(
            select(Template).where(
                Template.bank_code == preread.bank_code.upper(), Template.status == "enabled"
            )
        ).scalars().first()
        if row is not None:
            template_row = row
            template = {"bank_code": row.bank_code, "version": row.version, "field_map": row.field_map}
            matched_template = {"id": row.id, "bank_code": row.bank_code, "by": "preread_bank_name"}
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
        result = run_analysis(
            data, password=password, template=template, preread=preread,
            thresholds=threshold_service.build_config(db),
        )
    except EncryptedFile as exc:
        if password_file is not None and password:
            _record_password_attempt(
                db, file_id=password_file.id, file_name=file_name, outcome="failed",
            )
            db.commit()
        raise HTTPException(400, detail={"code": "E_ENCRYPT", "message": str(exc)}) from exc
    except Exception as exc:  # 解析失败也要留任务与审计
        task = Task(
            biz_no=f"T{datetime.now():%Y%m%d%H%M%S}{uuid.uuid4().hex[:4]}",
            status="PENDING",
            failure_code="E_PARSE",
            created_at=datetime.now(),
            period_start=period_start,
            period_end=period_end,
        )
        db.add(task); db.flush()
        transition(task, "FAILED")
        db.commit(); db.refresh(task)
        db.add(AuditLog(action="create_task_failed", object_type="task", object_id=task.id, detail=str(exc)[:200]))
        db.commit()
        raise HTTPException(500, detail={"code": "E_PARSE", "message": str(exc)[:200]}) from exc

    file_obj = password_file or _find_or_create_file(
        db, digest=digest, mime=file.content_type, storage_path=path,
    )
    file_obj.mime = file.content_type
    file_obj.carrier = result["carrier"]
    file_obj.pages = result["pages"]
    file_obj.has_text_layer = result["has_text_layer"]
    if not file_obj.storage_path:
        file_obj.storage_path = str(path)

    task = Task(
        biz_no=f"T{datetime.now():%Y%m%d%H%M%S}{uuid.uuid4().hex[:4]}",
        task_type="credit", channel="upload", file_id=file_obj.id,
        carrier=result["carrier"], status="PENDING",
        template_id=template_row.id if template_row else None,
        template_version=template_row.version if template_row else None,
        period_start=period_start, period_end=period_end,
        check_result={
            "warnings": result["warnings"],
            "self_check": result.get("self_check"),
            "preread": result.get("preread"),
            "matched_template": matched_template,
        },
        finished_at=datetime.now(),
    )
    db.add(task); db.flush()
    db.add(TaskFile(task_id=task.id, file_id=file_obj.id, role="original", seq=1))

    # 现阶段仍同步执行分析；每次状态推进仍必须满足统一状态机。
    transition(task, "CHECKING")
    transition(task, "PARSING")
    transition(task, "VERIFYING")
    transition(task, "REPORTING")

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
    if result["password_protected"] and password:
        _record_password_attempt(
            db, file_id=file_obj.id, file_name=file_name, outcome="success",
        )
    transition(task, "DONE")
    db.commit(); db.refresh(task)

    return {"task_id": task.id, "biz_no": task.biz_no, "status": task.status,
            "carrier": task.carrier, "txn_count": result["txn_count"],
            "preread": result.get("preread")}


def _latest_report(db: Session, task_id: int) -> Report | None:
    return db.execute(
        select(Report).where(Report.task_id == task_id).order_by(Report.version.desc())
    ).scalars().first()


def _summary_rows(db: Session, tasks: list[Task]) -> list[dict]:
    from services.summary import summarize

    out: list[dict] = []
    for task in tasks:
        rep = _latest_report(db, task.id)
        file_row = db.get(FileObj, task.file_id) if task.file_id else None
        txn_count = db.execute(
            select(func.count()).select_from(Txn).where(Txn.task_id == task.id)
        ).scalar_one()
        out.append(
            summarize(
                task=task,
                payload=(rep.payload if rep else None),
                file_row=file_row,
                txn_count=int(txn_count or 0),
                report_version=(rep.version if rep else None),
            )
        )
    return out


def _facets(items: list[dict]) -> dict:
    def counts(key: str) -> dict:
        result: dict[str, int] = {}
        for item in items:
            value = (item.get(key) or {}).get("level") if isinstance(item.get(key), dict) else None
            if value:
                result[value] = result.get(value, 0) + 1
        return result

    banks: dict[str, int] = {}
    for item in items:
        name = item.get("bank_name") or "未识别"
        banks[name] = banks.get(name, 0) + 1
    return {
        "authenticity": counts("authenticity"),
        "source": counts("source"),
        "risk": counts("risk"),
        "parse": counts("parse"),
        "bank": banks,
        "total": len(items),
    }


@router.get("")
def list_tasks(
    status: str | None = None,
    limit: int = 500,
    authenticity: str | None = None,
    source: str | None = None,
    risk: str | None = None,
    risk_code: str | None = None,
    min_income: float | None = None,
    max_income: float | None = None,
    parse: str | None = None,
    bank: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
    trash: int = 0,
    db: Session = Depends(get_session),
    _: None = Depends(require_local_access),
):
    """解析结果列表：按银行关心的维度汇总，并支持合格性/风险/解析质量/银行/时间/关键字筛选。"""
    stmt = select(Task).order_by(Task.id.desc()).limit(min(limit, 1000))
    stmt = stmt.where(Task.deleted_at.is_not(None)) if trash else stmt.where(Task.deleted_at.is_(None))
    if status:
        stmt = stmt.where(Task.status == status)
    rows = db.execute(stmt).scalars().all()
    items = _summary_rows(db, rows)
    facets = _facets(items)

    if authenticity:
        items = [i for i in items if i["authenticity"]["level"] == authenticity]
    if source:
        items = [i for i in items if i["source"]["level"] == source]
    if risk:
        items = [i for i in items if i["risk"]["level"] == risk]
    if risk_code:
        items = [i for i in items if risk_code in (i.get("risk_codes") or [])]
    def _income(item):
        try:
            return float(item.get("income") or 0)
        except (TypeError, ValueError):
            return 0.0
    if min_income is not None:
        items = [i for i in items if _income(i) >= min_income]
    if max_income is not None:
        items = [i for i in items if _income(i) <= max_income]
    if parse:
        items = [i for i in items if i["parse"]["level"] == parse]
    if bank:
        items = [i for i in items if (i.get("bank_name") or "未识别") == bank]
    if date_from:
        items = [i for i in items if (i.get("created_at") or "") >= date_from]
    if date_to:
        items = [i for i in items if (i.get("created_at") or "") <= date_to + "T23:59:59"]
    if q:
        needle = q.strip().lower()
        items = [i for i in items if needle in (i.get("biz_no") or "").lower()]
    return {"items": items, "total": len(items), "facets": facets}


class TaskIdsPayload(BaseModel):
    task_ids: list[int]
    confirm: bool = False


def _load_tasks(db: Session, ids: list[int]) -> list[Task]:
    if not ids:
        raise HTTPException(400, detail={"code": "E_PARAM", "message": "未选择任何流水"})
    rows = db.execute(select(Task).where(Task.id.in_(ids))).scalars().all()
    if not rows:
        raise HTTPException(404, detail={"code": "E_NOT_FOUND", "message": "选中的流水不存在"})
    return list(rows)


@router.get("/{task_id}/transactions.csv")
def transactions_export(task_id: int, db: Session = Depends(get_session),
                        _: None = Depends(require_local_access)):
    # 明细导出：UTF-8 BOM + CRLF，Excel 直接双击可读
    task = db.get(Task, task_id)
    if task is None or task.deleted_at is not None:
        raise HTTPException(404, detail={"code": "E_NOT_FOUND", "message": "流水不存在或已删除"})
    rows = db.execute(select(Txn).where(Txn.task_id == task_id)
                      .order_by(Txn.txn_date, Txn.id)).scalars().all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["业务号", "交易日期", "方向", "金额", "余额", "摘要", "对方", "页号"])
    for row in rows:
        writer.writerow([task.biz_no, row.txn_date, "收入" if row.direction == "in" else "支出" if row.direction == "out" else "",
                         "" if row.amount is None else row.amount, "" if row.balance is None else row.balance,
                         row.summary or "", row.counterparty_name or "", row.page_no or ""])
    body = "\ufeff" + buffer.getvalue()
    filename = f"{task.biz_no}.csv"
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{task_id}/export.json")
def report_export(task_id: int, db: Session = Depends(get_session),
                  _: None = Depends(require_local_access)):
    # 完整报告导出：报告 + 明细 + 阈值版本，用于归档或二次分析
    task = db.get(Task, task_id)
    if task is None or task.deleted_at is not None:
        raise HTTPException(404, detail={"code": "E_NOT_FOUND", "message": "流水不存在或已删除"})
    report_row = db.execute(
        select(Report).where(Report.task_id == task_id).order_by(Report.version.desc())
    ).scalars().first()
    if report_row is None:
        raise HTTPException(404, detail={"code": "E_STATE", "message": "该流水还没有报告"})
    rows = db.execute(select(Txn).where(Txn.task_id == task_id)
                      .order_by(Txn.txn_date, Txn.id)).scalars().all()
    payload = {
        "biz_no": task.biz_no,
        "status": task.status,
        "carrier": task.carrier,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "report": report_row.payload,
        "transactions": [
            {
                "txn_date": r.txn_date, "direction": r.direction,
                "amount": None if r.amount is None else str(r.amount),
                "balance": None if r.balance is None else str(r.balance),
                "summary": r.summary, "counterparty_name": r.counterparty_name, "page_no": r.page_no,
            }
            for r in rows
        ],
    }
    filename = f"{task.biz_no}.json"
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/recycle")
def recycle_tasks(payload: TaskIdsPayload, db: Session = Depends(get_session),
                  _: None = Depends(require_local_access)):
    # 批量移入回收站：只标记 deleted_at，明细与报告都保留，可恢复
    rows = _load_tasks(db, payload.task_ids)
    now = datetime.utcnow()
    moved = 0
    for row in rows:
        if row.deleted_at is None:
            row.deleted_at = now
            moved += 1
    db.add(AuditLog(action="recycle_tasks", object_type="task", object_id=rows[0].id,
                    detail=f"ids={sorted(r.id for r in rows)}; moved={moved}"))
    db.commit()
    return {"moved": moved, "ids": sorted(r.id for r in rows)}


@router.post("/restore")
def restore_tasks(payload: TaskIdsPayload, db: Session = Depends(get_session),
                  _: None = Depends(require_local_access)):
    # 从回收站恢复
    rows = _load_tasks(db, payload.task_ids)
    restored = 0
    for row in rows:
        if row.deleted_at is not None:
            row.deleted_at = None
            restored += 1
    db.add(AuditLog(action="restore_tasks", object_type="task", object_id=rows[0].id,
                    detail=f"ids={sorted(r.id for r in rows)}; restored={restored}"))
    db.commit()
    return {"restored": restored, "ids": sorted(r.id for r in rows)}


@router.post("/purge")
def purge_tasks(payload: TaskIdsPayload, db: Session = Depends(get_session),
                _: None = Depends(require_local_access)):
    # 彻底删除：只允许回收站内、且 confirm=true；连同明细/指标/报告/材料关联一起删
    if not payload.confirm:
        raise HTTPException(400, detail={"code": "E_CONFIRM", "message": "彻底删除需要 confirm=true"})
    rows = _load_tasks(db, payload.task_ids)
    live = [r for r in rows if r.deleted_at is None]
    if live:
        raise HTTPException(409, detail={"code": "E_STATE",
                                         "message": f"这些流水还在用，请先移入回收站：{[r.id for r in live]}"})
    ids = [r.id for r in rows]
    purged = 0
    for task in rows:
        db.query(Txn).filter(Txn.task_id == task.id).delete()
        db.query(MetricValue).filter(MetricValue.task_id == task.id).delete()
        db.query(Report).filter(Report.task_id == task.id).delete()
        db.query(TaskFile).filter(TaskFile.task_id == task.id).delete()
        db.query(BankAccount).filter(BankAccount.task_id == task.id).delete()
        db.delete(task)
        purged += 1
    db.add(AuditLog(action="purge_tasks", object_type="task", object_id=ids[0],
                    detail=f"ids={sorted(ids)}; purged={purged}"))
    db.commit()
    return {"purged": purged, "ids": sorted(ids)}


@router.post("/{task_id}/reanalyze")
def reanalyze_task(
    task_id: int,
    password: str | None = Form(None),
    template_id: int | None = Form(None),
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
    from db.models import Template
    chosen_id = template_id if template_id is not None else task.template_id
    if chosen_id:
        row = db.get(Template, chosen_id)
        if row is not None:
            template = {"bank_code": row.bank_code, "version": row.version, "field_map": row.field_map}
            task.template_id = row.id
            task.template_version = row.version

    preread = run_preread(data, password=password)
    try:
        result = run_analysis(
            data, password=password, template=template, preread=preread,
            thresholds=threshold_service.build_config(db),
        )
    except EncryptedFile as exc:
        raise HTTPException(400, detail={"code": "E_ENCRYPT", "message": str(exc)}) from exc

    # 明细与指标按本次解析结果重建（重解析的核心目的）
    from db.models import MetricValue as _MetricValue, Txn as _Txn

    db.query(_Txn).filter(_Txn.task_id == task_id).delete()
    db.query(_MetricValue).filter(_MetricValue.task_id == task_id).delete()
    for item in result["transactions"]:
        db.add(_Txn(
            task_id=task_id,
            txn_date=item["txn_date"],
            direction=item["direction"],
            amount=None if item["amount"] is None else Decimal(item["amount"]),
            balance=None if item["balance"] is None else Decimal(item["balance"]),
            summary=item["summary"],
            counterparty_name=item["counterparty_name"],
            page_no=item["page_no"],
            confidence=None if item["confidence"] is None else Decimal(item["confidence"]),
        ))
    for m in result["metrics"]:
        db.add(_MetricValue(
            task_id=task_id, metric_code=m["code"], metric_name=m["name"],
            value_num=None if m["value"] is None else Decimal(m["value"]),
            unit=m["unit"], note=m["note"],
            caliber_version=m.get("caliber_version", 1),
        ))
    db.flush()

    latest = db.execute(
        select(Report).where(Report.task_id == task_id).order_by(Report.version.desc())
    ).scalars().first()
    new_version = (latest.version + 1) if latest else 1
    payload = dict(result["report"])
    payload["version"] = new_version  # 对外可见的报告版本，只增不改
    db.add(Report(task_id=task_id, version=new_version, payload=payload))

    check = dict(task.check_result or {})
    check.update({
        "warnings": result["warnings"],
        "self_check": result.get("self_check"),
        "preread": result.get("preread"),
    })
    task.check_result = check
    db.add(AuditLog(action="reanalyze_task", object_type="task", object_id=task_id,
                    detail="report v" + str(new_version)))
    db.commit()
    return {"task_id": task_id, "version": new_version, "layers": [
        {"layer": l["layer"], "status": l["status"], "checks": len(l.get("checks") or [])}
        for l in result["report"].get("layers", [])
    ]}


@router.post("/{task_id}/whitelist")
def whitelist_task(
    task_id: int,
    reason: str = Form(...),
    db: Session = Depends(get_session),
):
    """人工开绿灯：标记该任务为已复核，解析失败不再阻断后续使用。"""
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    check = dict(task.check_result or {})
    check["whitelist"] = {
        "reason": reason,
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    task.check_result = check
    db.add(AuditLog(action="whitelist_task", object_type="task", object_id=task_id, detail=reason[:180]))
    db.commit()
    return {"task_id": task_id, "whitelisted": True, "reason": reason}


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


@router.get("/merge/modes")
def merge_modes():
    """可选的多账户合并方式（含公式、适用条件与已知偏差）。"""
    return {"items": mode_catalog()}


@router.post("/merge")
def merge_tasks(payload: dict, db: Session = Depends(get_session)):
    """把同一借款人的多个账户合并成一份视图。

    入参：{"task_ids": [1,2], "mode": "net_internal"}
    """
    task_ids = [int(x) for x in (payload.get("task_ids") or [])]
    mode = str(payload.get("mode") or "net_internal")
    if len(task_ids) < 2:
        raise HTTPException(400, detail={"code": "E_STATE", "message": "至少选择两个账户/任务"})
    accounts = []
    for task_id in task_ids:
        task = db.get(Task, task_id)
        if task is None:
            continue
        rows = db.execute(select(Txn).where(Txn.task_id == task_id).order_by(Txn.id)).scalars().all()
        def _d(value):
            if not value:
                return None
            try:
                return _date.fromisoformat(str(value)[:10])
            except ValueError:
                return None
        accounts.append(AccountInput(
            account_id=str(task_id),
            bank_code=None,
            period_start=_d(task.period_start),
            period_end=_d(task.period_end),
            transactions=[
                Transaction(
                    page_no=r.page_no or 1, row_no=index + 1,
                    txn_date=r.txn_date, direction=r.direction,
                    amount=r.amount, balance=r.balance,
                    summary=r.summary, counterparty_name=r.counterparty_name,
                )
                for index, r in enumerate(rows)
            ],
        ))
    try:
        result = merge_accounts(accounts, mode)
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "E_STATE", "message": str(exc)}) from exc
    db.add(AuditLog(action="merge_accounts", object_type="task", object_id=task_ids[0],
                    detail=f"mode={mode}; tasks={task_ids}"))
    db.commit()
    return result

@router.post("/{task_id}/supplement", status_code=status.HTTP_202_ACCEPTED)
def add_supplement(
    task_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
    _: None = Depends(require_local_access),
):
    """为待补件任务追加材料；不创建新任务，也不覆盖历史材料。"""
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    if task.status != "NEED_SUPPLEMENT":
        raise HTTPException(409, detail={"code": "E_STATE", "message": "当前任务不允许补件"})

    data = file.file.read()
    if not data:
        raise HTTPException(400, detail={"code": "E_FORMAT", "message": "补件文件为空"})
    digest = hashlib.sha256(data).hexdigest()
    existing = db.execute(
        select(TaskFile).join(FileObj, TaskFile.file_id == FileObj.id).where(
            TaskFile.task_id == task.id, FileObj.sha256 == digest,
        )
    ).scalars().first()
    if existing is not None:
        raise HTTPException(409, detail={"code": "E_STATE", "message": "该材料已在此任务中，无需重复补传"})

    path = STORAGE / f"{uuid.uuid4().hex}{Path(file.filename or '').suffix or '.pdf'}"
    path.write_bytes(data)
    file_obj = _find_or_create_file(
        db, digest=digest, mime=file.content_type, storage_path=path,
    )
    max_seq = db.scalar(select(func.max(TaskFile.seq)).where(TaskFile.task_id == task.id)) or 0
    db.add(TaskFile(task_id=task.id, file_id=file_obj.id, role="supplement", seq=int(max_seq) + 1))
    transition(task, "PARSING")
    db.add(AuditLog(
        action="add_supplement", object_type="task", object_id=task.id,
        detail=f"file={_safe_file_name(file.filename)}; file_id={file_obj.id}",
    ))
    db.commit()
    return {"task_id": task.id, "status": task.status, "file_id": file_obj.id, "material_count": int(max_seq) + 1}

