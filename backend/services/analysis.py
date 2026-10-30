"""把算法侧的四层核验、指标与报告串起来，供接口调用。"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algorithm.ocr.parse import parse  # noqa: E402
from algorithm.ocr.models import Template as ParseTemplate  # noqa: E402
from algorithm.algo.file_layer import analyze_file  # noqa: E402
from algorithm.algo.content_layer import analyze_content  # noqa: E402
from algorithm.algo.ledger_layer import analyze_ledger  # noqa: E402
from algorithm.algo.external_layer import analyze_external, ExternalContext  # noqa: E402
from algorithm.algo.verdict import conclude  # noqa: E402
from algorithm.algo.metrics import compute_metrics  # noqa: E402
from algorithm.algo.report import build_report, ReportMaterial, ReportCheck  # noqa: E402
from algorithm.ocr.infer import Mark as InferMark, infer_template as _infer_template  # noqa: E402
from algorithm.algo.self_check import run_self_check  # noqa: E402


class EncryptedFile(Exception):
    """PDF 需要口令；由接口转成 E_ENCRYPT。"""


def is_password_protected(file_bytes: bytes) -> bool:
    """只识别 PDF 是否设有打开口令，不验证或保存口令。"""
    if file_bytes[:4] != b"%PDF":
        return False
    doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    try:
        return bool(doc.needs_pass)
    finally:
        doc.close()


def run_analysis(
    file_bytes: bytes,
    *,
    password: str | None = None,
    template: dict | None = None,
    preread: object | None = None,
) -> dict:
    """返回 {carrier, pages, has_text_layer, txn_count, report, metrics, bank} 供落库。"""
    raw = file_bytes
    pages = 1
    has_text = False

    password_protected = False
    if file_bytes[:4] == b"%PDF":
        doc = pymupdf.open(stream=file_bytes, filetype="pdf")
        pages = doc.page_count
        if doc.needs_pass:
            password_protected = True
            if not password or doc.authenticate(password) <= 0:
                raise EncryptedFile("PDF 需要打开口令")
            tmp = Path(tempfile.gettempdir()) / "backend_plain.pdf"
            doc.save(tmp, encryption=pymupdf.PDF_ENCRYPT_NONE)
            raw = tmp.read_bytes()
            doc = pymupdf.open(stream=raw, filetype="pdf")
        text_len = sum(len(doc[i].get_text("text").strip()) for i in range(doc.page_count))
        has_text = text_len > 50 * doc.page_count
    carrier = "electronic" if has_text else "image"

    tpl = None
    if template:
        tpl = ParseTemplate(
            bank_code=str(template.get("bank_code", "UNKNOWN")),
            version=int(template.get("version", 1)),
            field_map=dict(template.get("field_map", {})),
        )

    parsed = parse(raw, tpl)
    file_layer = analyze_file(raw, carrier=carrier)
    content_layer = analyze_content(parsed)
    ledger = analyze_ledger(parsed.transactions)
    external = analyze_external(ExternalContext(transactions=parsed.transactions))
    verdict = conclude(
        content_layer, carrier=carrier, file_layer=file_layer, ledger=ledger, external=external
    )
    metrics = compute_metrics(parsed.transactions)
    txn_ids = list(range(1, len(parsed.transactions) + 1))
    self_check = run_self_check(raw, parsed.transactions, getattr(parsed, "footer_count", None), preread=preread)
    report = build_report(
        verdict,
        metrics,
        carrier=carrier,
        transactions=parsed.transactions,
        txn_ids=txn_ids,
        materials=[ReportMaterial(file_id=0, role="original", pages=pages)],
        self_check=[
            ReportCheck(code=i.code, name=i.name, status=i.status, detail=i.detail or "")
            for i in self_check.items
        ],
    )
    payload = json.loads(report.model_dump_json())

    return {
        "carrier": carrier,
        "pages": pages,
        "has_text_layer": has_text,
        "password_protected": password_protected,
        "txn_count": len(parsed.transactions),
        "warnings": list(parsed.warnings),
        "preread": preread.to_dict() if preread is not None else None,
        "self_check": {
            "status": self_check.status,
            "summary": self_check.summary,
            "items": [
                {"code": i.code, "name": i.name, "status": i.status, "detail": i.detail, "ratio": i.ratio}
                for i in self_check.items
            ],
            "samples": self_check.samples[:5],
        },
        "report": payload,
        "metrics": [
            {
                "code": m.code,
                "name": m.name,
                "value": None if m.value is None else str(m.value),
                "unit": m.unit,
                "note": m.note,
                "caliber_version": getattr(m, "caliber_version", 1),
            }
            for m in metrics.metrics
        ],
        "transactions": [
            {
                "txn_date": t.txn_date,
                "direction": t.direction,
                "amount": None if t.amount is None else str(t.amount),
                "balance": None if t.balance is None else str(t.balance),
                "summary": t.summary,
                "counterparty_name": t.counterparty_name,
                "page_no": t.page_no,
                "confidence": str(t.confidence) if getattr(t, "confidence", None) is not None else None,
            }
            for t in parsed.transactions
        ],
    }



def infer_from_marks(file_bytes: bytes, marks: list[dict], bank_code: str = "UNKNOWN") -> dict:
    """少量标注外推模板：返回 field_map、来源、列样本与告警。"""
    parsed = [InferMark(field=m["field"], page=int(m.get("page", 0)),
                        x=float(m["x"]), y=float(m["y"])) for m in marks]
    res = _infer_template(file_bytes, parsed, bank_code=bank_code)
    return {
        "field_map": res.template.field_map,
        "provenance": [
            {"field": p.field, "column": p.column, "source": p.source,
             "confidence": p.confidence, "why": p.why}
            for p in res.provenance
        ],
        "columns": res.columns,
        "warnings": res.warnings,
    }
