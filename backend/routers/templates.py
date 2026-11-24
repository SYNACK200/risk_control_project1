"""模板的存取与发布（管理页面用）。"""
from __future__ import annotations

import json
from pathlib import Path as _Path

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import AuditLog, Task, Template, Txn, now
from db.session import get_session
from helpers.security import require_admin, require_banker
from services.analysis import infer_from_marks
from services import template_layout as tlayout

router = APIRouter(prefix="/templates", tags=["templates"], dependencies=[Depends(require_banker)])


class TemplateIn(BaseModel):
    bank_code: str
    field_map: dict
    header_columns: list | None = None
    layout: dict | None = None
    required_fields: list[str] | None = None
    sample_file_id: int | None = None
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
    # 聚合每个模板的历史任务使用次数与完成率，供模板列表直观展示
    usage_map: dict[int, tuple[int, int]] = {}
    if rows:
        tids = [t.id for t in rows]
        stat_rows = db.execute(
            select(Task.template_id, Task.status, func.count(Task.id))
            .where(Task.template_id.in_(tids), Task.deleted_at.is_(None))
            .group_by(Task.template_id, Task.status)
        ).all()
        for tid, st, cnt in stat_rows:
            tot, done = usage_map.get(int(tid), (0, 0))
            tot += int(cnt)
            if st == "DONE":
                done += int(cnt)
            usage_map[int(tid)] = (tot, done)
    out = []
    for t in rows:
        tot, done = usage_map.get(t.id, (0, 0))
        out.append({
            "id": t.id, "bank_code": t.bank_code, "version": t.version,
            "status": t.status, "field_map": t.field_map, "header_columns": t.header_columns,
            "required_fields": t.required_fields,
            "has_layout": bool(t.layout and (t.layout.get("tables") or t.layout.get("boxes"))),
            "has_sample": t.sample_file_id is not None,
            "tasks_total": tot,
            "success_rate": round(done / tot, 4) if tot > 0 else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            "deleted_at": t.deleted_at.isoformat() if t.deleted_at else None,
        })
    return out


