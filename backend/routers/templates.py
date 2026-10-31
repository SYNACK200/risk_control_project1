"""模板的存取与发布（管理页面用）。"""
from __future__ import annotations

import json
from pathlib import Path as _Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import Task, Template, Txn, now
from db.session import get_session
from helpers.security import require_banker
from services.analysis import infer_from_marks
from services import template_layout as tlayout

router = APIRouter(prefix="/templates", tags=["templates"], dependencies=[Depends(require_banker)])


class TemplateIn(BaseModel):
    bank_code: str
    field_map: dict
    header_columns: list | None = None
    version: int = 1


@router.get("")
def list_templates(bank_code: str | None = None, include_deleted: bool = False,
                   db: Session = Depends(get_session)):
    stmt = select(Template).order_by(Template.bank_code, Template.version.desc())
    if not include_deleted:
        stmt = stmt.where(Template.deleted_at.is_(None))
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


_META_PATTERNS = [
    ("account_no", r"(?:卡号|账号|账户|本方账号)\s*[:：]?\s*([0-9*]{8,})"),
    ("account_name", r"(?:户名|姓名|账户名)\s*[:：]?\s*([^\s，,；;]{2,20})"),
    ("period", r"(?:起止日期|交易期间|对账期间)\s*[:：]?\s*"
               r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2})\s*(?:至|—|－|~|到)\s*"
               r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2})"),
    ("currency", r"(人民币|美元|欧元|港币|CNY|USD|EUR|HKD)"),
]


def _extract_meta(page_text: str, words: list[dict], page_w: float, page_h: float) -> dict:
    """从首页文本里抽账号/户名/期间/币种，并给出命中文字的位置（归一化）。"""
    import re as _re

    out: dict[str, dict] = {}
    flat = _re.sub(r"[ \t]+", " ", page_text)
    for field, pattern in _META_PATTERNS:
        m = _re.search(pattern, flat)
        if not m:
            continue
        value = m.group(1) if field != "period" else f"{m.group(1)} ~ {m.group(2)}"
        key = m.group(0)[:24]
        spot = None
        for w in words:
            if w["text"] and (w["text"][:6] in key or key[:6] in w["text"]):
                spot = w
                break
        rect = None
        if spot and page_w and page_h:
            rect = {
                "x": round(spot["x0"] / page_w, 4),
                "y": round(spot["top"] / page_h, 4),
                "w": round(max(0.02, (spot["x1"] - spot["x0"]) / page_w), 4),
                "h": round(max(0.015, (spot["bottom"] - spot["top"]) / page_h), 4),
            }
        out[field] = {"value": value.strip(), "rect": rect}
    return out


@router.post("/decrypt")
def decrypt_pdf(file: UploadFile = File(...), password: str | None = Form(None)):
    """把带口令的 PDF 解密后原样返回，供标注/预读/试解析统一使用解密件。"""
    from fastapi.responses import Response
    from starlette.concurrency import run_in_threadpool

    import pymupdf

    data = file.file.read()
    if not data:
        raise HTTPException(400, "文件为空")
    if data[:4] != b"%PDF":
        raise HTTPException(422, detail={"code": "E_PARAM", "message": "只支持 PDF"})
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        if doc.needs_pass and (not password or doc.authenticate(password) <= 0):
            raise HTTPException(400, detail={"code": "E_ENCRYPT", "message": "口令不正确"})
        plain = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_NONE)
    finally:
        doc.close()
    return Response(content=plain, media_type="application/pdf",
                    headers={"X-Decrypted": "1"})


