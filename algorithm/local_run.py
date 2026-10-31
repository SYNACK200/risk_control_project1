
"""离线跑一份流水的完整分析（不依赖后端）。
用法：python algorithm/local_run.py <pdf路径> [--password 口令] [--template 模板json] [--out 输出json]
说明：这不是业务闭环，是算法侧离线验证；产物为报告 JSON + 业务摘要。
"""
from __future__ import annotations
import argparse, json, pathlib, sys, tempfile, re
from datetime import date
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import pymupdf
from algorithm.ocr.parse import parse
from algorithm.ocr.models import Template
from algorithm.ocr.template_convert import convert_annotation
from algorithm.algo.file_layer import analyze_file
from algorithm.algo.content_layer import analyze_content
from algorithm.algo.ledger_layer import analyze_ledger
from algorithm.algo.external_layer import analyze_external, ExternalContext
from algorithm.algo.verdict import conclude
from algorithm.algo.metrics import compute_metrics
from algorithm.algo.report import build_report, ReportMaterial
from algorithm.algo.self_check import run_self_check


def mask(text: str, keep: int = 4) -> str:
    if not text: return text
    return text[:keep] + "*" * max(1, len(text) - keep)


def load_template(path: pathlib.Path, file_bytes: bytes | None = None) -> Template:
    """旧版 field_map 直接用；标注导出（v1 箱体）走 ocr.template_convert 转换。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    field_map = data.get("field_map")
    if field_map:
        return Template(
            bank_code=data.get("bank_code", "UNKNOWN"),
            version=data.get("version", 1),
            field_map=field_map,
        )
    if not data.get("tables") and not data.get("meta_boxes"):
        raise ValueError("模板缺少 field_map，tables 里也没有可用的 columns")
    result = convert_annotation(data, file_bytes)
    if result.template is None:
        raise ValueError("标注模板无法转换：" + "；".join(result.errors))
    return result.template


SUMMARY_LIMITATIONS = 10


def summary_limitations(items: list[str]) -> list[str]:
    """摘要只列前 N 条，其余给条数；完整清单留在报告 JSON。"""
    shown = list(items[:SUMMARY_LIMITATIONS])
    if len(items) > SUMMARY_LIMITATIONS:
        shown.append(
            f"……其余 {len(items) - SUMMARY_LIMITATIONS} 条见报告 JSON 的 limitations（共 {len(items)} 条）"
        )
    return shown


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--password", default=None)
    ap.add_argument("--template", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    src = pathlib.Path(a.path)
    if not src.exists():
        print(f"文件不存在：{src}", file=sys.stderr); return 2
    raw_original = src.read_bytes()

    # 1 过闸：PDF/图片 + 加密
    doc = pymupdf.open(stream=raw_original, filetype="pdf") if raw_original[:4] == b"%PDF" else None
    steps = []
    if doc is None:
        steps.append(("过门槛", "通过", "非 PDF（按图片处理）")); carrier = "image"; raw = raw_original; pages = 1
    else:
        if doc.needs_pass:
            ok = bool(a.password) and doc.authenticate(a.password) > 0
            steps.append(("加密检查", "通过" if ok else "不通过", "口令正确" if ok else "未提供或口令错误"))
            if not ok:
                print(json.dumps({"error": "E_ENCRYPT", "steps": steps}, ensure_ascii=False, indent=1)); return 3
        tmp = pathlib.Path(tempfile.gettempdir()) / f"plain_{src.stem}.pdf"
        doc.save(tmp, encryption=pymupdf.PDF_ENCRYPT_NONE)
        raw, pages = tmp.read_bytes(), doc.page_count
        text_len = sum(len(doc[i].get_text("text").strip()) for i in range(doc.page_count))
        carrier = "electronic" if text_len > 50 * doc.page_count else "image"
        steps.append(("过门槛", "通过", f"PDF {pages} 页；文字层 {text_len} 字 → {carrier}"))

    # 2 解析（可选模板）
    tpl = None
    if a.template:
        tpl = load_template(pathlib.Path(a.template), raw)
    parsed = parse(raw, tpl)
    steps.append(("解析", "成功" if parsed.transactions else "失败",
                  f"{len(parsed.transactions)} 笔；完整率 {parsed.field_completeness}；低置信 {parsed.low_conf_ratio}；警告 {len(parsed.warnings)} 条"))

    # 2b 识别自检 S1~S7：解析值能否在原文里回查到
    sc = run_self_check(raw, parsed.transactions, getattr(parsed, "footer_count", None))
    steps.append(("识别自检", sc.status, sc.summary))

    # 3 四层 + 结论
    fl = analyze_file(raw, carrier=carrier)
    cl = analyze_content(parsed)
    ll = analyze_ledger(parsed.transactions)
    el = analyze_external(ExternalContext(transactions=parsed.transactions))
    v = conclude(cl, carrier=carrier, file_layer=fl, ledger=ll, external=el)
    steps.append(("四层核验", "完成", f"载体 {fl.status} / 内容 {cl.status} / 账务 {ll.status} / 外部 {el.status}"))

    # 4 指标 + 报告
    ms = compute_metrics(parsed.transactions)
    ids = list(range(1, len(parsed.transactions) + 1))
    rep = build_report(v, ms, carrier=carrier, transactions=parsed.transactions, txn_ids=ids,
                       materials=[ReportMaterial(file_id=1, role="original", pages=pages)],
                       self_check=sc)
    data = json.loads(rep.model_dump_json())
    steps.append(("出报告", "完成", f"结论 {data['verdict']}；指标 {sum(1 for m in ms.metrics if m.value is not None)}/{len(ms.metrics)} 有值"))

    summary = {
        "文件": mask(src.name, 12), "页数": pages, "载体": carrier,
        "笔数": len(parsed.transactions),
        "覆盖期": [parsed.transactions[0].txn_date, parsed.transactions[-1].txn_date] if parsed.transactions else None,
        "结论": data["verdict"], "理由": data["verdict_reason"],
        "受限": summary_limitations(data["limitations"]),
        "自检": [{"项": f"{i.code} {i.name}", "结果": i.status, "说明": i.detail} for i in sc.items],
        "步骤": steps,
    }
    out = pathlib.Path(a.out) if a.out else pathlib.Path(tempfile.gettempdir()) / f"report_{src.stem}.json"
    out.write_text(json.dumps({"summary": summary, "report": data}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    print(f"\n报告 JSON：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