@router.post("")
def create_template(payload: TemplateIn, db: Session = Depends(get_session)):
    bank = payload.bank_code.upper()
    latest = db.execute(
        select(func.max(Template.version)).where(Template.bank_code == bank)
    ).scalar() or 0
    row = Template(
        bank_code=bank,
        version=latest + 1,
        status="draft",
        field_map=payload.field_map,
        header_columns=payload.header_columns,
        layout=payload.layout,
        required_fields=payload.required_fields,
        sample_file_id=payload.sample_file_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _audit_template(db, "create_template", row.id, f"新建 {row.bank_code} v{row.version}")
    db.commit()
    return {"id": row.id, "version": row.version, "status": row.status}


@router.post("/{template_id}/publish", dependencies=[Depends(require_admin)])
def publish_template(template_id: int, db: Session = Depends(get_session)):
    row = db.get(Template, template_id)
    if row is None:
        raise HTTPException(404, "模板不存在")
    if row.deleted_at is not None:
        raise HTTPException(400, detail={"code": "E_STATE", "message": "已删除的模板不能启用，请先恢复"})
    # 同一银行只允许一个启用版本
    others = db.execute(
        select(Template).where(Template.bank_code == row.bank_code, Template.deleted_at.is_(None))
    ).scalars().all()
    for o in others:
        if o.id == row.id:
            o.status = "enabled"
        elif o.status == "enabled":
            o.status = "disabled"
            _audit_template(db, "disable_template", o.id, f"被新版本替代：{o.bank_code} v{o.version}")
    _audit_template(db, "publish_template", row.id, f"启用 {row.bank_code} v{row.version}")
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


def _extract_meta(page_text: str, words: list[dict], page_w: float, page_h: float,
                  header_y: float | None = None) -> dict:
    """从首页页眉文本里抽账号/户名/期间/币种，并合并同行命中词的完整外接框（归一化）。

    当提供 header_y（表头行上沿 pt）时，仅在表头上方页眉区检索，避免误框到表格首行数据（如币种列）。
    """
    import re as _re

    # 按 y 聚类成行，且优先限制在表头上方页眉区
    header_words = [
        w for w in words
        if w.get("text") and (header_y is None or w["bottom"] <= header_y + 4.0)
    ]
    lines: list[list[dict]] = []
    for w in sorted(header_words, key=lambda item: ((item["top"] + item["bottom"]) / 2, item["x0"])):
        cy = (w["top"] + w["bottom"]) / 2
        if lines:
            prev_cy = sum((p["top"] + p["bottom"]) / 2 for p in lines[-1]) / len(lines[-1])
            if abs(cy - prev_cy) <= 4.5:
                lines[-1].append(w)
                continue
        lines.append([w])
    for line in lines:
        line.sort(key=lambda item: item["x0"])

    header_text = "\n".join(" ".join(w["text"] for w in line) for line in lines) if lines else page_text
    flat = _re.sub(r"[ \t]+", " ", header_text)

    out: dict[str, dict] = {}
    for field, pattern in _META_PATTERNS:
        m = _re.search(pattern, flat)
        if not m:
            continue
        value = m.group(1) if field != "period" else f"{m.group(1)} ~ {m.group(2)}"
        matched_words: list[dict] = []
        for line in lines:
            line_str = " ".join(w["text"] for w in line)
            lm = _re.search(pattern, line_str)
            if not lm:
                continue
            # 把正则在 line_str 中的字符区间映射回对应的所有词，合并其外接框
            span_start, span_end = lm.span()
            cursor = 0
            for w in line:
                w_start = cursor
                w_end = cursor + len(w["text"])
                if w_end > span_start and w_start < span_end:
                    matched_words.append(w)
                cursor = w_end + 1
            if matched_words:
                break
        rect = None
        if matched_words and page_w and page_h:
            x0 = min(w["x0"] for w in matched_words)
            y0 = min(w["top"] for w in matched_words)
            x1 = max(w["x1"] for w in matched_words)
            y1 = max(w["bottom"] for w in matched_words)
            rect = {
                "x": round(max(0.0, x0 / page_w), 4),
                "y": round(max(0.0, y0 / page_h), 4),
                "w": round(min(1.0 - max(0.0, x0 / page_w), max(0.02, (x1 - x0) / page_w)), 4),
                "h": round(min(1.0 - max(0.0, y0 / page_h), max(0.015, (y1 - y0) / page_h)), 4),
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

    # 扫描每一页有没有明细表头。
    # 之前只读第 0 页，用户没法知道「第 2 页起是不是同一版式」——
    # 而模板能否复用整套解析，全看这一点。
    pages_info = []
    for idx, pg in enumerate(doc):
        try:
            if idx == 0:
                ws0 = words
            else:
                ws0 = []
                mtx = pg.rotation_matrix
                for x0, y0, x1, y1, tx, *_r in pg.get_text("words"):
                    if not tx.strip():
                        continue
                    rr = pymupdf.Rect(x0, y0, x1, y1) * mtx
                    ws0.append({"x0": rr.x0, "x1": rr.x1, "top": rr.y0, "bottom": rr.y1, "text": tx})
            try:
                from algorithm.ocr.infer import detect_header_row as _dhr
                hdr0 = _dhr({idx: ws0})
            except Exception:
                hdr0 = []
            pages_info.append({
                "page_no": idx,
                "words": len(ws0),
                "header_words": len(hdr0),
                # ≥2 个表头词才算这一页有明细表头；1 个可能是页眉里的「交易日期」字样
                "has_header": len(hdr0) >= 2,
            })
        except Exception:
            pages_info.append({"page_no": idx, "words": 0, "header_words": 0, "has_header": False})

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
                "y": round((w["top"] + w["bottom"]) / 2, 1),
                "top": round(w["top"], 1), "bottom": round(w["bottom"], 1)} for w in header]

    # 列边界：相邻表头词之间如果留有空隙（>6pt），取空隙中点作分界；
    # 没有空隙说明表头紧挨，按两词中心均值切。
    boundaries = []
    for left, right in zip(header, header[1:]):
        gap = right["x0"] - left["x1"]
        mid = (
            (left["x1"] + right["x0"]) / 2
            if gap > 6
            else ((left["x0"] + left["x1"]) / 2 + (right["x0"] + right["x1"]) / 2) / 2
        )
        boundaries.append({"after": left["text"], "before": right["text"],
                           "gap": round(gap, 1), "x": round(mid, 1)})

    pw = page_size["width"] or 1.0
    suggestions: list[dict] = []
    used: set[str] = set()
    for idx, w in enumerate(header):
        field = FIELD_BY_HEADER.get(w["text"].strip())
        if not field or field in used:
            continue
        used.add(field)
        word_w = max(w["x1"] - w["x0"], 12.0)
        col_x0 = boundaries[idx - 1]["x"] if idx > 0 else max(0.0, w["x0"] - 0.2 * word_w)
        col_x1 = boundaries[idx]["x"] if idx < len(boundaries) else min(pw, w["x1"] + 0.5 * word_w)
        if col_x1 <= col_x0:
            col_x0, col_x1 = w["x0"], max(w["x1"], w["x0"] + 12.0)
        col_x_norm = round(max(0.0, col_x0 / pw), 4)
        col_w_norm = round(min(1.0 - col_x_norm, max(0.02, (col_x1 - col_x0) / pw)), 4)
        suggestions.append({
            "field": field, "column": w["text"],
            "x": round((w["x0"] + w["x1"]) / 2, 1),
            "y": round((w["top"] + w["bottom"]) / 2, 1),
            "x0": round(col_x0, 1), "x1": round(col_x1, 1),
            "col_x": col_x_norm, "col_w": col_w_norm,
        })

    header_top_pt = min((h["top"] for h in headers), default=None)
    meta = _extract_meta(full_text, words, page_size["width"], page_size["height"], header_y=header_top_pt)

    # 表格区：表头行上沿再往上留 2pt，到页面底部留 2% —— 由系统给出，不让用户画
    table_area = None
    if header:
        top = min(h["top"] for h in headers)
        table_area = {
            "x": round(max(0.0, min(h["x0"] for h in headers) / page_size["width"] - 0.01), 4),
            "y": round(max(0.0, top / page_size["height"] - 0.004), 4),
            "w": round(min(1.0, (max(h["x1"] for h in headers) / page_size["width"]) - (min(h["x0"] for h in headers) / page_size["width"]) + 0.02), 4),
            "h": round(max(0.05, 0.98 - max(0.0, top / page_size["height"] - 0.004)), 4),
            "header_y": round(max(h["bottom"] for h in headers) / page_size["height"], 4),
        }

    return {"bank_name": bank_name, "bank_code": bank_code, "rotation": rotation,
            "page_size": page_size, "header_found": len(header) > 0,
            "headers": headers, "suggestions": suggestions, "meta": meta,
            "boundaries": boundaries, "table_area": table_area,
            "page_count": len(pages_info), "pages": pages_info}


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

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                tmp = _Path(tf.name)
            try:
                doc.save(tmp, encryption=pymupdf.PDF_ENCRYPT_NONE)
                data = tmp.read_bytes()
            finally:
                tmp.unlink(missing_ok=True)
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

    # 用这份临时模板把整份文件试跑一遍，返回逐页情况：
    # 用户要看到的不只是「总笔数」，还有「第 2、3…页模板还好不好用」。
    try:
        from algorithm.ocr.models import Template as _PT
        from algorithm.ocr.parse import parse as _parse

        tpl = _PT(bank_code=bank_code.upper(), version=0,
                  field_map=dict(result["field_map"] or {}), layout=layout)
        parsed = _parse(data, tpl)
        from collections import Counter as _Counter

        per_page = _Counter(t.page_no for t in parsed.transactions)
        hdr_pages = {h.page_no for h in (parsed.headers or []) if any([
            getattr(h, "account_no", None) is not None,
            getattr(h, "account_name", None) is not None,
            getattr(h, "period_start", None) is not None,
        ])}
        payload["preview"] = {
            "txn_count": len(parsed.transactions),
            "page_count": parsed.page_count,
            "base_page": int(parsed_marks[0].get("page") or 0),
            "pages": [
                {"page_no": pno + 1, "rows": per_page.get(pno + 1, 0), "header_found": (pno + 1) in hdr_pages}
                for pno in range(parsed.page_count or 0)
            ],
        }
    except Exception as exc:  # noqa: BLE001 - 试跑失败不影响建模板
        payload["preview"] = {"error": str(exc)[:120]}

    payload["valid"] = result["valid"]
    if save_draft and not result["valid"] and not allow_invalid:
        payload["saved"] = False
        payload["saved_invalid"] = False
        payload["reject_reason"] = "反验未通过，已拦截草稿入库（如需强制保存请勾选允许保存未通过草稿）"
        return payload
    if save_draft:
        file_id = None
        try:
            file_id = _store_sample(db, file.filename or "template_sample.pdf", data)
        except Exception:  # noqa: BLE001
            file_id = None
        _latest = db.execute(
            select(func.max(Template.version)).where(Template.bank_code == bank_code.upper())
        ).scalar() or 0
        row = Template(bank_code=bank_code.upper(), version=_latest + 1, status="draft",
                       field_map=result["field_map"],
                       header_columns=[c.get("alias") for c in result["columns"]],
                       sample_file_id=file_id, layout=layout)
        db.add(row); db.commit(); db.refresh(row)
        payload["template_id"] = row.id
        payload["saved_invalid"] = not result["valid"]
    return payload

