"""账户/户名实体识别与合并（借鉴版本控制：账户=分支、户名=提交者、合并=merge、冲突=conflict）。

数据来源：每个任务的 preread（预读得到的银行、脱敏账号、脱敏户名）与已落库明细。
不引入新表：当前规模下按任务聚合即可；规模化再落 account/subject 表。

合并方法依据经典风险度量理论：
- 加总：完全相关（共单调）情形，是分散化收益为零的保守上界。
- 平方和开根：各账户相互独立时方差可加，sigma=sqrt(sum sigma_i^2)。
- 取最大：完全重叠情形，重叠区只按最大风险计一次。
- 并集去重：重叠期间只计一次，避免重复计数（double counting）。
- 加权平均：等权分摊，权重和为 1 的凸组合。
- 风险预算（凸组合）：按余额或收入份额给权重，权重和为 1。
参考：Artzner et al. (1999) 一致性风险度量（次可加性）、Basel IRB 的集中度与相关性假设。
（本地联网检索工具不可用，以上为教科书结论，未逐条核对原文。）
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Report, Task, Txn

REPAY_WORDS = ("还款", "分期", "贷款")
RISKY_CODES = {
    "DTI_HIGH", "LOW_BALANCE", "NEGATIVE_BALANCE", "NET_OUTFLOW",
    "LOAN_PLATFORM_MANY", "SMALL_LOAN_FREQUENT", "CASH_OUT_HEAVY",
    "NEW_LOAN", "COUNTERPARTY_CONCENTRATED", "INCOME_UNSTABLE",
}

METHODS: list[dict] = [
    {
        "id": "sum",
        "label": "加总",
        "short": "各账户金额直接相加，视为完全相关",
        "detail": "把每个账户的入账、出账、还款都相加。适合账户之间存在资金往来、风险高度同向的情况。缺点：若两个账户覆盖同一时间段，重叠区会被算两次（高估收入与还款）。",
        "formula": "X = sum(x_i)",
        "assumption": "完全相关（共单调），分散化收益为 0",
    },
    {
        "id": "union",
        "label": "并集去重",
        "short": "重叠月份只算一次，非重叠分别计入",
        "detail": "先取所有账户期间的并集；某个月只有一账户时按该账户金额，多账户重叠时按重叠算法取最大或平均。适合多账户时间区间不完全相同、又不希望重复计收入的情况。",
        "formula": "X = sum over months in union f(month)",
        "assumption": "重叠区不应重复计数",
    },
    {
        "id": "independence",
        "label": "独立假设",
        "short": "按平方和开根合并，账户间不相关",
        "detail": "假设各账户风险相互独立，合并风险等于各账户平方和开根。结果通常小于直接相加，适合账户之间没有资金往来、风险来源不同的情况。",
        "formula": "X = sqrt(sum x_i^2)",
        "assumption": "相互独立、无共同驱动因子",
    },
    {
        "id": "max",
        "label": "取最大",
        "short": "只看最坏那个账户",
        "detail": "各账户取最大值，等同于认为所有账户完全重叠、同一笔风险只发生一次。适合同一笔资金在多个账户间流转、不能重复计的情况。",
        "formula": "X = max(x_i)",
        "assumption": "完全重叠，风险不叠加",
    },
    {
        "id": "average",
        "label": "等权平均",
        "short": "各账户等权平均",
        "detail": "各账户等权平均，权重和为 1。适合作横向对比或账户数很多时的稳健估计，不反映总额，不能用于授信额度测算。",
        "formula": "X = (1/n) sum x_i",
        "assumption": "等权、凸组合",
    },
    {
        "id": "convex",
        "label": "余额加权",
        "short": "按账户余额占比加权（凸组合）",
        "detail": "按各账户期末余额占合计的份额给权重，权重非负且和为 1，是凸组合；账户越大权重越高。适合账户体量差异大的情况。",
        "formula": "X = sum w_i x_i, w_i >= 0, sum w_i = 1",
        "assumption": "风险随账户体量线性放大（凸性）",
    },
    {
        "id": "cvar",
        "label": "尾部合并",
        "short": "只看最差 20% 的月份（尾部风险）",
        "detail": "把各账户的月度净流入放在一起，取最差 20% 月份的均值（CVaR/ES 的离散近似），再按合并方法合并。适合关注最坏情况而不是平均水平。",
        "formula": "ES = mean(worst 20% monthly net inflow)",
        "assumption": "尾部风险一致，关注最坏情形",
    },
]

OVERLAP_MODES = [
    {"id": "max", "label": "重叠取最大", "detail": "同一个月多个账户都有数据时取最大值，避免重复计数。"},
    {"id": "avg", "label": "重叠取平均", "detail": "同一个月多个账户都有数据时取平均，偏中性。"},
    {"id": "sum", "label": "重叠也相加", "detail": "重叠月份也相加，等于加总口径，会高估。"},
]

METRIC_POLICY = {
    "A01": ("money", "期间收入合计"),
    "A02": ("ratio", "月均收入"),
    "B01": ("money", "月还款合计"),
    "B02": ("ratio", "债务收入比 DTI"),
    "C01": ("money", "净流入"),
    "C02": ("ratio", "流入流出比"),
}


def _latest_report(db: Session, task_id: int) -> dict:
    row = db.execute(
        select(Report).where(Report.task_id == task_id).order_by(Report.version.desc())
    ).scalars().first()
    return (row.payload if row and row.payload else {}) or {}


def collect_entities(db: Session) -> dict:
    tasks = db.execute(select(Task).where(Task.status == "DONE").order_by(Task.id.desc())).scalars().all()
    accounts: dict[str, dict] = {}
    subjects: dict[str, dict] = {}
    for task in tasks:
        check = task.check_result if isinstance(task.check_result, dict) else {}
        pre = check.get("preread") or {}
        account = pre.get("account_masked")
        holder = pre.get("holder_masked")
        bank = pre.get("bank_name")
        bank_code = pre.get("bank_code")
        acc_key = f"{bank_code or 'UNK'}:{account or 'UNK'}"
        sub_key = holder or "未识别户名"

        acc = accounts.setdefault(acc_key, {
            "key": acc_key,
            "bank_name": bank,
            "bank_code": bank_code,
            "account_masked": account,
            "holders": {},
            "tasks": [],
            "period_start": None,
            "period_end": None,
        })
        if holder:
            acc["holders"][holder] = acc["holders"].get(holder, 0) + 1
        acc["tasks"].append(task.id)
        if task.period_start and (acc["period_start"] is None or task.period_start < acc["period_start"]):
            acc["period_start"] = task.period_start
        if task.period_end and (acc["period_end"] is None or task.period_end > acc["period_end"]):
            acc["period_end"] = task.period_end

        sub = subjects.setdefault(sub_key, {
            "key": sub_key,
            "holder_masked": holder,
            "confidence": "high" if holder else "low",
            "accounts": {},
            "tasks": [],
        })
        sub["accounts"][acc_key] = sub["accounts"].get(acc_key, 0) + 1
        sub["tasks"].append(task.id)

    conflicts = []
    for acc in accounts.values():
        if len(acc["holders"]) > 1:
            conflicts.append({
                "kind": "account_multi_holder",
                "severity": "high",
                "account_key": acc["key"],
                "account_masked": acc["account_masked"],
                "bank_name": acc["bank_name"],
                "holders": sorted(acc["holders"].keys()),
                "tasks": acc["tasks"],
                "message": "同一账户出现多个户名，疑似借用账户或冒用他人流水",
            })
    multi = [s for s in subjects.values() if len(s["accounts"]) > 1]
    return {
        "accounts": sorted(accounts.values(), key=lambda a: -len(a["tasks"])),
        "subjects": sorted(subjects.values(), key=lambda s: -len(s["tasks"])),
        "conflicts": conflicts,
        "summary": {
            "accounts": len(accounts),
            "subjects": len(subjects),
            "multi_account_subjects": len(multi),
            "conflicts": len(conflicts),
        },
    }


def _month_key(value: str | None) -> str | None:
    if not value:
        return None
    m = re.match(r"(\d{4})-(\d{2})", str(value))
    return f"{m.group(1)}-{m.group(2)}" if m else None


def _task_series(db: Session, task_id: int) -> dict:
    rows = db.execute(select(Txn).where(Txn.task_id == task_id)).scalars().all()
    months: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"in": Decimal(0), "out": Decimal(0), "repay": Decimal(0)})
    balance_end = None
    for row in rows:
        key = _month_key(row.txn_date)
        if key is None:
            continue
        amount = row.amount or Decimal(0)
        if row.direction == "in":
            months[key]["in"] += amount
        elif row.direction == "out":
            months[key]["out"] += amount
            summary = row.summary or ""
            if any(word in summary for word in REPAY_WORDS):
                months[key]["repay"] += amount
        if row.balance is not None:
            balance_end = row.balance
    return {"months": months, "balance_end": balance_end, "txn_count": len(rows)}


def _combine(values: list[float], method: str, overlap: str, weights: list[float] | None) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    if method == "sum":
        return sum(values)
    if method == "union":
        if overlap == "max":
            return max(values)
        if overlap == "avg":
            return sum(values) / len(values)
        return sum(values)
    if method == "independence":
        return math.sqrt(sum(v * v for v in values))
    if method == "max":
        return max(values)
    if method == "average":
        return sum(values) / len(values)
    if method == "convex":
        w = weights or [1.0 / len(values)] * len(values)
        total = sum(w) or 1.0
        return sum(v * wi for v, wi in zip(values, w)) / total
    return sum(values)


MERGE_UNSUPPORTED = [
    ("A03", "月收入中位数", "需要原始明细按账户重新分桶，当前只合并月度汇总"),
    ("A04", "收入稳定性", "依赖各账户月度序列，合并后需重算，暂不提供"),
    ("A05", "工资占比", "需要工资类明细重新归类，暂不提供"),
    ("B04", "网贷平台数", "平台去重需跨账户明细，暂不提供"),
    ("C03", "日均余额", "余额不能相加（同一时点只有一份钱），需按账户分别看"),
    ("C04", "余额波动率", "同上，余额类指标不合并"),
    ("E01", "对手方集中度", "对手方需跨账户去重，暂不提供"),
]


def _merge_subject_legacy(db: Session, holder_key: str, method: str, overlap: str) -> dict:
    if method not in {m["id"] for m in METHODS}:
        raise ValueError(f"未知合并方法：{method}")
    if overlap not in {m["id"] for m in OVERLAP_MODES}:
        raise ValueError(f"未知重叠算法：{overlap}")

    tasks = db.execute(select(Task).where(Task.status == "DONE")).scalars().all()
    picked = []
    for task in tasks:
        check = task.check_result if isinstance(task.check_result, dict) else {}
        pre = check.get("preread") or {}
        holder = pre.get("holder_masked") or "未识别户名"
        if holder != holder_key:
            continue
        picked.append((task, pre))

    if not picked:
        raise ValueError("没有该户名下的已解析流水")

    series_list = []
    for task, pre in picked:
        series = _task_series(db, task.id)
        series["task_id"] = task.id
        series["bank_name"] = pre.get("bank_name")
        series["account_masked"] = pre.get("account_masked")
        series["report"] = _latest_report(db, task.id)
        series_list.append(series)

    month_values = {"in": defaultdict(list), "out": defaultdict(list), "repay": defaultdict(list)}
    balances = []
    for series in series_list:
        if series["balance_end"] is not None:
            balances.append(float(series["balance_end"]))
        for key, bucket in series["months"].items():
            month_values["in"][key].append(float(bucket["in"]))
            month_values["out"][key].append(float(bucket["out"]))
            month_values["repay"][key].append(float(bucket["repay"]))

    all_months = sorted(set(month_values["in"]) | set(month_values["out"]))
    overlap_months = sorted(
        key for key in all_months
        if len(month_values["in"].get(key, [])) > 1 or len(month_values["out"].get(key, [])) > 1
    )

    weights = balances if method == "convex" and balances else None
    # 账户级合计：取最大/等权/余额加权按账户总额计算，避免与并集口径混同
    per_account = {"in": [], "out": [], "repay": []}
    for series in series_list:
        for field in ("in", "out", "repay"):
            per_account[field].append(float(sum(bucket[field] for bucket in series["months"].values())))

    merged = {}
    for field in ("in", "out", "repay"):
        if method == "max":
            merged[field] = max(per_account[field]) if per_account[field] else 0.0
        elif method == "average":
            merged[field] = sum(per_account[field]) / len(per_account[field]) if per_account[field] else 0.0
        elif method == "convex":
            w = weights or [1.0] * len(per_account[field])
            total_w = sum(w) or 1.0
            merged[field] = sum(v * wi for v, wi in zip(per_account[field], w)) / total_w
        else:
            base = "union" if method == "cvar" else method
            total = 0.0
            for key in all_months:
                values = month_values[field].get(key, [])
                total += _combine(values, base, overlap, None)
            merged[field] = total

    months_count = len(all_months)
    a02 = merged["in"] / months_count if months_count else None
    b02 = (merged["repay"] / a02) if a02 else None
    c01 = merged["in"] - merged["out"]
    c02 = (merged["in"] / merged["out"]) if merged["out"] else None
    if method == "cvar" and all_months:
        nets = []
        for key in all_months:
            inflow = _combine(month_values["in"].get(key, []), "union", overlap, None)
            outflow = _combine(month_values["out"].get(key, []), "union", overlap, None)
            nets.append(inflow - outflow)
        nets.sort()
        k = max(1, math.ceil(len(nets) * 0.2))
        c01 = sum(nets[:k]) / k

    counts = [len([c for c in (s["report"].get("conclusions") or []) if c.get("code") in RISKY_CODES]) for s in series_list]
    if method == "max":
        risk_count = max(counts) if counts else 0
    elif method == "independence":
        risk_count = round(math.sqrt(sum(c * c for c in counts)))
    elif method == "average":
        risk_count = round(sum(counts) / len(counts)) if counts else 0
    elif method == "convex" and weights:
        total_w = sum(weights) or 1.0
        risk_count = round(sum(c * w for c, w in zip(counts, weights)) / total_w)
    else:
        risk_count = sum(counts)
    risk_level = "high" if risk_count >= 3 else "medium" if risk_count == 2 else "low" if risk_count == 1 else "none"

    method_meta = next(m for m in METHODS if m["id"] == method)
    overlap_meta = next(m for m in OVERLAP_MODES if m["id"] == overlap)

    gaps = []
    if all_months:
        start, end = all_months[0], all_months[-1]
        y0, m0 = int(start[:4]), int(start[5:7])
        y1, m1 = int(end[:4]), int(end[5:7])
        expected = (y1 - y0) * 12 + (m1 - m0) + 1
        if expected > months_count:
            gaps.append(f"覆盖区间共 {expected} 个月，实际有数据 {months_count} 个月，缺 {expected - months_count} 个月")

    warnings = []
    if overlap_months:
        warnings.append(
            f"{len(overlap_months)} 个月份存在多账户重叠，已按「{overlap_meta['label']}」处理：{', '.join(overlap_months[:6])}"
        )
    if any(not s["account_masked"] for s in series_list):
        warnings.append("有账户未识别出账号，合并结果的可信度下降")
    if holder_key == "未识别户名":
        warnings.append("该组未识别户名，属于弱关联，需要人工核对身份")
    warnings.extend(gaps)

    metrics = [
        {"code": "A01", "name": "合并期间收入", "value": round(merged["in"], 2), "unit": "元",
         "how": f"{method_meta['label']}：{method_meta['formula']}", "note": "跨账户月度入账合并后求和"},
        {"code": "A02", "name": "合并月均收入", "value": round(a02, 2) if a02 is not None else None, "unit": "元",
         "how": "A01 ÷ 有数据月份数（按合并后口径重算）", "note": f"共 {months_count} 个月"},
        {"code": "B01", "name": "合并月还款", "value": round(merged["repay"], 2), "unit": "元",
         "how": f"{method_meta['label']}：{method_meta['formula']}", "note": "按摘要关键词识别还款/分期/贷款"},
        {"code": "B02", "name": "合并 DTI", "value": round(b02, 4) if b02 is not None else None, "unit": "百分比",
         "how": "B01 ÷ A02（按合并后分量重算）", "note": "比率类指标不相加"},
        {"code": "C01",
         "name": "尾部净流入 ES" if method == "cvar" else "合并净流入",
         "value": round(c01, 2), "unit": "元",
         "how": "最差 20% 月份净流入均值（ES）" if method == "cvar" else "合并入账 − 合并出账",
         "note": "越小说明最坏月份越差" if method == "cvar" else ""},
        {"code": "C02", "name": "合并流入流出比", "value": round(c02, 4) if c02 is not None else None, "unit": "倍",
         "how": "合并入账 ÷ 合并出账", "note": ""},
    ]

    return {
        "subject": holder_key,
        "method": method_meta,
        "overlap": overlap_meta,
        "accounts": [
            {
                "task_id": s["task_id"],
                "bank_name": s["bank_name"],
                "account_masked": s["account_masked"],
                "months": len(s["months"]),
                "txn_count": s["txn_count"],
                "balance_end": None if s["balance_end"] is None else str(s["balance_end"]),
                "risk_hits": len([c for c in (s["report"].get("conclusions") or []) if c.get("code") in RISKY_CODES]),
                "verdict": s["report"].get("verdict"),
            }
            for s in series_list
        ],
        "coverage": {
            "months": months_count,
            "overlap_months": overlap_months,
            "from": all_months[0] if all_months else None,
            "to": all_months[-1] if all_months else None,
        },
        "metrics": metrics,
        "risk": {"level": risk_level, "hits": risk_count, "per_account": counts},
        "unsupported": [{"code": c, "name": n, "reason": r} for c, n, r in MERGE_UNSUPPORTED],
        "warnings": warnings,
        "explain": {
            "why_this_method": method_meta["detail"],
            "assumption": method_meta["assumption"],
            "ratio_rule": "比率类指标（月均、DTI、流入流出比）不直接相加，统一按合并后的分子分母重算。",
            "balance_rule": "余额类指标不跨账户相加：同一时点同一笔钱只存在一个账户里。",
        },
    }


def merge_subject(db: Session, holder_key: str, method: str = "net_internal", overlap: str = "auto") -> dict:
    """合并一个户名下的所有账户。计算交给 algorithm.algo.merge（含内部转账抵消与 40 项重算）。

    overlap 参数保留兼容：合并引擎按期间自动处理重叠，不再单独选择重叠算法。
    """
    from datetime import date as _date

    from algorithm.algo.merge import MODES, AccountInput, merge_accounts
    from algorithm.algo.metrics import METRIC_DEFS
    from algorithm.ocr.models import Transaction

    mode = method if method in MODES else "net_internal"
    tasks = db.execute(select(Task).where(Task.status == "DONE")).scalars().all()
    picked = []
    for task in tasks:
        check = task.check_result if isinstance(task.check_result, dict) else {}
        pre = check.get("preread") or {}
        holder = pre.get("holder_masked") or "未识别户名"
        if holder != holder_key:
            continue
        picked.append((task, pre))
    if not picked:
        raise ValueError("没有该户名下的已解析流水")

    accounts: list[AccountInput] = []
    account_meta = []
    for task, pre in picked:
        rows = db.execute(select(Txn).where(Txn.task_id == task.id)).scalars().all()
        txns = []
        for i, row in enumerate(rows, 1):
            txns.append(Transaction(
                page_no=row.page_no or 1,
                row_no=i,
                txn_date=str(row.txn_date) if row.txn_date else None,
                summary=row.summary,
                counterparty_name=row.counterparty_name,
                direction=row.direction,
                amount=row.amount,
                balance=row.balance,
            ))
        start = _date.fromisoformat(str(task.period_start)) if task.period_start else None
        end = _date.fromisoformat(str(task.period_end)) if task.period_end else None
        accounts.append(AccountInput(account_id=str(task.id), bank_code=pre.get("bank_code"),
                                     period_start=start, period_end=end, transactions=txns))
        account_meta.append({
            "task_id": task.id,
            "bank_name": pre.get("bank_name"),
            "account_masked": pre.get("account_masked"),
            "months": len({_month_key(str(row.txn_date)) for row in rows if row.txn_date} - {None}),
            "txn_count": len(rows),
            "balance_end": str(rows[-1].balance) if rows and rows[-1].balance is not None else None,
            "risk_hits": len([c for c in (_latest_report(db, task.id).get("conclusions") or [])
                              if c.get("code") in RISKY_CODES]),
            "verdict": _latest_report(db, task.id).get("verdict"),
        })

    result = merge_accounts(accounts, mode)
    units = {code: unit for code, _name, unit in METRIC_DEFS}
    metrics = []
    for item in result["metrics"]:
        value = item.get("value")
        metrics.append({
            "code": item["code"],
            "name": item["name"],
            "value": None if value is None else float(value),
            "unit": units.get(item["code"], ""),
            "how": item.get("basis", ""),
            "note": "",
        })

    counts = [a["risk_hits"] for a in account_meta]
    if mode == "worst_case":
        hits = max(counts) if counts else 0
    elif mode in ("convex", "weighted"):
        hits = round(sum(counts) / len(counts)) if counts else 0
    elif mode == "evidence":
        hits = max(counts) if counts else 0
    else:
        hits = min(3, sum(counts)) if counts else 0
    risk_level = "high" if hits >= 3 else "medium" if hits == 2 else "low" if hits == 1 else "none"

    months = sorted({_month_key(str(r.txn_date)) for _t, rows in [] for r in rows} - {None}) if False else []
    month_owner: dict[str, set[int]] = defaultdict(set)
    for account, meta in zip(accounts, account_meta):
        for txn in account.transactions:
            key = _month_key(txn.txn_date)
            if key:
                month_owner[key].add(meta["task_id"])
    months = sorted(month_owner)
    overlap_months = [k for k, owners in month_owner.items() if len(owners) > 1]

    warnings: list[str] = list(result.get("notes") or [])
    if overlap_months:
        warnings.append(f"{len(overlap_months)} 个月份存在多账户重叠，已由合并引擎按期间并集处理")
    if result.get("overlap_days"):
        warnings.append(f"账户期间重叠约 {result['overlap_days']} 天")
    if any(not a["account_masked"] for a in account_meta):
        warnings.append("有账户未识别出账号，合并结果可信度下降")
    if holder_key == "未识别户名":
        warnings.append("该组未识别户名，属于弱关联，需要人工核对身份")

    return {
        "subject": holder_key,
        "method": {
            "id": mode,
            "label": result["label"],
            "short": result["one_line"],
            "detail": result["formula"],
            "formula": result["formula"],
            "assumption": "",
        },
        "overlap": {"id": "auto", "label": "按期间自动处理", "detail": "合并引擎按各账户期间取并集，重叠不重复计数。"},
        "accounts": account_meta,
        "coverage": {
            "months": len(months),
            "overlap_months": overlap_months,
            "from": result.get("period_start"),
            "to": result.get("period_end"),
            "raw_txn_count": result.get("raw_txn_count"),
            "merged_txn_count": result.get("txn_count"),
            "dropped_duplicates": result.get("dropped_duplicates"),
            "internal_transfers": len(result.get("internal_transfers") or []),
        },
        "metrics": metrics,
        "risk": {"level": risk_level, "hits": hits, "per_account": counts},
        "unsupported": [{"code": c, "name": n, "reason": r} for c, n, r in MERGE_UNSUPPORTED],
        "warnings": warnings,
        "explain": {
            "why_this_method": result["one_line"],
            "assumption": result["formula"],
            "ratio_rule": "比率类指标（月均、DTI、流入流出比）由合并后的明细重算，不直接相加。",
            "balance_rule": "余额类指标不跨账户相加：同一时点同一笔钱只存在一个账户里。",
        },
    }
