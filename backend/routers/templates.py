"""模板的存取与发布（管理页面用）。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import Task, Template, Txn
from db.session import get_session
from helpers.security import require_local_access
from services.analysis import infer_from_marks

router = APIRouter(prefix="/templates", tags=["templates"], dependencies=[Depends(require_local_access)])


class TemplateIn(BaseModel):
    bank_code: str
    field_map: dict
    header_columns: list | None = None
    version: int = 1


@router.get("")
def list_templates(bank_code: str | None = None, db: Session = Depends(get_session)):
    stmt = select(Template).order_by(Template.bank_code, Template.version.desc())
    if bank_code:
        stmt = stmt.where(Template.bank_code == bank_code.upper())
    rows = db.execute(stmt).scalars().all()
    return [{"id": t.id, "bank_code": t.bank_code, "version": t.version,
             "status": t.status, "field_map": t.field_map, "header_columns": t.header_columns} for t in rows]


@router.post("")
def create_template(payload: TemplateIn, db: Session = Depends(get_session)):
    row = Template(bank_code=payload.bank_code.upper(), version=payload.version,
                   status="draft", field_map=payload.field_map, header_columns=payload.header_columns)
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "status": row.status}


@router.post("/{template_id}/publish")
def publish_template(template_id: int, db: Session = Depends(get_session)):
    row = db.get(Template, template_id)
    if row is None:
        raise HTTPException(404, "模板不存在")
    # 同一银行只允许一个启用版本
    others = db.execute(select(Template).where(Template.bank_code == row.bank_code)).scalars().all()
    for o in others:
        o.status = "enabled" if o.id == row.id else "disabled"
    db.commit()
    return {"id": row.id, "status": row.status}



class InferApply(BaseModel):
    template_id: int


@router.post("/infer")
def infer_template_api(
    file: UploadFile = File(...),
    marks: str = Form(..., description="JSON 数组，如 [{\"field\":\"amount\",\"page\":0,\"x\":530,\"y\":60}]"),
    bank_code: str = Form("UNKNOWN"),
    password: str | None = Form(None),
    save_draft: bool = Form(False),
    db: Session = Depends(get_session),
):
    """少量标注 → 外推整张表的模板；返回字段映射、来源与置信度。"""
    import json as _json

    try:
        parsed_marks = _json.loads(marks)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"marks 不是合法 JSON：{exc}") from exc
    if not isinstance(parsed_marks, list) or not parsed_marks:
        raise HTTPException(400, "marks 必须是非空数组")

    data = file.file.read()
    if not data:
        raise HTTPException(400, "文件为空")
    if data[:4] == b"%PDF":
        import pymupdf

        doc = pymupdf.open(stream=data, filetype="pdf")
        if doc.needs_pass:
            if not password or doc.authenticate(password) <= 0:
                raise HTTPException(400, detail={"code": "E_ENCRYPT", "message": "PDF 需要打开口令"})
            import tempfile
            from pathlib import Path as _Path

            tmp = _Path(tempfile.gettempdir()) / "infer_plain.pdf"
            doc.save(tmp, encryption=pymupdf.PDF_ENCRYPT_NONE)
            data = tmp.read_bytes()
    try:
        result = infer_from_marks(data, parsed_marks, bank_code=bank_code)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    payload = {
        "bank_code": bank_code.upper(),
        "field_map": result["field_map"],
        "provenance": result["provenance"],
        "columns": result["columns"],
        "warnings": result["warnings"],
    }
    if save_draft:
        row = Template(bank_code=bank_code.upper(), version=1, status="draft",
                       field_map=result["field_map"],
                       header_columns=[c.get("alias") for c in result["columns"]])
        db.add(row); db.commit(); db.refresh(row)
        payload["template_id"] = row.id
    return payload

class TemplatePatch(BaseModel):
    bank_code: str | None = None
    field_map: dict | None = None
    header_columns: list | None = None


@router.put("/{template_id}")
def update_template(template_id: int, payload: TemplatePatch, db: Session = Depends(get_session)):
    # 改模板 = 出新版本：旧版本保留为 disabled，历史可追溯
    row = db.get(Template, template_id)
    if row is None:
        raise HTTPException(404, "模板不存在")
    latest = db.execute(select(func.max(Template.version)).where(
        Template.bank_code == (payload.bank_code or row.bank_code).upper()
    )).scalar() or 0
    new_row = Template(
        bank_code=(payload.bank_code or row.bank_code).upper(),
        version=latest + 1,
        status="draft",
        field_map=payload.field_map if payload.field_map is not None else row.field_map,
        header_columns=payload.header_columns if payload.header_columns is not None else row.header_columns,
    )
    old_status = row.status
    row.status = "disabled"
    db.add(new_row)
    db.commit()
    db.refresh(new_row)
    return {"id": new_row.id, "version": new_row.version, "status": new_row.status, "previous_id": row.id,
            "previous_status": old_status}


@router.post("/{template_id}/duplicate")
def duplicate_template(template_id: int, db: Session = Depends(get_session)):
    row = db.get(Template, template_id)
    if row is None:
        raise HTTPException(404, "模板不存在")
    latest = db.execute(select(func.max(Template.version)).where(
        Template.bank_code == row.bank_code)).scalar() or row.version
    copy = Template(bank_code=row.bank_code, version=latest + 1, status="draft",
                    field_map=row.field_map, header_columns=row.header_columns)
    db.add(copy)
    db.commit()
    db.refresh(copy)
    return {"id": copy.id, "version": copy.version}


@router.post("/{template_id}/disable")
def disable_template(template_id: int, db: Session = Depends(get_session)):
    row = db.get(Template, template_id)
    if row is None:
        raise HTTPException(404, "模板不存在")
    row.status = "disabled"
    db.commit()
    return {"id": row.id, "status": row.status}


@router.delete("/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_session)):
    row = db.get(Template, template_id)
    if row is None:
        raise HTTPException(404, "模板不存在")
    used = db.execute(select(func.count(Task.id)).where(Task.template_id == template_id)).scalar() or 0
    if used:
        raise HTTPException(409, detail={"code": "E_STATE",
                                         "message": f"该模板已被 {used} 条流水使用，请先停用而不是删除"})
    db.delete(row)
    db.commit()
    return {"deleted": template_id}


@router.get("/{template_id}/stats")
def template_stats(template_id: int, db: Session = Depends(get_session)):
    row = db.get(Template, template_id)
    if row is None:
        raise HTTPException(404, "模板不存在")
    tasks = db.execute(select(Task).where(Task.template_id == template_id)).scalars().all()
    done = [t for t in tasks if t.status == "DONE"]
    failed = [t for t in tasks if t.status == "FAILED"]
    counts = []
    for t in done:
        n = db.execute(select(func.count(Txn.id)).where(Txn.task_id == t.id)).scalar() or 0
        counts.append(n)
    avg = round(sum(counts) / len(counts), 1) if counts else None
    return {
        "template_id": row.id,
        "bank_code": row.bank_code,
        "version": row.version,
        "status": row.status,
        "tasks_total": len(tasks),
        "tasks_done": len(done),
        "tasks_failed": len(failed),
        "success_rate": (round(len(done) / len(tasks), 4) if tasks else None),
        "avg_txn_count": avg,
        "zero_txn_tasks": len([c for c in counts if c == 0]),
    }


@router.post("/{template_id}/preview")
def preview_template(template_id: int, file: UploadFile = File(...), password: str | None = Form(None),
                     db: Session = Depends(get_session)):
    # 用该模板试解析一份样例，不落库
    row = db.get(Template, template_id)
    if row is None:
        raise HTTPException(404, "模板不存在")
    data = file.file.read()
    if not data:
        raise HTTPException(400, "文件为空")
    from algorithm.ocr.models import Template as ParseTemplate
    from algorithm.ocr.parse import parse
    raw = data
    if data[:4] == b"%PDF":
        import pymupdf
        doc = pymupdf.open(stream=data, filetype="pdf")
        if doc.needs_pass:
            if not password or doc.authenticate(password) <= 0:
                raise HTTPException(400, detail={"code": "E_ENCRYPT", "message": "PDF 需要打开口令"})
    tpl = ParseTemplate(bank_code=row.bank_code, version=row.version, field_map=dict(row.field_map or {}))
    parsed = parse(raw, tpl)
    rows = [
        {
            "txn_date": t.txn_date, "summary": t.summary, "direction": t.direction,
            "amount": None if t.amount is None else str(t.amount),
            "balance": None if t.balance is None else str(t.balance),
            "page_no": t.page_no,
        }
        for t in parsed.transactions[:10]
    ]
    return {
        "template_id": row.id,
        "txn_count": len(parsed.transactions),
        "page_count": parsed.page_count,
        "warnings": parsed.warnings[:8],
        "rows": rows,
    }


@router.get("/{template_id}/export")
def export_template(template_id: int, db: Session = Depends(get_session)):
    row = db.get(Template, template_id)
    if row is None:
        raise HTTPException(404, "模板不存在")
    payload = {
        "bank_code": row.bank_code, "version": row.version, "field_map": row.field_map,
        "header_columns": row.header_columns,
    }
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=template-{row.bank_code}-v{row.version}.json"},
    )


@router.post("/import")
def import_template(payload: dict, db: Session = Depends(get_session)):
    bank = str(payload.get("bank_code") or "").upper()
    if not bank:
        raise HTTPException(400, detail={"code": "E_PARAM", "message": "缺少 bank_code"})
    field_map = payload.get("field_map") or {}
    if not isinstance(field_map, dict) or not field_map:
        raise HTTPException(400, detail={"code": "E_PARAM", "message": "field_map 不能为空"})
    latest = db.execute(select(func.max(Template.version)).where(Template.bank_code == bank)).scalar() or 0
    row = Template(bank_code=bank, version=latest + 1, status="draft",
                   field_map=field_map, header_columns=payload.get("header_columns"))
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "version": row.version, "bank_code": row.bank_code}