class TemplatePatch(BaseModel):
    required_fields: list[str] | None = None
    bank_code: str | None = None
    field_map: dict | None = None
    header_columns: list | None = None
    # 框画范围（表格区 / 表头高度 / 每列 x·w / 页面尺寸）。
    # 模板只有 field_map 时，列边界要靠「按表头词重新推算」，版式一变就错位；
    # 存下 layout 后，解析可以直接用这份几何，也让「改框画范围」成为可能。
    layout: dict | None = None


@router.put("/{template_id}", dependencies=[Depends(require_admin)])
def update_template(template_id: int, payload: TemplatePatch, db: Session = Depends(get_session)):
    # 改模板 = 出新版本：旧版本保留为 disabled，历史可追溯
    # 注意：import 必须放在函数最前面。放在下面会让 Python 把 _dt_now 当局部变量，
    # 上面第一次使用时就 UnboundLocalError —— 这正是「保存为新版本显示失败」的原因。
    from datetime import datetime as _dt_now  # noqa: PLC0415

    row = db.get(Template, template_id)
    if row is None or row.deleted_at is not None:
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
        sample_file_id=row.sample_file_id,
        layout=payload.layout if payload.layout is not None else row.layout,
        required_fields=payload.required_fields if payload.required_fields is not None else row.required_fields,
        updated_at=_dt_now.utcnow(),
    )
    old_status = row.status
    row.status = "disabled"
    row.updated_at = _dt_now.utcnow()
    db.add(new_row)
    db.commit()
    db.refresh(new_row)
    return {"id": new_row.id, "version": new_row.version, "status": new_row.status, "previous_id": row.id,
            "previous_status": old_status}


