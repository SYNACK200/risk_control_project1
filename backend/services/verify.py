"""快慢双通道的慢通道：用另一个引擎复核快通道的解析结果。

见 docs/快慢双通道解析设计.md。

慢通道**不修改**报告的任何业务字段，只写 report.verification：
  passed      两个引擎逐笔一致
  discrepancy 有差异，附清单
  failed      慢通道自己跑不起来（不等于快通道错）
"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import FileObj, Report, Task
from logging import getLogger

log = getLogger(__name__)

# 复核时最多记录这么多条差异，再多就只报数量（差异通常成片出现，逐条列没意义）
MAX_DIFFS = 20


def _norm(v) -> str:
    """金额/余额归一化：Decimal 保留两位，None 统一成空串。"""
    if v is None:
        return ""
    try:
        return str(Decimal(str(v)).quantize(Decimal("0.01")))
    except Exception:  # noqa: BLE001
        return str(v)


def _txn_key(t) -> tuple:
    """逐笔比较用的键：日期 + 金额 + 余额 + 方向。"""
    return (
        str(t.txn_date or ""),
        _norm(t.amount),
        _norm(t.balance),
        str(t.direction or ""),
    )


def compare(fast: list, slow: list) -> tuple[list[dict], int]:
    """逐笔对比，返回 (差异清单, 差异总数)。

    不做「文本全等」比较，只比业务字段——两个引擎的空白、换行处理本来就不同。
    按位置比：同一份文件、同一个模板，顺序应当一致；
    数量不同时把多出来的部分单列，而不是整体判错。
    """
    diffs: list[dict] = []
    n = max(len(fast), len(slow))
    for i in range(n):
        if i >= len(fast):
            diffs.append({"index": i + 1, "type": "slow_only",
                          "slow": {"date": slow[i].txn_date, "amount": _norm(slow[i].amount)}})
            continue
        if i >= len(slow):
            diffs.append({"index": i + 1, "type": "fast_only",
                          "fast": {"date": fast[i].txn_date, "amount": _norm(fast[i].amount)}})
            continue
        kf, ks = _txn_key(fast[i]), _txn_key(slow[i])
        if kf != ks:
            diffs.append({
                "index": i + 1, "type": "mismatch",
                "fast": {"date": kf[0], "amount": kf[1], "balance": kf[2], "direction": kf[3]},
                "slow": {"date": ks[0], "amount": ks[1], "balance": ks[2], "direction": ks[3]},
            })
    return diffs[:MAX_DIFFS], len(diffs)


def verify_report(db: Session, task_id: int) -> dict:
    """对某个任务的报告做一次慢通道复核。"""
    task = db.get(Task, task_id)
    if task is None:
        return {"status": "failed", "reason": "任务不存在"}

    rep = db.execute(
        select(Report).where(Report.task_id == task_id).order_by(Report.version.desc())
    ).scalars().first()
    if rep is None:
        return {"status": "failed", "reason": "报告不存在"}

    carrier = (rep.carrier or "").lower()
    if carrier and carrier != "electronic":
        # 图片件两条通道都是 OCR，同错概率高，复核意义小
        return {"status": "skipped", "reason": "非电子件不做双引擎复核"}

    # 原始文件在 FileObj.storage_path（和分析时同一份），不是 services.storage
    from pathlib import Path  # noqa: PLC0415

    file_row = db.get(FileObj, task.file_id) if task.file_id else None
    if file_row is None or not file_row.storage_path:
        return {"status": "failed", "reason": "任务没有可用的原始文件"}
    path = Path(file_row.storage_path)
    if not path.exists():
        return {"status": "failed", "reason": "原始文件已被清理"}
    data = path.read_bytes()

    # 慢通道用 pdfplumber（与快通道的 PyMuPDF 是两套独立实现）
    from algorithm.ocr.models import Template as ParseTemplate  # noqa: PLC0415
    from algorithm.ocr.parse import parse  # noqa: PLC0415

    tpl = None
    try:
        payload = rep.payload if isinstance(rep.payload, dict) else {}
        tpl_meta = payload.get("template") or {}
        if tpl_meta.get("bank_code"):
            tpl = ParseTemplate(
                bank_code=tpl_meta["bank_code"],
                version=tpl_meta.get("version") or 1,
                field_map=dict(tpl_meta.get("field_map") or {}),
                layout=tpl_meta.get("layout"),
            )
    except Exception:  # noqa: BLE001
        tpl = None

    try:
        slow = parse(data, tpl)
    except Exception as exc:  # noqa: BLE001
        log.warning("慢通道解析失败 task=%s: %s", task_id, exc)
        return {"status": "failed", "reason": f"慢通道解析失败：{str(exc)[:120]}"}

    # 快通道的逐笔落在 txn 表（报告 payload 里只有汇总），从这里取
    from db.models import Txn  # noqa: PLC0415

    fast_txns = db.execute(
        select(Txn).where(Txn.task_id == task_id).order_by(Txn.id)
    ).scalars().all()
    if not fast_txns:
        return {"status": "failed", "reason": "任务没有逐笔明细，无法对比"}

    diffs, total = compare(fast_txns, slow.transactions)
    status = "passed" if total == 0 else "discrepancy"
    return {
        "status": status,
        "engine": "pdfplumber",
        "checked_at": datetime.utcnow().isoformat(),
        "txn_count_fast": len(fast_txns),
        "txn_count_slow": len(slow.transactions),
        "diff_count": total,
        "diffs": diffs,
    }


def save_verification(db: Session, task_id: int, result: dict) -> None:
    rep = db.execute(
        select(Report).where(Report.task_id == task_id).order_by(Report.version.desc())
    ).scalars().first()
    if rep is None:
        return
    rep.verification = result
    db.commit()


def verify_task(task_id: int) -> dict:
    """进程池里跑的入口：自己开 session。"""
    from db.session import SessionLocal  # noqa: PLC0415

    if SessionLocal is None:
        return {"status": "failed", "reason": "数据库未初始化"}
    with SessionLocal() as db:
        result = verify_report(db, task_id)
        save_verification(db, task_id, result)
        return result