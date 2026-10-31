"""把任务+报告汇总成「银行办事需要的几列」：合格性、解析质量、信用风险、材料。

口径写在这里，前端只渲染，不再各算一套：
- 真实性：任一 inconsistency 或截图件 -> fail；影像件 -> unknown；四层全 pass -> pass；否则 partial。
- 解析质量：任务非 DONE 或无明细 -> failed；自检有失败项或指标有值率 < 80% -> partial；否则 ok。
- 信用风险：按阈值结论条数分级，high >=3、medium =2、low =1、none =0，并给出命中编码。
"""
from __future__ import annotations

from typing import Any

RISKY_CODES = {
    "DTI_HIGH", "LOW_BALANCE", "NEGATIVE_BALANCE", "NET_OUTFLOW",
    "LOAN_PLATFORM_MANY", "SMALL_LOAN_FREQUENT", "CASH_OUT_HEAVY",
    "NEW_LOAN", "COUNTERPARTY_CONCENTRATED", "INCOME_UNSTABLE",
}

AUTH_LABEL = {
    "pass": "合格",
    "grant": "可授信",
    "supplement": "需补充",
    "fail": "不合格",
    "unknown": "无法判定",
}

# 拆法：
#   可授信 = 核心层没有「矛盾/不一致」，受限只来自「我们查不到」（外部未开通、
#            基线缺失、字体非嵌入这类留档即可的问题）
#   需补充 = 缺少关键材料或存在需客户补交的项（每页合计/页脚笔数/期初期末余额）
#   不合格 = 出现一致性矛盾（inconsistent/fail）或截图件
CORE_LAYERS = ("file", "content", "ledger")
REQUIRED_MATERIAL_CODES = {"C2", "C3", "C4"}

PARSE_LABEL = {"ok": "完整", "partial": "不完整", "failed": "失败"}

RISK_LABEL = {"high": "高", "medium": "中", "low": "低", "none": "未见"}


def _auth(layers: list[dict], carrier: str | None) -> dict:
    statuses = {item.get("layer"): item.get("status") for item in (layers or [])}
    bad = [name for name, status in statuses.items() if status in ("inconsistent", "fail")]
    if not statuses:
        level = "unknown"
    elif bad or carrier == "screenshot":
        level = "fail"
    elif carrier == "image":
        level = "unknown"
    elif all(statuses.get(name) == "pass" for name in ("file", "content", "ledger", "external")):
        level = "pass"
    else:
        core_checks = [
            check
            for layer in layers
            if layer.get("layer") in CORE_LAYERS
            for check in (layer.get("checks") or [])
        ]
        skipped = [
            check.get("code")
            for check in core_checks
            if check.get("status") == "skipped" and check.get("code") in REQUIRED_MATERIAL_CODES
        ]
        # 核心层里出现 fail/inconsistent 的单点，或某层一项都没执行过 → 也要补充/复核
        core_flagged = [
            check.get("code")
            for check in core_checks
            if check.get("status") in ("fail", "inconsistent")
        ]
        unverified = [
            layer.get("layer")
            for layer in layers
            if layer.get("layer") in CORE_LAYERS and not (layer.get("checks") or [])
        ]
        level = "supplement" if (skipped or core_flagged or unverified or not core_checks) else "grant"
    limited = [
        name
        for name in ("file", "content", "ledger", "external")
        if statuses.get(name) in ("limited", "skipped", "unavailable", "undetermined")
    ]
    missing_materials = [
        check.get("code")
        for layer in layers
        if layer.get("layer") in CORE_LAYERS
        for check in (layer.get("checks") or [])
        if check.get("status") == "skipped" and check.get("code") in REQUIRED_MATERIAL_CODES
    ]
    return {
        "level": level,
        "label": AUTH_LABEL[level],
        "blocked_layers": bad,
        "limited_layers": limited,
        "core_passed": all(statuses.get(name) == "pass" for name in CORE_LAYERS),
        "missing_materials": missing_materials,
    }


