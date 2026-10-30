"""模板的存取与发布（管理页面用）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Template
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
