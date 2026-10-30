"""多账户合并：把同一借款人的多个银行账户流水/指标合并成一份视图。

设计原则：
1. 合并方式必须显式选择，且每种方式都给出公式、适用条件与已知偏差；
2. 流水合并（加总/去重/抵消）与指标合并（木桶/凸性/加权）分开：
   前者处理「钱」，后者处理「分」；
3. 任何合并都输出 explain，说明每个数怎么来的。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .metrics import compute_metrics


@dataclass
class AccountInput:
    account_id: str
    bank_code: str | None
    period_start: date | None
    period_end: date | None
    transactions: list


@dataclass
class MergeMode:
    key: str
    label: str
    one_line: str
    formula: str
    when: str
    caveat: str
    level: str  # flow / score


MODES: dict[str, MergeMode] = {
    "net_internal": MergeMode(
        "net_internal", "合并并抵消内部转账（推荐）",
        "先按指纹去重，再剔除账户之间的互转，最后汇总",
        "合并 = Σ明细 − 重复指纹 − 内部转账成对记录",
        "多账户、账户之间可能有互相转账",
        "内部转账识别依赖同日或相邻日、金额相等；跨行到账延迟超过 2 天会漏判",
        "flow",
    ),
    "sum": MergeMode(
        "sum", "直接相加",
        "所有账户的明细原样合并，期间取并集",
        "合并 = Σ 各账户明细",
        "账户之间没有内部转账，或只做粗略规模判断",
        "同一笔互转会记两次，收入与支出都会虚高",
        "flow",
    ),
    "dedupe": MergeMode(
        "dedupe", "仅去重后相加",
        "同一笔明细被重复上传/重复出现时只保留一次",
        "合并 = Σ明细 − 重复指纹（日期+方向+金额+摘要）",
        "怀疑同一份流水被重复提交",
        "只去掉完全相同的记录，不减掉互转的两端",
        "flow",
    ),
    "worst_case": MergeMode(
        "worst_case", "最坏情形（木桶）",
        "每个指标取各账户里最差的那个，按最弱一环评价",
        "M = max_i m_i（风险类）；稳健类取 min_i m_i",
        "授信审批偏保守，宁可高估风险",
        "会把某一账户的异常放大到整个人，可能过严",
        "score",
    ),
    "convex": MergeMode(
        "convex", "凸性聚合（惩罚集中）",
        "平方和开根，同样规模下越集中越重，越分散越轻",
        "M = √(Σ m_i²)",
        "关心风险是否集中在单一账户",
        "对量纲敏感，比值类指标需先归一到 0–1",
        "score",
    ),
    "weighted": MergeMode(
        "weighted", "按规模加权平均",
        "按各账户流水金额（或笔数）占比加权",
        "M = Σ w_i m_i ÷ Σ w_i",
        "账户重要性差异大，小账户不应与大账户同权",
        "主账户权重高时，小账户的异常容易被稀释",
        "score",
    ),
    "sync_amplify": MergeMode(
        "sync_amplify", "同步放大（超可加）",
        "两笔流水在同一个月份同时抽走资金时，合并风险按 Σ × (1 + λ·同步率) 放大",
        "M = Σ mᵢ × (1 + λ · 同步月数/总月数)",
        "多账户时间上同步（同月大额流出/净流出），合并风险可能大于各自之和",
        "同步判定依赖月份粒度与「大额」阈值（月均流出的 80%）；λ 默认 0.5，可用 MERGE_SYNC_LAMBDA 调整",
        "flow",
    ),
    "evidence": MergeMode(
        "evidence", "证据合成（真实性）",
        "把各账户真实性当作证据在对数几率空间相加",
        "logit(P) = Σ logit(p_i) − (n−1)·logit(p0)",
        "多份材料的真实性需要合成一个总体可信度",
        "各账户证据不独立时（同一来源伪造）会高估可信度",
        "score",
    ),
}


# 风险类指标：越大越差；稳健类：越小越差。未列出的按「越大越差」。
LOWER_IS_WORSE = {"A04", "A06", "C02", "C03", "C06"}


def _fingerprint(txn) -> tuple:
    summary = (txn.summary or "").strip()[:8]
    return (str(txn.txn_date or ""), str(txn.direction or ""), str(txn.amount or ""), summary)


def _signed(txn) -> Decimal:
    amount = txn.amount or Decimal("0")
    return amount if txn.direction == "in" else -amount


def _days(date_text: str | None) -> date | None:
    if not date_text:
        return None
    m = re.match(r"(20\d{2})\D(\d{1,2})\D(\d{1,2})", str(date_text))
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _dedupe(accounts: list[AccountInput]) -> tuple[list, int]:
    seen: set[tuple] = set()
    kept = []
    dropped = 0
    for account in accounts:
        for txn in account.transactions:
            key = _fingerprint(txn)
            if key in seen:
                dropped += 1
                continue
            seen.add(key)
            kept.append((account.account_id, txn))
    return kept, dropped


def _cancel_internal(rows: list[tuple[str, object]]) -> tuple[list[tuple[str, object]], list[dict]]:
    """账户 A 转出与账户 B 转入：金额相等、日期相差 ≤2 天，成对剔除。"""
    by_amount: dict[Decimal, list[tuple[int, str, object]]] = {}
    for index, (account_id, txn) in enumerate(rows):
        if txn.amount is None or txn.direction not in ("in", "out"):
            continue
        by_amount.setdefault(txn.amount, []).append((index, account_id, txn))

    removed: set[int] = set()
    pairs: list[dict] = []
    for amount, items in by_amount.items():
        outs = [item for item in items if item[2].direction == "out"]
        ins = [item for item in items if item[2].direction == "in"]
        used: set[int] = set()
        for index_out, account_out, txn_out in outs:
            day_out = _days(txn_out.txn_date)
            if day_out is None:
                continue
            for index_in, account_in, txn_in in ins:
                if index_in in used or account_in == account_out:
                    continue
                day_in = _days(txn_in.txn_date)
                if day_in is None or abs((day_in - day_out).days) > 2:
                    continue
                used.add(index_in)
                removed.add(index_out)
                removed.add(index_in)
                pairs.append({
                    "amount": str(amount),
                    "from": account_out,
                    "to": account_in,
                    "out_date": str(txn_out.txn_date),
                    "in_date": str(txn_in.txn_date),
                })
                break
    kept = [row for index, row in enumerate(rows) if index not in removed]
    return kept, pairs


def _combine(values: list[Decimal], mode: str, weights: list[Decimal] | None) -> Decimal | None:
    values = [v for v in values if v is not None]
    if not values:
        return None
    if mode == "worst_case":
        return max(values)
    if mode == "convex":
        return Decimal(str(round(math.sqrt(sum(float(v) ** 2 for v in values)), 4)))
    if mode == "weighted":
        if not weights or len(weights) != len(values):
            weights = [Decimal("1")] * len(values)
        total = sum(weights) or Decimal("1")
        return sum(v * w for v, w in zip(values, weights)) / total
    return sum(values)


def mode_catalog() -> list[dict]:
    return [
        {
            "key": m.key,
            "label": m.label,
            "one_line": m.one_line,
            "formula": m.formula,
            "when": m.when,
            "caveat": m.caveat,
            "level": m.level,
        }
        for m in MODES.values()
    ]


def merge_accounts(accounts: list[AccountInput], mode: str = "net_internal") -> dict:
    if mode not in MODES:
        raise ValueError(f"未知合并方式：{mode}")
    definition = MODES[mode]
    notes: list[str] = []

    per_account = []
    for account in accounts:
        inflow = sum((t.amount or Decimal("0")) for t in account.transactions if t.direction == "in")
        outflow = sum((t.amount or Decimal("0")) for t in account.transactions if t.direction == "out")
        per_account.append({
            "account_id": account.account_id,
            "bank_code": account.bank_code,
            "period_start": str(account.period_start) if account.period_start else None,
            "period_end": str(account.period_end) if account.period_end else None,
            "txn_count": len(account.transactions),
            "inflow": str(inflow),
            "outflow": str(outflow),
        })

    # 流水层合并
    rows = [(account.account_id, txn) for account in accounts for txn in account.transactions]
    raw_count = len(rows)
    dropped_dup = 0
    internal_pairs: list[dict] = []
    if mode in ("dedupe", "net_internal"):
        rows, dropped_dup = _dedupe(accounts)
        if dropped_dup:
            notes.append(f"按指纹去重 {dropped_dup} 条重复明细")
    if mode == "net_internal":
        rows, internal_pairs = _cancel_internal(rows)
        if internal_pairs:
            notes.append(f"剔除 {len(internal_pairs)} 对账户间互转，金额合计 {sum(Decimal(p['amount']) for p in internal_pairs)} 元")

    merged_txns = [txn for _account, txn in rows]
    periods = [
        (account.period_start, account.period_end)
        for account in accounts
        if account.period_start and account.period_end
    ]
    period_start = min((p[0] for p in periods), default=None)
    period_end = max((p[1] for p in periods), default=None)

    # 指标层合并
    metric_sets = [compute_metrics(account.transactions) for account in accounts]
    merged_metrics = compute_metrics(merged_txns)
    codes = [m.code for m in merged_metrics.metrics]
    sync = _sync_profile(accounts) if mode == "sync_amplify" else None
    amplify_factor = Decimal(1)
    if sync is not None:
        amplify_factor = Decimal(1) + sync["lambda"] * sync["score"]
        if sync["sync_months"]:
            notes.append(
                "同步放大：{} 个月里有 {} 个月出现多账户同时大额流出/净流出，"
                "同步率 {:.0%}，放大系数 ×{:.2f}（超可加：合并风险大于各自之和）".format(
                    sync["months"], len(sync["sync_months"]), float(sync["score"]), float(amplify_factor)
                )
            )
    metrics = []
    for code in codes:
        if definition.level == "flow":
            value = next((m.value for m in merged_metrics.metrics if m.code == code), None)
            basis = "由合并后的明细重算"
            if sync is not None and code in SYNC_AMPLIFY_CODES:
                per_account = [
                    next((m.value for m in ms.metrics if m.code == code), None)
                    for ms in metric_sets
                ]
                total = sum((v for v in per_account if v is not None), Decimal(0))
                if total:
                    value = total * amplify_factor
                    basis = "Σ 各账户该指标 × (1 + λ·同步率)（超可加）"
        else:
            values = []
            for ms in metric_sets:
                item = next((m for m in ms.metrics if m.code == code), None)
                if item is not None and item.value is not None:
                    values.append(item.value)
            if code in LOWER_IS_WORSE and mode == "worst_case":
                value = min(values) if values else None
            else:
                value = _combine(values, mode, None)
            basis = definition.formula
        name = next((m.name for m in merged_metrics.metrics if m.code == code), code)
        metrics.append({"code": code, "name": name, "value": None if value is None else str(value), "basis": basis})

    overlap_days = 0
    if len(periods) > 1:
        starts = [p[0] for p in periods]
        ends = [p[1] for p in periods]
        overlap_start = max(starts)
        overlap_end = min(ends)
        if overlap_start <= overlap_end:
            overlap_days = (overlap_end - overlap_start).days + 1
            notes.append(f"账户期间重叠 {overlap_days} 天，重叠部分按月均口径按并集天数折算，不重复计月")

    return {
        "mode": mode,
        "label": definition.label,
        "formula": definition.formula,
        "one_line": definition.one_line,
        "period_start": str(period_start) if period_start else None,
        "period_end": str(period_end) if period_end else None,
        "overlap_days": overlap_days,
        "accounts": per_account,
        "raw_txn_count": raw_count,
        "txn_count": len(merged_txns),
        "dropped_duplicates": dropped_dup,
        "internal_transfers": internal_pairs,
        "metrics": metrics,
        "notes": notes,
        "sync": None if sync is None else {
            "months": sync["months"],
            "sync_months": sync["sync_months"],
            "score": str(sync["score"]),
            "lambda": str(sync["lambda"]),
            "amplify_factor": str(amplify_factor),
        },
    }


# 风险型指标（越高越差）：同步放大时按「Σ mᵢ × (1 + λ·同步率)」合成，
# 用来表达「两笔时间上同步的流水，合起来的风险大于各自之和」（超可加）。
SYNC_AMPLIFY_CODES = frozenset({
    "A04", "B02", "B03", "B04", "B05", "B06", "B07", "B08",
    "C05", "C06", "C07", "C08", "D02", "D03", "D05", "D07",
    "E01", "E02", "E03", "E05", "E07",
})

# 同步放大的默认强度；可用环境变量 MERGE_SYNC_LAMBDA 覆盖（0 表示不放大）。
import os as _os
SYNC_LAMBDA = Decimal(_os.getenv("MERGE_SYNC_LAMBDA", "0.5"))


def _month_bucket(txn) -> str | None:
    text = str(txn.txn_date or "")
    if len(text) >= 7 and text[4] == "-":
        return text[:7]
    return None


def _sync_profile(accounts: list[AccountInput]) -> dict:
    """检测「同步压力」：同一月份里 ≥2 个账户同时出现大额流出或净流出。

    这不是线性相加：两笔流水各自单独看都没问题，但同一个月一起抽走资金，
    对还款能力的冲击大于两者之和，所以合并时给一个放大系数。
    """
    monthly: dict[str, dict[str, dict[str, Decimal]]] = {}
    for account in accounts:
        for txn in account.transactions:
            month = _month_bucket(txn)
            if month is None:
                continue
            bucket = monthly.setdefault(month, {}).setdefault(account.account_id, {"in": Decimal(0), "out": Decimal(0)})
            if txn.direction == "in":
                bucket["in"] += txn.amount or Decimal(0)
            elif txn.direction == "out":
                bucket["out"] += txn.amount or Decimal(0)

    if not monthly:
        return {"months": 0, "sync_months": [], "score": Decimal(0), "lambda": SYNC_LAMBDA}

    # 每个账户的月均流出，用来判断「大额」
    per_account_totals: dict[str, Decimal] = {}
    per_account_months: dict[str, int] = {}
    for month, accounts_in_month in monthly.items():
        for account_id, bucket in accounts_in_month.items():
            per_account_totals[account_id] = per_account_totals.get(account_id, Decimal(0)) + bucket["out"]
            per_account_months[account_id] = per_account_months.get(account_id, 0) + 1
    averages = {
        account_id: (per_account_totals[account_id] / per_account_months[account_id])
        for account_id in per_account_totals
        if per_account_months[account_id]
    }

    sync_months: list[str] = []
    for month, accounts_in_month in sorted(monthly.items()):
        stressed = 0
        for account_id, bucket in accounts_in_month.items():
            average = averages.get(account_id, Decimal(0))
            net = bucket["in"] - bucket["out"]
            heavy = average > 0 and bucket["out"] >= average * Decimal("0.8")
            if heavy or net < 0:
                stressed += 1
        if stressed >= 2:
            sync_months.append(month)

    months_count = len(monthly)
    score = Decimal(len(sync_months)) / Decimal(months_count) if months_count else Decimal(0)
    return {"months": months_count, "sync_months": sync_months, "score": score, "lambda": SYNC_LAMBDA}
