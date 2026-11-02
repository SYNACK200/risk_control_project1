"""业务看板聚合：把库里已有流水的任务、报告、评分、结论与阈值命中一次汇总。

数据量按「已受理任务」规模算（几十到几千），用 Python 聚合比在 SQL 里解 JSON 更清楚。
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import Report, Task, Txn
from db.session import get_session
from helpers.security import require_banker

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_banker)])

GRADE_LABEL = {"good": "良好", "fair": "一般", "poor": "较差", "unknown": "未评级"}


def _num(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@router.get("")
def get_dashboard(db: Session = Depends(get_session)):
    """看板：总览 + 评分/结论分布 + 银行分布 + 阈值命中 + 最近任务。"""
    live = Task.deleted_at.is_(None)
    tasks = db.execute(select(Task).where(live)).scalars().all()
    task_ids = [t.id for t in tasks]

    txn_by_task: dict[int, int] = {}
    txn_total = 0
    if task_ids:
        rows = db.execute(
            select(Txn.task_id, func.count(Txn.id)).where(Txn.task_id.in_(task_ids)).group_by(Txn.task_id)
        ).all()
        txn_by_task = {int(tid): int(n) for tid, n in rows}
        txn_total = sum(txn_by_task.values())

    reports: dict[int, Report] = {}
    if task_ids:
        rep_rows = db.execute(
            select(Report).where(Report.task_id.in_(task_ids)).order_by(Report.version.desc())
        ).scalars().all()
        for rep in rep_rows:
            reports.setdefault(rep.task_id, rep)  # 每个任务取最高版本

    grades: Counter[str] = Counter()
    verdicts: Counter[str] = Counter()
    banks: dict[str, dict[str, int]] = {}
    hit_counter: Counter[tuple[str, str]] = Counter()
    coverage_warn = 0
    threshold_version: int | None = None

    for task in tasks:
        cr = task.check_result or {}
        preread = cr.get("preread") or {}
        bank_code = (preread.get("bank_code") or "未识别") if isinstance(preread, dict) else "未识别"
        slot = banks.setdefault(bank_code, {"tasks": 0, "txn": 0})
        slot["tasks"] += 1
        slot["txn"] += txn_by_task.get(task.id, 0)

        cov = cr.get("parse_coverage")
        if isinstance(cov, (int, float)) and cov < 0.8:
            coverage_warn += 1

        rep = reports.get(task.id)
        if rep is None:
            grades["unknown"] += 1
            verdicts[rep.verdict if rep else "未出报告"] += 1
            continue
        verdicts[rep.verdict or "未判定"] += 1
        payload = rep.payload or {}
        if threshold_version is None:
            threshold_version = payload.get("threshold_version")
        scores = payload.get("scores") or {}
        grade = scores.get("grade") or "unknown"
        grades[str(grade)] += 1
        for item in (scores.get("risk_hits") or []):
            code = str(item.get("code") or "").strip()
            name = str(item.get("name") or code or "未命名")
            if code:
                hit_counter[(code, name)] += 1
        for item in (payload.get("conclusions") or []):
            code = str(item.get("code") or "").strip()
            if not code:
                continue
            hit_counter[(code, str(item.get("name") or item.get("text") or code)[:40])] += 1

    done = sum(1 for t in tasks if t.status == "DONE")
    failed = sum(1 for t in tasks if t.status == "FAILED")

    recent: list[dict] = []
    for task in sorted(tasks, key=lambda t: t.id, reverse=True)[:10]:
        rep = reports.get(task.id)
        payload = (rep.payload or {}) if rep else {}
        scores = payload.get("scores") or {}
        recent.append({
            "task_id": task.id,
            "biz_no": task.biz_no,
            "status": task.status,
            "bank_code": ((task.check_result or {}).get("preread") or {}).get("bank_code"),
            "verdict": rep.verdict if rep else None,
            "overall": _num(scores.get("overall")),
            "grade": scores.get("grade"),
            "txn_count": txn_by_task.get(task.id, 0),
        })

    return {
        "summary": {
            "tasks": len(tasks),
            "done": done,
            "failed": failed,
            "txn_total": txn_total,
            "avg_txn": round(txn_total / len(tasks), 1) if tasks else 0,
            "coverage_warn": coverage_warn,
            "threshold_version": threshold_version,
        },
        "grades": [
            {"grade": g, "label": GRADE_LABEL.get(g, g), "count": n}
            for g, n in grades.most_common()
        ],
        "verdicts": [{"verdict": v, "count": n} for v, n in verdicts.most_common()],
        "banks": [
            {"bank_code": k, **v} for k, v in sorted(banks.items(), key=lambda kv: -kv[1]["tasks"])
        ],
        "threshold_hits": [
            {"code": code, "name": name, "count": n}
            for (code, name), n in hit_counter.most_common(15)
        ],
        "recent": recent,
    }