SOURCE_LABEL = {
    "clean": "未见可疑",
    "limited": "受限（需复核）",
    "suspicious": "来源可疑",
    "unknown": "无法判定",
}


def _source(layers: list[dict], verdict: str | None) -> dict:
    """原始文件来源侧：只看载体/结构层，不掺内容层。"""
    file_status = next((item.get("status") for item in layers if item.get("layer") == "file"), None)
    if verdict == "来源可疑" or file_status == "fail":
        level = "suspicious"
    elif file_status == "pass":
        level = "clean"
    elif file_status in ("limited", "skipped", "unavailable", "undetermined"):
        level = "limited"
    else:
        level = "unknown"
    return {"level": level, "label": SOURCE_LABEL[level], "file_status": file_status}


def _parse(payload: dict, task_status: str, txn_count: int | None) -> dict:
    metrics = payload.get("metrics") or []
    total = len(metrics)
    valued = sum(1 for item in metrics if item.get("value") is not None)
    checks = payload.get("self_check") or []
    failed = [c.get("code") for c in checks if c.get("status") in ("inconsistent", "fail")]
    limited = [c.get("code") for c in checks if c.get("status") in ("limited", "skipped")]
    if task_status != "DONE" or not txn_count:
        level = "failed"
    elif failed or (total and valued / total < 0.8):
        level = "partial"
    else:
        level = "ok"
    return {
        "level": level,
        "label": PARSE_LABEL[level],
        "txn_count": txn_count or 0,
        "metrics_valued": valued,
        "metrics_total": total,
        "failed_checks": failed,
        "limited_checks": limited,
    }


def _metric_value(payload: dict, code: str) -> str | None:
    for item in payload.get("metrics") or []:
        if item.get("code") == code and item.get("value") is not None:
            return str(item.get("value"))
    return None


def _risk(payload: dict) -> dict:
    conclusions = payload.get("conclusions") or []
    hits = [
        {"code": item.get("code"), "level": item.get("level"), "value": item.get("value")}
        for item in conclusions
        if item.get("code") in RISKY_CODES
    ]
    count = len(hits)
    level = "high" if count >= 3 else "medium" if count == 2 else "low" if count == 1 else "none"
    return {
        "level": level,
        "label": RISK_LABEL[level],
        "count": count,
        "hits": hits,
    }


def summarize(
    *,
    task: Any,
    payload: dict | None,
    file_row: Any | None,
    txn_count: int | None,
    report_version: int | None,
) -> dict:
    payload = payload or {}
    check = task.check_result if isinstance(task.check_result, dict) else {}
    preread = check.get("preread") or {}
    layers = payload.get("layers") or []
    carrier = task.carrier or (file_row.carrier if file_row is not None else None)
    auth = _auth(layers, carrier)
    parse = _parse(payload, task.status, txn_count)
    risk = _risk(payload)
    materials = len(payload.get("materials") or [])
    limitations = len(payload.get("limitations") or [])
    return {
        "id": task.id,
        "biz_no": task.biz_no,
        "status": task.status,
        "carrier": carrier,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "bank_name": preread.get("bank_name"),
        "bank_code": preread.get("bank_code"),
        "period_start": task.period_start or preread.get("period_start"),
        "period_end": task.period_end or preread.get("period_end"),
        "verdict": payload.get("verdict"),
        "source": _source(layers, payload.get("verdict")),
        "income": _metric_value(payload, "A01"),
        "monthly_income": _metric_value(payload, "A02"),
        "dti": _metric_value(payload, "B02"),
        "net_inflow": _metric_value(payload, "C01"),
        "risk_codes": [h["code"] for h in risk["hits"]],
        "authenticity": auth,
        "parse": parse,
        "risk": risk,
        "materials": materials,
        "limitations": limitations,
        "report_version": report_version,
        "whitelisted": bool((task.check_result or {}).get("whitelist")) if isinstance(task.check_result, dict) else False,
        "whitelist_reason": ((task.check_result or {}).get("whitelist") or {}).get("reason") if isinstance(task.check_result, dict) else None,
    }