@router.post("/probe")
def probe_template(file: UploadFile = File(...), password: str | None = Form(None)):
    """标注前的 OCR 预读：识别银行、表头词，并直接给出建议标注（只读第 1 页，不落库）。"""
    data = file.file.read()
    if not data:
        raise HTTPException(400, "文件为空")
    if data[:4] != b"%PDF":
        raise HTTPException(422, detail={"code": "E_PARAM",
                                         "message": "预读只支持 PDF 电子件（图片件请直接框选）"})
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    if doc.needs_pass:
        if not password or doc.authenticate(password) <= 0:
            doc.close()
            raise HTTPException(400, detail={"code": "E_ENCRYPT", "message": "PDF 需要打开口令"})
    page = doc[0]
    matrix = page.rotation_matrix
    words: list[dict] = []
    for x0, y0, x1, y1, text, *_rest in page.get_text("words"):
        if not text.strip():
            continue
        rect = pymupdf.Rect(x0, y0, x1, y1) * matrix
        words.append({"x0": rect.x0, "x1": rect.x1, "top": rect.y0,
                      "bottom": rect.y1, "text": text})
    full_text = page.get_text() or ""
    page_size = {"width": round(page.rect.width, 1), "height": round(page.rect.height, 1)}
    rotation = int(page.rotation)
    doc.close()

    from algorithm.algo.preread import BANK_ALIASES
    from algorithm.ocr.infer import FIELD_BY_HEADER, detect_header_row

    bank_name = bank_code = None
    for alias, code in BANK_ALIASES:
        if alias in full_text:
            bank_name, bank_code = alias, code
            break

    header = detect_header_row({0: words})
    headers = [{"text": w["text"], "x0": round(w["x0"], 1), "x1": round(w["x1"], 1),
                "x": round((w["x0"] + w["x1"]) / 2, 1),
                "y": round((w["top"] + w["bottom"]) / 2, 1)} for w in header]

    # 列边界：相邻表头词之间如果留有空隙（>6pt），取空隙中点作分界；
    # 没有空隙说明表头被拆成多个词（如「收入 支出 金额」），按两词中心均值切。
    boundaries = []
    for left, right in zip(header, header[1:]):
        gap = right["x0"] - left["x1"]
        mid = (left["x1"] + right["x0"]) / 2 if gap > 6 else (left["x1"] + right["x0"]) / 2
        boundaries.append({"after": left["text"], "before": right["text"],
                           "gap": round(gap, 1), "x": round(mid, 1)})

    suggestions: list[dict] = []
    used: set[str] = set()
    for w in header:
        field = FIELD_BY_HEADER.get(w["text"].strip())
        if not field or field in used:
            continue
        used.add(field)
        suggestions.append({"field": field, "column": w["text"],
                            "x": round((w["x0"] + w["x1"]) / 2, 1),
                            "y": round((w["top"] + w["bottom"]) / 2, 1)})

    meta = _extract_meta(full_text, words, page_size["width"], page_size["height"])
    return {"bank_name": bank_name, "bank_code": bank_code, "rotation": rotation,
            "page_size": page_size, "header_found": len(header) > 0,
            "headers": headers, "suggestions": suggestions, "meta": meta,
            "boundaries": boundaries}