@router.get("/{template_id}", dependencies=[Depends(require_banker)])
def get_template(template_id: int, db: Session = Depends(get_session)):
    """取单个模板（含 layout 与 field_map）：模板详情页与「改框画范围」都要用。"""
    row = db.get(Template, template_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(404, "模板不存在")
    return {
        "id": row.id, "bank_code": row.bank_code, "version": row.version,
        "status": row.status, "field_map": row.field_map or {},
        "header_columns": row.header_columns, "layout": row.layout,
        "required_fields": row.required_fields,
        "sample_file_id": row.sample_file_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/{template_id}/sample", dependencies=[Depends(require_banker)])
def template_sample(template_id: int, db: Session = Depends(get_session)):
    """取建模板时用的样本文件：模板详情页「改框画范围」要用同一份样本回看。"""
    from fastapi.responses import FileResponse

    from db.models import FileObj

    row = db.get(Template, template_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(404, "模板不存在")
    if not row.sample_file_id:
        raise HTTPException(404, detail={"code": "E_NOT_FOUND",
                                         "message": "这个模板没有保存样本文件，无法回看框选范围"})
    f = db.get(FileObj, row.sample_file_id)
    if f is None or not f.storage_path:
        raise HTTPException(404, detail={"code": "E_NOT_FOUND", "message": "样本文件已被清理"})
    path = _Path(f.storage_path)
    if not path.exists():
        raise HTTPException(404, detail={"code": "E_NOT_FOUND", "message": "样本文件已被清理"})
    return FileResponse(path, filename=f"template-{template_id}-sample{path.suffix}")


@router.post("/{template_id}/duplicate", dependencies=[Depends(require_admin)])
def duplicate_template(template_id: int, db: Session = Depends(get_session)):
    row = db.get(Template, template_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(404, "模板不存在")
    latest = db.execute(select(func.max(Template.version)).where(
        Template.bank_code == row.bank_code)).scalar() or row.version
    copy = Template(
        bank_code=row.bank_code,
        version=latest + 1,
        status="draft",
        field_map=row.field_map,
        header_columns=row.header_columns,
        layout=row.layout,
        required_fields=row.required_fields,
        sample_file_id=row.sample_file_id,
    )
    db.add(copy)
    db.commit()
    db.refresh(copy)
    _audit_template(db, "duplicate_template", copy.id, f"复制自 v{row.version} (#{row.id})")
    db.commit()
    return {"id": copy.id, "version": copy.version}


@router.post("/{template_id}/disable", dependencies=[Depends(require_admin)])
def disable_template(template_id: int, db: Session = Depends(get_session)):
    row = db.get(Template, template_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(404, "模板不存在")
    row.status = "disabled"
    db.commit()
    return {"id": row.id, "status": row.status}


@router.delete("/{template_id}", dependencies=[Depends(require_admin)])
def delete_template(template_id: int, db: Session = Depends(get_session)):
    row = db.get(Template, template_id)
    if row is None:
        raise HTTPException(404, "模板不存在")
    if row.deleted_at is not None:
        return {"deleted": template_id, "soft": True, "used": 0, "message": "该模板已从列表移除"}
    used = db.execute(select(func.count(Task.id)).where(Task.template_id == template_id)).scalar() or 0
    # 一律软删除：模板是花了人工在样本上画出来的，物理删掉就再也找不回来。
    # 之前对「无任务引用」的模板做物理删除，导致 ICBC / CMB / CGB 三个模板被删后无法恢复，
    # 只能重新标注。现在统一进回收站，可恢复。
    row.deleted_at = now()
    row.status = "disabled"
    _audit_template(db, "delete_template", template_id,
                    f"软删除 {row.bank_code} v{row.version}（引用 {used} 个任务，可恢复）")
    db.commit()
    return {"deleted": template_id, "soft": True, "used": used,
            "message": "已移入回收站，可在模板库「回收站」里恢复"}


@router.post("/{template_id}/restore", dependencies=[Depends(require_admin)])
def restore_template(template_id: int, db: Session = Depends(get_session)):
    row = db.get(Template, template_id)
    if row is None:
        raise HTTPException(404, "模板不存在")
    if row.deleted_at is None:
        return {"id": template_id, "restored": False, "message": "该模板未在回收站"}
    row.deleted_at = None
    _audit_template(db, "restore_template", template_id,
                    f"从回收站恢复 {row.bank_code} v{row.version}")
    db.commit()
    return {"id": template_id, "restored": True, "message": "已恢复（状态为停用，需要时再启用）"}


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


def _run_preview(raw: bytes, bank_code: str, version: int, field_map: dict,
                 layout: dict | None, required_fields: list[str] | None, template_id: int | None = None) -> dict:
    from collections import Counter

    from algorithm.ocr.parse import parse
    from services.template_checks import missing_required
    from services.template_parse import build_template

    tpl = build_template(bank_code=bank_code, version=version, field_map=field_map, layout=layout)
    parsed = parse(raw, tpl)
    per_page = Counter(t.page_no or 1 for t in parsed.transactions)
    header_by_page = {h.page_no: h for h in (parsed.headers or [])}
    pages = []
    for pno in range(1, (parsed.page_count or 0) + 1):
        h = header_by_page.get(pno)
        has_header = bool(h and any([
            getattr(h, "account_no", None) is not None,
            getattr(h, "account_name", None) is not None,
            getattr(h, "period_start", None) is not None,
        ]))
        pages.append({
            "page_no": pno,
            "rows": per_page.get(pno, 0),
            "header_found": has_header,
            "columns": 0,
        })

    rows = [
        {
            "txn_date": t.txn_date,
            "summary": t.summary,
            "counterparty": getattr(t, "counterparty_name", None),
            "reference_no": getattr(t, "reference_no", None),
            "direction": t.direction,
            "amount": None if t.amount is None else str(t.amount),
            "balance": None if t.balance is None else str(t.balance),
            "page_no": t.page_no,
            "extra": getattr(t, "extra", None),
        }
        for t in parsed.transactions[:15]
    ]
    mapped = set((field_map or {}).keys())
    required = list(required_fields or [])
    present = set(required) & mapped
    missing = missing_required(field_map, required)
    empty = []
    for field in required:
        if field in missing:
            continue
        if field in ("txn_date", "amount", "balance", "summary"):
            if not any(getattr(t, field, None) not in (None, "") for t in parsed.transactions):
                empty.append(field)

    def _first_header_val(field_name: str) -> str | None:
        for hdr in (parsed.headers or []):
            hf = getattr(hdr, field_name, None)
            val = getattr(hf, "value", None) if hf is not None else hf
            if val:
                return str(val)
        return None

    extra_meta: dict[str, str] = {}
    for hdr in (parsed.headers or []):
        for k, hf in (getattr(hdr, "extra_fields", None) or {}).items():
            val = getattr(hf, "value", None)
            if val and k not in extra_meta:
                extra_meta[k] = str(val)

    return {
        "template_id": template_id,
        "txn_count": len(parsed.transactions),
        "page_count": parsed.page_count,
        "pages": pages,
        "warnings": (parsed.warnings or [])[:8],
        "rows": rows,
        "meta": {
            "account_no": _first_header_val("account_no"),
            "account_name": _first_header_val("account_name"),
            "bank_branch": _first_header_val("bank_branch"),
            "account_type": _first_header_val("account_type"),
            "currency": _first_header_val("currency"),
            "period_start": _first_header_val("period_start"),
            "period_end": _first_header_val("period_end"),
            **extra_meta,
        },
        "extra_meta": extra_meta,
        "required_fields": required,
        "missing_columns": missing,
        "empty_columns": empty,
        "present_columns": sorted(present),
    }


@router.post("/preview-draft")
def preview_draft_template(
    bank_code: str = Form("UNKNOWN"),
    field_map: str = Form("{}"),
    layout: str = Form("{}"),
    required_fields: str = Form("[]"),
    password: str | None = Form(None),
    file: UploadFile = File(...),
):
    """未保存先试跑：按画布当前的 layout + field_map 立刻试解析，把真实笔数、样例行与单值反馈给标注员。"""
    from services.analysis import EncryptedFile, plain_bytes

    data = file.file.read()
    if not data:
        raise HTTPException(400, detail={"code": "E_PARAM", "message": "文件为空"})
    try:
        raw = plain_bytes(data, password)
    except EncryptedFile as exc:
        raise HTTPException(400, detail={"code": "E_ENCRYPT", "message": str(exc)}) from exc
    try:
        fmap = json.loads(field_map) if field_map else {}
        lay = json.loads(layout) if layout else {}
        req = json.loads(required_fields) if required_fields else []
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, detail={"code": "E_PARAM", "message": f"标注 JSON 不合法：{exc}"}) from exc
    return _run_preview(raw, bank_code.upper(), 0, fmap, lay, req, template_id=None)


@router.post("/save-from-canvas")
def save_template_from_canvas(
    bank_code: str = Form(...),
    field_map: str = Form(...),
    layout: str = Form(...),
    required_fields: str = Form("[]"),
    header_columns: str | None = Form(None),
    template_id: int | None = Form(None),
    publish: bool = Form(False),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_session),
    user=Depends(require_banker),
):
    """画布一站式保存：只产生一个新版本，同时把样本文件与 layout/required_fields 存齐；管理员可直接启用。"""
    try:
        fmap = json.loads(field_map)
        lay = json.loads(layout)
        req = json.loads(required_fields) if required_fields else []
        hcols = json.loads(header_columns) if header_columns else None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, detail={"code": "E_PARAM", "message": f"模板 JSON 不合法：{exc}"}) from exc

    if not isinstance(fmap, dict) or not fmap:
        raise HTTPException(400, detail={"code": "E_PARAM", "message": "至少要标出一列字段再保存"})

    bank = bank_code.strip().upper()
    if not bank:
        raise HTTPException(400, detail={"code": "E_PARAM", "message": "缺少银行代码"})

    sample_file_id: int | None = None
    prev_row = None
    if template_id is not None:
        prev_row = db.get(Template, template_id)
        if prev_row is None or prev_row.deleted_at is not None:
            raise HTTPException(404, detail={"code": "E_NOT_FOUND", "message": "模板不存在或已删除"})
        sample_file_id = prev_row.sample_file_id
    if file is not None:
        data = file.file.read()
        if data:
            sample_file_id = _store_sample(db, file.filename or "sample.pdf", data)

    latest = db.execute(
        select(func.max(Template.version)).where(Template.bank_code == bank)
    ).scalar() or 0

    can_publish = bool(publish and getattr(user, "is_admin", False))
    new_row = Template(
        bank_code=bank,
        version=latest + 1,
        status="enabled" if can_publish else "draft",
        field_map=fmap,
        header_columns=hcols or list(fmap.values()),
        layout=lay,
        required_fields=req,
        sample_file_id=sample_file_id,
    )
    if can_publish:
        others = db.execute(
            select(Template).where(Template.bank_code == bank, Template.deleted_at.is_(None))
        ).scalars().all()
        for o in others:
            if o.status == "enabled":
                o.status = "disabled"
                _audit_template(db, "disable_template", o.id, f"被新版本替代：{bank} v{o.version}")

    db.add(new_row)
    db.commit()
    db.refresh(new_row)
    _audit_template(
        db,
        "publish_template" if can_publish else "create_template",
        new_row.id,
        f"画布保存 {bank} v{new_row.version}" + ("（已直接启用）" if can_publish else "（草稿）"),
    )
    db.commit()
    return {
        "id": new_row.id,
        "bank_code": new_row.bank_code,
        "version": new_row.version,
        "status": new_row.status,
        "has_sample": new_row.sample_file_id is not None,
    }


@router.post("/{template_id}/preview")
def preview_template(template_id: int, file: UploadFile = File(...), password: str | None = Form(None),
                     db: Session = Depends(get_session)):
    # 用该模板试解析一份样例，不落库
    row = db.get(Template, template_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(404, "模板不存在")
    data = file.file.read()
    if not data:
        raise HTTPException(400, "文件为空")
    from services.analysis import EncryptedFile, plain_bytes

    try:
        raw = plain_bytes(data, password)
    except EncryptedFile as exc:
        raise HTTPException(400, detail={"code": "E_ENCRYPT", "message": str(exc)}) from exc
    return _run_preview(
        raw, row.bank_code, row.version,
        row.field_map or {}, row.layout, row.required_fields, template_id=row.id,
    )


@router.get("/{template_id}/export")
def export_template(template_id: int, db: Session = Depends(get_session)):
    row = db.get(Template, template_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(404, "模板不存在")
    payload = {
        "bank_code": row.bank_code,
        "version": row.version,
        "field_map": row.field_map,
        "header_columns": row.header_columns,
        "layout": row.layout,
        "required_fields": row.required_fields,
    }
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=template-{row.bank_code}-v{row.version}.json"},
    )


def _normalize_import_item(raw: dict) -> dict:
    """兼容三种模板 JSON 格式并归一化为标准入库结构：
    1) 平台导出格式 {bank_code, field_map, layout, header_columns, required_fields}
    2) FieldMapV1 / schema_version=1 格式（如 cmb_template.json：顶层 tables/meta_boxes/page_size，无 field_map）
    3) 列序号映射格式（如 icbc_template.json：{bank_code, field_map, header_columns}）
    """
    if not isinstance(raw, dict):
        raise HTTPException(400, detail={"code": "E_PARAM", "message": "模板 JSON 必须是对象"})
    bank = str(raw.get("bank_code") or "").strip().upper()
    if not bank:
        raise HTTPException(400, detail={"code": "E_PARAM", "message": "缺少 bank_code（银行代码）"})

    layout = raw.get("layout")
    is_v1_top = (not layout) and (bool(raw.get("tables")) or bool(raw.get("meta_boxes")))
    if is_v1_top:
        is_one_based = int(raw.get("schema_version") or 0) == 1 or int(raw.get("page_base") or 0) == 1
        norm_tables = []
        for idx, tb in enumerate(raw.get("tables") or []):
            p_raw = int(tb.get("page", 1 if is_one_based else 0))
            p_zero = max(0, p_raw - 1) if is_one_based else max(0, p_raw)
            area = tb.get("area") or {"x": 0.03, "y": 0.16, "w": 0.94, "h": 0.76}
            hy = tb.get("headerY") if tb.get("headerY") is not None else tb.get("header_y", area.get("y", 0.16))
            cols = []
            for c in (tb.get("columns") or []):
                f = str(c.get("field") or ((c.get("fields") or [""])[0]) or "").strip()
                if not f:
                    continue
                cols.append({
                    "field": f,
                    "fields": [f],
                    "label": c.get("label") or f,
                    "header_text": c.get("header_text") or c.get("label") or f,
                    "x": float(c.get("x", 0)),
                    "w": float(c.get("w", 0.08)),
                })
            norm_tables.append({
                "page": p_zero,
                "slot": tb.get("slot") or ("first" if idx == 0 else "middle"),
                "area": area,
                "headerY": float(hy),
                "columns": cols,
            })
        norm_meta = []
        for mb in (raw.get("meta_boxes") or []):
            rect = mb.get("rect") if isinstance(mb.get("rect"), dict) else mb
            p_raw = int(mb.get("page", 1 if is_one_based else 0))
            p_zero = max(0, p_raw - 1) if is_one_based else max(0, p_raw)
            mfield = str(mb.get("field") or "")
            if mfield == "branch":
                mfield = "bank_branch"
            norm_meta.append({
                "field": mfield,
                "label": str(mb.get("label") or mfield),
                "value": str(mb.get("value") or ""),
                "page": p_zero,
                "x": float(rect.get("x", 0)),
                "y": float(rect.get("y", 0)),
                "w": float(rect.get("w", 0.12)),
                "h": float(rect.get("h", 0.03)),
            })
        norm_custom = [
            {
                "key": str(cf.get("key") or cf.get("code") or ""),
                "label": str(cf.get("label") or cf.get("code") or ""),
                **({"kind": str(cf["kind"])} if cf.get("kind") else {}),
            }
            for cf in (raw.get("custom_fields") or [])
            if cf.get("key") or cf.get("code")
        ]
        layout = {
            "page_size": raw.get("page_size") or {"w": 595.0, "h": 842.0},
            "page_count": max(1, len(norm_tables)),
            "page_base": 0,
            "tables": norm_tables,
            "meta_boxes": norm_meta,
            **({"custom_fields": norm_custom} if norm_custom else {}),
        }

    field_map = dict(raw.get("field_map") or {})
    if not field_map and isinstance(layout, dict):
        for tb in (layout.get("tables") or []):
            for c in (tb.get("columns") or []):
                f = str(c.get("field") or ((c.get("fields") or [""])[0]) or "").strip()
                if f and f not in field_map:
                    field_map[f] = str(c.get("header_text") or c.get("label") or f)
    if not field_map:
        raise HTTPException(400, detail={"code": "E_PARAM", "message": "模板缺少 field_map 或 layout.tables.columns，无法导入"})

    header_columns = raw.get("header_columns")
    if not header_columns and isinstance(raw.get("match_rule"), dict):
        header_columns = raw["match_rule"].get("header_fingerprint")
    if not header_columns:
        header_columns = [str(v) for v in field_map.values()]

    return {
        "bank_code": bank,
        "field_map": field_map,
        "header_columns": header_columns,
        "layout": layout,
        "required_fields": raw.get("required_fields") or ["txn_date", "amount", "balance"],
        "publish": bool(raw.get("publish", False)),
    }


def _insert_imported_template(db: Session, norm: dict, can_publish: bool) -> Template:
    bank = norm["bank_code"]
    latest = db.execute(select(func.max(Template.version)).where(Template.bank_code == bank)).scalar() or 0
    row = Template(
        bank_code=bank,
        version=latest + 1,
        status="enabled" if can_publish else "draft",
        field_map=norm["field_map"],
        header_columns=norm["header_columns"],
        layout=norm["layout"],
        required_fields=norm["required_fields"],
    )
    if can_publish:
        others = db.execute(
            select(Template).where(Template.bank_code == bank, Template.deleted_at.is_(None))
        ).scalars().all()
        for o in others:
            if o.status == "enabled":
                o.status = "disabled"
    db.add(row)
    db.flush()
    _audit_template(db, "import_template", row.id, f"导入 {bank} v{row.version}")
    return row


@router.post("/import", dependencies=[Depends(require_banker)])
def import_template(
    # 必须显式 Body(...)：FastAPI 会把裸 dict|list 当成内嵌字段 payload，
    # 于是标准导出 JSON 直接 422 Field required（上一版就是这里坏掉的）
    payload: dict | list = Body(...),
    db: Session = Depends(get_session),
    user=Depends(require_banker),
):
    """导入单个或批量模板 JSON（同时兼容导出格式、schema_version=1 框选格式与列序号格式）。"""
    if isinstance(payload, list):
        raw_items = payload
        top_publish = False
    elif isinstance(payload, dict) and isinstance(payload.get("templates"), list):
        raw_items = payload["templates"]
        top_publish = bool(payload.get("publish", False))
    else:
        raw_items = [payload]
        top_publish = bool(payload.get("publish", False)) if isinstance(payload, dict) else False

    if not raw_items:
        raise HTTPException(400, detail={"code": "E_PARAM", "message": "导入内容为空"})
    is_admin = bool(getattr(user, "is_admin", False))
    created: list[dict] = []
    for item in raw_items:
        norm = _normalize_import_item(item)
        can_pub = is_admin and (top_publish or norm["publish"])
        row = _insert_imported_template(db, norm, can_pub)
        created.append({"id": row.id, "version": row.version, "bank_code": row.bank_code, "status": row.status})
    db.commit()
    first = created[0]
    return {**first, "count": len(created), "items": created}


@router.post("/load-builtin", dependencies=[Depends(require_banker)])
def load_builtin_templates(
    publish: bool = False,
    force: bool = False,
    db: Session = Depends(get_session),
    user=Depends(require_banker),
):
    """一键载入系统内置的标准银行模板（工行/招行/建行/农行/中行/广发），仅跳过已有可用或草稿版本的银行（force=true 时强制新增新版）。"""
    samples_dir = _Path(__file__).resolve().parents[2] / "algorithm" / "integration" / "samples"
    builtin_raws: list[dict] = []
    if samples_dir.exists():
        for fp in sorted(samples_dir.glob("*_template.json")):
            try:
                builtin_raws.append(json.loads(fp.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001
                continue
    # 补充主流银行标准电子版表头与基础区框模板，避免无几何布局的裸模板
    builtin_raws.extend([
        {
            "bank_code": "CCB",
            "field_map": {
                "txn_date": "记账日期",
                "summary": "摘要",
                "amount": "交易金额",
                "balance": "账户余额",
                "counterparty": "对方户名",
            },
            "header_columns": ["序号", "记账日期", "交易时间", "交易地点/附言", "摘要", "交易金额", "账户余额", "对方户名"],
            "required_fields": ["txn_date", "amount", "balance"],
        },
        {
            "bank_code": "ABC",
            "field_map": {
                "txn_date": "交易日期",
                "summary": "交易摘要",
                "amount": "交易金额",
                "balance": "本次余额",
                "counterparty": "对方户名",
            },
            "header_columns": ["交易日期", "交易时间", "交易金额", "本次余额", "对方户名", "交易摘要", "交易渠道"],
            "required_fields": ["txn_date", "amount", "balance"],
        },
        {
            "bank_code": "BOC",
            "field_map": {
                "txn_date": "交易日期",
                "currency": "币别",
                "amount": "交易金额",
                "balance": "余额",
                "summary": "业务摘要",
                "counterparty": "对方账户名称",
            },
            "header_columns": ["交易日期", "交易时间", "币别", "钞汇", "交易金额", "余额", "业务摘要", "对方账户名称"],
            "required_fields": ["txn_date", "amount", "balance"],
        },
        {
            "bank_code": "CGB",
            "field_map": {
                "txn_date": "交易时间",
                "summary": "摘要",
                "amount": "交易金额",
                "balance": "账户余额",
                "counterparty": "对方姓名",
            },
            "header_columns": ["交易时间", "摘要", "币种", "交易金额", "账户余额", "对方账号", "对方姓名"],
            "required_fields": ["txn_date", "amount", "balance"],
        },
    ])
    is_admin = bool(getattr(user, "is_admin", False))
    can_pub = bool(publish and is_admin)
    loaded: list[dict] = []
    skipped: list[str] = []
    for item in builtin_raws:
        norm = _normalize_import_item(item)
        bank = norm["bank_code"]
        if not force:
            exists = db.execute(
                select(Template).where(
                    Template.bank_code == bank,
                    Template.deleted_at.is_(None),
                    Template.status.in_(("enabled", "draft")),
                )
            ).scalars().first()
            if exists is not None:
                skipped.append(bank)
                continue
        row = _insert_imported_template(db, norm, can_pub)
        loaded.append({"id": row.id, "bank_code": row.bank_code, "version": row.version, "status": row.status})
    db.commit()
    return {"loaded": loaded, "skipped": skipped}


@router.post("/analyze-fields")
def analyze_template_fields_api(
    file: UploadFile = File(...),
    short_fields: str = Form("[]", description="短字段 JSON 数组：[{field,label,keywords}]"),
    header_fields: str = Form("[]", description="标题字段 JSON 数组：[{field,label,keywords}]"),
    bank_code: str | None = Form(None),
    password: str | None = Form(None),
    save: bool = Form(False, description="是否直接保存为新模板版本"),
    publish: bool = Form(False, description="保存时是否直接启用（仅管理员生效）"),
    db: Session = Depends(get_session),
    user=Depends(require_banker),
):
    """模板页一键调用模板分析算法：短字段就近匹配 + 标题字段版式分析，可选直接入库。"""
    import json as _json

    from services.template_analyzer import analyze_template_fields

    try:
        parsed_short = _json.loads(short_fields or "[]")
        parsed_header = _json.loads(header_fields or "[]")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, detail={"code": "E_PARAM", "message": f"字段配置不是合法 JSON：{exc}"}) from exc

    if not isinstance(parsed_short, list) or not isinstance(parsed_header, list):
        raise HTTPException(400, detail={"code": "E_PARAM", "message": "short_fields 与 header_fields 必须是 JSON 数组"})

    data = file.file.read()
    if not data:
        raise HTTPException(400, detail={"code": "E_PARAM", "message": "上传的样例文件为空"})

    try:
        result = analyze_template_fields(
            data,
            parsed_short,
            parsed_header,
            password=password or None,
            bank_code=bank_code or None,
            filename=file.filename,
        )
    except PermissionError as exc:
        raise HTTPException(400, detail={"code": "E_ENCRYPT", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "E_PARAM", "message": str(exc)}) from exc

    if save:
        field_map = result.get("field_map") or {}
        if not field_map:
            raise HTTPException(
                400,
                detail={"code": "E_EMPTY_MAP", "message": "未匹配到任何标题字段列，无法保存模板；请检查标题字段关键词或样例 PDF。"},
            )
        final_bank = str(result.get("bank_code") or "UNKNOWN").strip().upper() or "UNKNOWN"
        sample_id = _store_sample(db, file.filename or "sample.pdf", data)
        last_ver = db.execute(
            select(func.max(Template.version)).where(Template.bank_code == final_bank)
        ).scalar() or 0
        is_admin = bool(getattr(user, "is_admin", False))
        can_pub = bool(publish and is_admin)
        if can_pub:
            for prev in db.execute(
                select(Template).where(
                    Template.bank_code == final_bank,
                    Template.status == "enabled",
                    Template.deleted_at.is_(None),
                )
            ).scalars().all():
                prev.status = "disabled"
        header_cols = [
            str(item["header_text"])
            for item in (result.get("header_results") or [])
            if item.get("matched") and item.get("header_text")
        ]
        req_fields = [k for k in ("txn_date", "amount", "balance") if k in field_map]
        row = Template(
            bank_code=final_bank,
            version=int(last_ver) + 1,
            status="enabled" if can_pub else "draft",
            field_map=field_map,
            header_columns=header_cols or None,
            layout=result.get("layout"),
            required_fields=req_fields or list(field_map.keys())[:3],
            sample_file_id=sample_id,
        )
        db.add(row)
        db.flush()
        _audit_template(
            db,
            "template.analyze_save",
            row.id,
            f"bank={final_bank} v{row.version} status={row.status} cols={len(field_map)} metas={len((result.get('layout') or {}).get('meta_boxes') or [])}",
        )
        db.commit()
        db.refresh(row)
        result["saved_template"] = {
            "id": row.id,
            "bank_code": row.bank_code,
            "version": row.version,
            "status": row.status,
            "has_sample": True,
        }

    return result


def _store_sample(db: Session, filename: str, data: bytes) -> int:
    """把建模板用的样本存进 file_obj + 磁盘，供之后渲染「当时的框选」。"""
    import hashlib

    from db.models import FileObj

    digest = hashlib.sha256(data).hexdigest()
    exists = db.execute(select(FileObj).where(FileObj.sha256 == digest)).scalars().first()
    if exists:
        return exists.id
    lower = (filename or "").lower()
    is_pdf = b"%PDF-" in data[:1024] or lower.endswith(".pdf")
    if is_pdf:
        ext, mime, carrier = ".pdf", "application/pdf", "electronic"
    elif lower.endswith(".png") or data[:8].startswith(b"\x89PNG"):
        ext, mime, carrier = ".png", "image/png", "image"
    else:
        ext, mime, carrier = ".jpg", "image/jpeg", "image"

    storage = _Path(__file__).resolve().parents[1] / "storage" / "uploads"
    storage.mkdir(parents=True, exist_ok=True)
    path = storage / (digest + ext)
    if not path.exists():
        path.write_bytes(data)
    row = FileObj(sha256=digest, mime=mime, carrier=carrier,
                  pages=None, has_text_layer=is_pdf, storage_path=str(path))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


@router.get("/{template_id}/layout")
def get_template_layout(template_id: int, db: Session = Depends(get_session)):
    """模板当时的框选（页面尺寸 + 每个字段的方框）与样本是否可回看。"""
    row = db.get(Template, template_id)
    if row is None or row.deleted_at is not None:
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
    if row is None or row.deleted_at is not None:
        raise HTTPException(404, "模板不存在")
    if not row.sample_file_id or not row.layout:
        raise HTTPException(404, detail={"code": "E_NO_SAMPLE", "message": "该模板没有可回看的样本（旧版本模板）"})
    file_row = db.get(FileObj, row.sample_file_id)
    if file_row is None or not file_row.storage_path:
        raise HTTPException(404, detail={"code": "E_NO_SAMPLE", "message": "样本文件已不存在"})
    data = _Path(file_row.storage_path).read_bytes()
    png = tlayout.render_page_png(data, row.layout, max(0, page), dpi=max(80, min(200, dpi)))
    return Response(content=png, media_type="image/png")


def _audit_template(db: Session, action: str, template_id: int | None, detail: str) -> None:
    """模板的增删改必须有审计：出问题时要能回答「谁在什么时候改了什么」。"""
    try:
        db.add(AuditLog(action=action, object_type="template", object_id=template_id or 0,
                        detail=detail[:1000]))
    except Exception:  # noqa: BLE001 - 审计失败不能阻断业务
        pass