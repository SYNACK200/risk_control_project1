"""把算法侧的四层核验、指标与报告串起来，供接口调用。"""
from __future__ import annotations

from decimal import Decimal

import json
import os
import sys
import tempfile
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algorithm.ocr.parse import parse  # noqa: E402
from algorithm.ocr.models import MetaBox, Template as ParseTemplate  # noqa: E402
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


def _extract_header_meta(headers: list) -> dict:
    """提取模板/预读从页眉单值框读到的扩展元数据（含币种与自定义短字段）。"""
    meta: dict = {}
    extra: dict[str, str] = {}
    for hdr in (headers or []):
        for fname in ("account_no", "account_name", "bank_branch", "account_type", "currency", "period_start", "period_end"):
            if fname in meta:
                continue
            hf = getattr(hdr, fname, None)
            val = getattr(hf, "value", None) if hf is not None else hf
            if val:
                meta[fname] = str(val)
        for k, hf in (getattr(hdr, "extra_fields", None) or {}).items():
            val = getattr(hf, "value", None)
            if val and k not in extra:
                extra[k] = str(val)
    if extra:
        meta["extra_fields"] = extra
    return meta


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


def plain_bytes(file_bytes: bytes, password: str | None) -> bytes:
    """加密 PDF 用口令解出一份可解析的明文副本；非加密件原样返回。

    为什么必须有这一步：算法侧的 parse 只认明文，直接喂加密字节能"成功"返回 0 笔
    （它会吞掉 pymupdf 的加密异常），于是模板试跑显示"0 笔"而入口还报了成功。
    """
    if file_bytes[:4] != b"%PDF":
        return file_bytes
    doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    try:
        if not doc.needs_pass:
            return file_bytes
        if not password:
            raise EncryptedFile("PDF 设有打开口令，请输入口令后再分析")
        if doc.authenticate(password) <= 0:
            raise EncryptedFile("口令不正确，请重新输入")
        # 临时文件用随机名：并发解析两份加密件时固定名会互相覆盖
        import uuid

        tmp = Path(tempfile.gettempdir()) / f"plain_{uuid.uuid4().hex}.pdf"
        doc.save(tmp, encryption=pymupdf.PDF_ENCRYPT_NONE)
        try:
            return tmp.read_bytes()
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        doc.close()


def password_opens(file_bytes: bytes, password: str) -> bool:
    """给的口令能不能打开这份 PDF。上传时就该判定，而不是受理后再失败。"""
    if file_bytes[:4] != b"%PDF":
        return True
    doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    try:
        if not doc.needs_pass:
            return True
        return doc.authenticate(password) > 0
    finally:
        doc.close()


def run_analysis(
    file_bytes: bytes,
    *,
    password: str | None = None,
    template: dict | None = None,
    preread: object | None = None,
    thresholds: object | None = None,
    ocr_route: tuple[bool, dict] | None = None,
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
            doc.close()
            raw = plain_bytes(file_bytes, password)      # 加密件解成明文副本，算法侧只认明文
            doc = pymupdf.open(stream=raw, filetype="pdf")
        text_len = sum(len(doc[i].get_text("text").strip()) for i in range(doc.page_count))
        has_text = text_len > 50 * doc.page_count
        doc.close()          # 解析要用 bytes，doc 只用来数页与判断有没有文字层，用完就关
    carrier = "electronic" if has_text else "image"

    tpl = None
    if template:
        from services.template_parse import build_template  # noqa: PLC0415

        tpl = build_template(
            bank_code=str(template.get("bank_code", "UNKNOWN")),
            version=int(template.get("version", 1)),
            field_map=template.get("field_map", {}),
            # 必须带上框画范围：不带的话解析只能按表头词中心推算列边界
            layout=template.get("layout"),
        )

    pipeline_backend = os.getenv("PIPELINE_BACKEND", "legacy").strip().lower()
    parsed = parse(raw, tpl)
    # B1: 当显式开启 PIPELINE_BACKEND=rc_platform 或主解析 0 笔时，尝试用 rc_platform 锚点扩散 + parse_v2 兜底
    if (pipeline_backend == "rc_platform" or not parsed.transactions) and raw[:4] == b"%PDF":
        try:
            from algorithm.ocr.models import Transaction as _LegacyTxn  # noqa: PLC0415
            from rc_platform.capabilities.layout.detect import detect_layout  # noqa: PLC0415
            from rc_platform.capabilities.layout.words import extract_pdf_words  # noqa: PLC0415
            from rc_platform.capabilities.parse_v2.table_reader import read_statement  # noqa: PLC0415

            rc_pages = extract_pdf_words(raw)
            rc_plan = detect_layout(rc_pages)
            rc_stmt = read_statement(rc_pages, rc_plan)
            if len(rc_stmt.rows) > len(parsed.transactions):
                parsed.transactions = [
                    _LegacyTxn(
                        page_no=r.page_no, row_no=r.row_no, txn_date=r.txn_date,
                        trade_time=r.trade_time, reference_no=r.reference_no,
                        summary=r.summary, counterparty_name=r.counterparty_name,
                        direction=r.direction, amount=r.amount, balance=r.balance,
                        confidence=r.confidence, extra=r.extra,
                    )
                    for r in rc_stmt.rows
                ]
                pipeline_backend = "rc_platform"
        except Exception:  # noqa: BLE001 - 兜底失败不影响主流程
            pass
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
    header_meta = _extract_header_meta(getattr(parsed, "headers", None) or [])
    if header_meta:
        payload["header_meta"] = header_meta

    # 模板缺列要说清楚：否则用户看到的是一堆「不可算」指标，不知道是版式没标全
    from services.template_checks import missing_required  # noqa: PLC0415

    missing = missing_required((template or {}).get("field_map"), (template or {}).get("required_fields"))
    if missing:
        payload.setdefault("limitations", [])
        payload["limitations"].insert(
            0,
            "模板缺列：" + "、".join(missing) + "（这份版式模板未标注这些列，相关指标因此不可算）",
        )

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

    route_info = None
    if ocr_route is not None:
        use_api, rcfg = ocr_route
        route_info = {
            "engine": "cloud_api" if (use_api and carrier != "electronic") else "local",
            "cloud_eligible": bool(use_api),
            "workers": int((rcfg or {}).get("workers") or 2),
            "model": (rcfg or {}).get("model") or "PP-OCRv6",
        }
    return {
        "pipeline_backend": pipeline_backend,
        "ocr_route": route_info,
        "carrier": carrier,
        "pages": pages,
        "has_text_layer": has_text,
        "password_protected": password_protected,
        "txn_count": txn_total,
        "footer_count": footer_count,
        "parse_coverage": parse_coverage,
        "warnings": list(parsed.warnings),
        "header_meta": header_meta,
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