@router.post("/infer")
def infer_template_api(
    file: UploadFile = File(...),
    marks: str = Form(..., description="JSON 数组，如 [{\"field\":\"amount\",\"page\":0,\"x\":530,\"y\":60}]"),
    bank_code: str = Form("UNKNOWN"),
    password: str | None = Form(None),
    save_draft: bool = Form(False),
    allow_invalid: bool = Form(False, description="反验未通过时是否仍保存为草稿"),
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

            tmp = _Path(tempfile.gettempdir()) / "infer_plain.pdf"
            doc.save(tmp, encryption=pymupdf.PDF_ENCRYPT_NONE)
            data = tmp.read_bytes()
    try:
        result = infer_from_marks(data, parsed_marks, bank_code=bank_code)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    payload = {
        "bank_code": bank_code.upper(),
        "valid": result["valid"],
        "field_map": result["field_map"],
        "provenance": result["provenance"],
        "columns": result["columns"],
        "warnings": result["warnings"],
    }
    layout = None
    try:
        layout = tlayout.build_layout(data, parsed_marks, result["columns"], result["field_map"])
    except Exception:  # noqa: BLE001 - 布局失败不影响建模板
        layout = None
    payload["layout"] = layout

    payload["valid"] = result["valid"]
    if save_draft:
        file_id = None
        try:
            file_id = _store_sample(db, file.filename or "template_sample.pdf", data)
        except Exception:  # noqa: BLE001
            file_id = None
        row = Template(bank_code=bank_code.upper(), version=1, status="draft",
                       field_map=result["field_map"],
                       header_columns=[c.get("alias") for c in result["columns"]],
                       sample_file_id=file_id, layout=layout)
        db.add(row); db.commit(); db.refresh(row)
        payload["template_id"] = row.id
        payload["saved_invalid"] = not result["valid"]
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
    if row.deleted_at is not None:
        return {"deleted": template_id, "soft": True, "used": 0, "message": "该模板已从列表移除"}
    used = db.execute(select(func.count(Task.id)).where(Task.template_id == template_id)).scalar() or 0
    if used:
        # 有历史流水引用：不能物理删除，否则报告溯源断链；改为从列表移除（历史保留）
        row.deleted_at = now()
        row.status = "disabled"
        db.commit()
        return {"deleted": template_id, "soft": True, "used": used,
                "message": f"该模板被 {used} 条流水引用，已从列表移除（历史解析记录仍保留），未做物理删除"}
    db.delete(row)
    db.commit()
    return {"deleted": template_id, "soft": False, "used": 0, "message": "已删除"}


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


def _store_sample(db: Session, filename: str, data: bytes) -> int:
    """把建模板用的样本存进 file_obj + 磁盘，供之后渲染「当时的框选」。"""
    import hashlib

    from db.models import FileObj

    digest = hashlib.sha256(data).hexdigest()
    exists = db.execute(select(FileObj).where(FileObj.sha256 == digest)).scalars().first()
    if exists:
        return exists.id
    storage = _Path(__file__).resolve().parents[1] / "storage" / "uploads"
    storage.mkdir(parents=True, exist_ok=True)
    path = storage / (digest + ".pdf")
    if not path.exists():
        path.write_bytes(data)
    row = FileObj(sha256=digest, mime="application/pdf", carrier="electronic",
                  pages=None, has_text_layer=True, storage_path=str(path))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


@router.get("/{template_id}/layout")
def get_template_layout(template_id: int, db: Session = Depends(get_session)):
    """模板当时的框选（页面尺寸 + 每个字段的方框）与样本是否可回看。"""
    row = db.get(Template, template_id)
    if row is None:
        raise HTTPException(404, "模板不存在")
    return {
        "template_id": row.id,
        "has_sample": row.sample_file_id is not None,
        "layout": row.layout,
        "field_map": row.field_map,
        "header_columns": row.header_columns,
    }


@router.get("/{template_id}/layout.png")
def get_template_layout_png(template_id: int, page: int = 0, dpi: int = 140, db: Session = Depends(get_session)):
    """渲染「当时的框选」：原页面 + 方框 + 字段名，直接给工作人员看。"""
    from fastapi.responses import Response

    from db.models import FileObj

    row = db.get(Template, template_id)
    if row is None:
        raise HTTPException(404, "模板不存在")
    if not row.sample_file_id or not row.layout:
        raise HTTPException(404, detail={"code": "E_NO_SAMPLE", "message": "该模板没有可回看的样本（旧版本模板）"})
    file_row = db.get(FileObj, row.sample_file_id)
    if file_row is None or not file_row.storage_path:
        raise HTTPException(404, detail={"code": "E_NO_SAMPLE", "message": "样本文件已不存在"})
    data = _Path(file_row.storage_path).read_bytes()
    png = tlayout.render_page_png(data, row.layout, max(0, page), dpi=max(80, min(200, dpi)))
    return Response(content=png, media_type="image/png")
