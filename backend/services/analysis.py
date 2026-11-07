"""把算法侧的四层核验、指标与报告串起来，供接口调用。"""
from __future__ import annotations

from decimal import Decimal

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
from services.custom_metric_eval import evaluate_custom  # noqa: E402
from algorithm.algo.report import build_report, ReportMaterial, ReportCheck  # noqa: E402
from algorithm.ocr.infer import Mark as InferMark, infer_template as _infer_template  # noqa: E402
from algorithm.algo.self_check import run_self_check  # noqa: E402


def _custom_field_stats(txns: list) -> list[dict]:
    """把模板自定义字段的值汇总成统计，供报告与看板展示。

    自定义字段是「列 → 字段」的映射，没有内置计算逻辑；
    但要让人看到它在整份流水里长什么样，至少得给出「有值笔数 + 合计 + 平均值」。
    数值型字段求和，非数值型只计数并给两个样例。
    """
    acc: dict[str, dict] = {}
    for t in txns:
        extra = getattr(t, "extra", None) or {}
        for field, raw in extra.items():
            box = acc.setdefault(field, {"field": field, "count": 0, "numeric_count": 0,
                                          "sum": Decimal("0"), "samples": []})
            box["count"] += 1
            text = str(raw).strip()
            try:
                val = Decimal(text.replace(",", "").replace("¥", "").replace("￥", ""))
                box["numeric_count"] += 1
                box["sum"] += val
            except Exception:  # noqa: BLE001
                if len(box["samples"]) < 2 and text:
                    box["samples"].append(text[:32])
    out = []
    for field, box in acc.items():
        numeric = box["numeric_count"] > 0 and box["numeric_count"] == box["count"]
        out.append({
            "field": field,
            "count": box["count"],
            "numeric": numeric,
            "sum": str(box["sum"]) if numeric else None,
            "avg": str((box["sum"] / box["count"]).quantize(Decimal("0.01"))) if numeric and box["count"] else None,
            "samples": box["samples"],
        })
    return sorted(out, key=lambda x: -x["count"])


def _append_custom_metrics(metrics, transactions):
    """把带 steps 的自定义指标算进指标集。失败时写进指标的 note，不给假 0。"""
    try:
        from db.session import SessionLocal  # noqa: PLC0415
        from db.models import CustomMetric  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415

        with SessionLocal() as session:
            rows = session.execute(
                select(CustomMetric).where(CustomMetric.enabled.is_(True))
            ).scalars().all()
            items = [(r.code, r.name, r.unit, r.steps) for r in rows if r.steps]
        if not items:
            return metrics
        from algorithm.algo.metrics import MetricValue  # noqa: PLC0415

        extra = []
        for code, name, unit, steps in items:
            res = evaluate_custom(steps, transactions)
            value = res["value"]
            note = "自定义指标（计算元执行）" if value is not None else (
                "自定义指标计算失败：" + (res.get("error") or "未知原因"))
            extra.append(MetricValue(
                code=code, name=name,
                value=round(Decimal(str(value)), 2) if value is not None else None,
                unit=unit or "", note=note,
            ))
        metrics.metrics.extend(extra)
        return metrics
    except Exception:  # noqa: BLE001 - 自定义指标失败不影响 40 项主指标
        return metrics


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
    thresholds: object | None = None,
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
            # 必须带上框画范围：不带的话解析只能按表头词中心推算列边界，
            # 「改框画范围」就永远不会影响结果（这一点之前实测时漏掉了）
            layout=template.get("layout"),
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
    # 有计算步骤的自定义指标在这里真正算出来；没有步骤的保持「仅登记口径」
    metrics = _append_custom_metrics(metrics, parsed.transactions)
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
        thresholds=thresholds,
    )
    payload = json.loads(report.model_dump_json())
    # 模板自定义字段的汇总（有值笔数、合计、均值、样例），报告与看板都用它
    payload["custom_field_stats"] = _custom_field_stats(parsed.transactions or [])

    # 解析覆盖率门禁：笔数远少于页脚声明时，报告必须自我说明并降级，避免「只读到 12 笔还给良好」
    footer_count = getattr(parsed, "footer_count", None)
    txn_total = len(parsed.transactions)
    parse_coverage = round(txn_total / footer_count, 4) if footer_count else None
    # 第二个信号：每页笔数异常低（12 页只有 12 笔这种），不依赖页脚也能发现漏行
    per_page = (txn_total / pages) if pages else None
    low_density = bool(pages >= 3 and per_page is not None and per_page < 2)
    if (parse_coverage is not None and parse_coverage < 0.8 and footer_count >= 10) or low_density:
        if parse_coverage is not None and footer_count >= 10:
            message = (
                f"解析不完整：只解析出 {txn_total} 笔，文件声明 {footer_count} 笔"
                f"（覆盖率 {parse_coverage:.0%}），指标与结论可能失真，请人工复核或修正模板"
            )
        else:
            message = (
                f"解析不完整：{pages} 页只解析出 {txn_total} 笔（每页 {per_page:.1f} 笔），"
                "疑似表格结构未还原，指标与结论可能失真，请人工复核或修正模板"
            )
        payload["limitations"] = [message] + list(payload.get("limitations") or [])
        scores = payload.get("scores")
        if isinstance(scores, dict):
            base = scores.get("overall")
            if isinstance(base, (int, float)):
                factor = (0.5 + 0.5 * parse_coverage) if parse_coverage is not None else 0.6
                scores["overall"] = round(float(base) * factor, 1)
            label = str(scores.get("grade_label") or "")
            if "解析不完整" not in label:
                scores["grade_label"] = (label + "·解析不完整").strip("·")

    return {
        "carrier": carrier,
        "pages": pages,
        "has_text_layer": has_text,
        "password_protected": password_protected,
        "txn_count": txn_total,
        "footer_count": footer_count,
        "parse_coverage": parse_coverage,
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
                "extra": getattr(t, "extra", None),
            }
            for t in parsed.transactions
        ],
    }



def infer_from_marks(file_bytes: bytes, marks: list[dict], bank_code: str = "UNKNOWN") -> dict:
    """少量标注外推模板：返回 field_map、来源、列样本与告警；反验不过时 valid=False 且无模板。"""
    parsed = [InferMark(field=m["field"], page=int(m.get("page", 0)),
                        x=float(m["x"]), y=float(m["y"])) for m in marks]
    res = _infer_template(file_bytes, parsed, bank_code=bank_code)
    return {
        "valid": res.valid,
        "field_map": res.template.field_map if res.template else getattr(res, "draft_map", {}) or {},
        "provenance": [
            {"field": p.field, "column": p.column, "source": p.source,
             "confidence": p.confidence, "why": p.why}
            for p in res.provenance
        ],
        "columns": res.columns,
        "warnings": res.warnings,
    }