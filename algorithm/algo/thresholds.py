from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field

from ..ocr.models import Transaction
from .evidence import txn_evidence
from .exclusions import analyze_exclusions
from .hits import HitResult
from .metrics import (
    SAME_DAY_TOLERANCE,
    MetricSet,
    _CRYPTO,
    _LOAN,
    _LOAN_COUNTERPARTY,
    _REPAY,
    _SMALL_LOAN,
    _has,
    _hour,
    _months_before,
    _parse_date,
)
from .models import Evidence

THRESHOLD_VERSION = 2
MAX_CONCLUSION_EVIDENCE = 20
ConclusionLevel = Literal["info"]


class ThresholdConfig(BaseModel):
    """默认阈值随系统发布；银行可改，改后升版本，旧报告不重写。

    v2 新增项中标注「未校准」的默认值为算法组暂定，待业务确认或样本校准后定稿。
    """

    version: int = THRESHOLD_VERSION
    dti_high: Decimal = Decimal("0.5")
    income_cv_high: Decimal = Decimal("0.5")
    low_balance_multiple: Decimal = Decimal("1.0")
    loan_platform_count: int = 3
    gambling_hit_count: int = 1
    night_ratio: Decimal = Decimal("0.1")
    # v2
    net_outflow_ratio: Decimal = Decimal("0.3")
    net_outflow_consecutive_months: int = 2
    net_outflow_month_floor: Decimal = Decimal("100")  # 未校准
    balance_decline_ratio: Decimal = Decimal("0.1")
    balance_decline_windows: int = 3
    fast_in_out_ratio: Decimal = Decimal("0.2")
    fast_in_out_min_amount: Decimal = Decimal("500")  # 未校准
    fast_in_out_min_txns: int = 3
    counterparty_min_txns: int = 20
    counterparty_missing_ratio: Decimal = Decimal("0.2")
    counterparty_hhi: Decimal | None = None  # 未校准；None = 不判定
    new_loan_min_count: int = 1
    new_loan_min_income_ratio: Decimal = Decimal("0.3")  # 未校准
    small_loan_repay_min_monthly: int = 1
    crypto_min_count: int = 1
    crypto_min_amount: Decimal = Decimal("1000")  # 未校准


DEFAULT_THRESHOLDS = ThresholdConfig()


def export_thresholds(config: ThresholdConfig | None = None) -> str:
    """整版阈值快照（JSON），供数据组建表种子与后端按版本归档。"""
    config = config or DEFAULT_THRESHOLDS
    return config.model_dump_json(indent=2)


class Conclusion(BaseModel):
    code: str
    level: ConclusionLevel = "info"
    threshold: str
    value: str


class ThresholdResult(BaseModel):
    version: int
    conclusions: list[Conclusion] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    # 每条结论所依据的明细行；rule_code 取结论 code，便于审批人跳回原页
    evidence: list[Evidence] = Field(default_factory=list)


def _fmt(value: Decimal | int) -> str:
    if isinstance(value, int):
        return str(value)
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _value(metrics: MetricSet, code: str) -> Decimal | None:
    return metrics.by_code(code).value


def _month_net(
    transactions: list[Transaction],
) -> tuple[dict[tuple[int, int], Decimal], Decimal, Decimal]:
    by_month: dict[tuple[int, int], Decimal] = {}
    total_in = Decimal("0")
    total_out = Decimal("0")
    for txn in transactions:
        if txn.amount is None:
            continue
        if txn.direction == "in":
            total_in += txn.amount
        else:
            total_out += txn.amount
        day = _parse_date(txn.txn_date)
        if day is not None:
            key = (day.year, day.month)
            sign = Decimal("1") if txn.direction == "in" else Decimal("-1")
            by_month[key] = by_month.get(key, Decimal("0")) + sign * txn.amount
    return by_month, total_in, total_out


def _month_balances(
    transactions: list[Transaction],
) -> dict[tuple[int, int], list[Decimal]]:
    result: dict[tuple[int, int], list[Decimal]] = {}
    for txn in transactions:
        day = _parse_date(txn.txn_date)
        if day is not None and txn.balance is not None:
            result.setdefault((day.year, day.month), []).append(txn.balance)
    return result


def _month_span(
    start: tuple[int, int], end: tuple[int, int]
) -> list[tuple[int, int]]:
    """自然月序列；缺交易的月也要出现，避免把非连续月份当成连续。"""
    result: list[tuple[int, int]] = []
    year, month = start
    while (year, month) <= end:
        result.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def _last_balance(
    transactions: list[Transaction], key: tuple[int, int]
) -> Decimal | None:
    """指定月内日期最新一笔的余额；同日按行序取后者，不依赖文件整体顺序。"""
    latest: tuple[tuple[date, int], Decimal] | None = None
    for txn in transactions:
        day = _parse_date(txn.txn_date)
        if day is None or (day.year, day.month) != key or txn.balance is None:
            continue
        marker = (day, txn.row_no or 0)
        if latest is None or marker > latest[0]:
            latest = (marker, txn.balance)
    return latest[1] if latest else None


def _last_balance_txn(
    transactions: list[Transaction], key: tuple[int, int]
) -> Transaction | None:
    latest: tuple[tuple[date, int], Transaction] | None = None
    for txn in transactions:
        day = _parse_date(txn.txn_date)
        if day is None or (day.year, day.month) != key or txn.balance is None:
            continue
        marker = (day, txn.row_no or 0)
        if latest is None or marker > latest[0]:
            latest = (marker, txn)
    return latest[1] if latest else None


def _month_txns(
    transactions: list[Transaction],
) -> dict[tuple[int, int], list[Transaction]]:
    result: dict[tuple[int, int], list[Transaction]] = {}
    for txn in transactions:
        day = _parse_date(txn.txn_date)
        if day is not None:
            result.setdefault((day.year, day.month), []).append(txn)
    return result


def _recent_loan_txns(
    transactions: list[Transaction], end: date | None
) -> list[Transaction]:
    if end is None:
        return []
    window_start = _months_before(end, 6)
    return [
        txn
        for txn in transactions
        if (day := _parse_date(txn.txn_date)) is not None
        and window_start <= day <= end
        and txn.direction == "in"
        and (_has(txn.summary, _LOAN) or _has(txn.counterparty_name, _LOAN_COUNTERPARTY))
    ]


def _month_end_inflows(
    transactions: list[Transaction], kept: set[int]
) -> list[Transaction]:
    """每月最后一笔未剔除入账，用作月收入序列的回指行。"""
    latest: dict[tuple[int, int], tuple[tuple[date, int], Transaction]] = {}
    for index, txn in enumerate(transactions):
        if index not in kept or txn.direction != "in" or txn.amount is None:
            continue
        day = _parse_date(txn.txn_date)
        if day is None:
            continue
        key = (day.year, day.month)
        marker = (day, txn.row_no or 0)
        if key not in latest or marker > latest[key][0]:
            latest[key] = (marker, txn)
    return [latest[key][1] for key in sorted(latest)]


def evaluate_thresholds(
    metrics: MetricSet,
    *,
    hits: HitResult | None = None,
    config: ThresholdConfig | None = None,
    monthly_payment: Decimal | None = None,
    transactions: list[Transaction] | None = None,
) -> ThresholdResult:
    """按阈值给出提示结论；阈值只影响提示，不影响五态真伪结论。

    transactions 可选：传入时净流出、余额下降、当日进出、对手方缺失率与
    放款/涉币金额条件按原始明细计算；不传则相应项只记录不判定。
    """
    config = config or DEFAULT_THRESHOLDS
    conclusions: list[Conclusion] = []
    notes: list[str] = []
    evidence: list[Evidence] = []

    def add_evidence(code: str, items: list[Transaction]) -> None:
        """给结论挂触发依据；只取前 20 笔，够回指原页即可。"""
        for txn in items[:MAX_CONCLUSION_EVIDENCE]:
            evidence.append(txn_evidence(txn, code))

    kept: set[int] = set()
    repay_txns: list[Transaction] = []
    small_loan_txns: list[Transaction] = []
    recent_loans: list[Transaction] = []
    if transactions:
        kept = set(analyze_exclusions(transactions).kept_indices)
        repay_txns = [
            txn
            for txn in transactions
            if txn.direction == "out"
            and txn.amount is not None
            and _has(txn.summary, _REPAY)
        ]
        small_loan_txns = [
            txn
            for txn in transactions
            if txn.direction == "out" and _has(txn.summary, _SMALL_LOAN)
        ]
        end = metrics.period_end
        if end is None:
            days = [_parse_date(txn.txn_date) for txn in transactions]
            end = max((day for day in days if day is not None), default=None)
        recent_loans = _recent_loan_txns(transactions, end)

    dti = _value(metrics, "B02")
    if dti is not None and dti >= config.dti_high:
        conclusions.append(
            Conclusion(code="DTI_HIGH", threshold=_fmt(config.dti_high), value=_fmt(dti))
        )
        add_evidence("DTI_HIGH", repay_txns)

    income_cv = _value(metrics, "A04")
    if income_cv is not None and income_cv >= config.income_cv_high:
        conclusions.append(
            Conclusion(
                code="INCOME_UNSTABLE",
                threshold=_fmt(config.income_cv_high),
                value=_fmt(income_cv),
            )
        )
        add_evidence("INCOME_UNSTABLE", _month_end_inflows(transactions or [], kept))

    lowest = _value(metrics, "C06")
    payment = monthly_payment
    if payment is None:
        payment = _value(metrics, "B01")
        if payment is not None and payment > 0:
            notes.append("最低余额阈值以 B01 月还款近似月供，未使用当地月供")
    if lowest is not None and payment is not None and payment > 0:
        line = payment * config.low_balance_multiple
        if lowest < line:
            conclusions.append(
                Conclusion(
                    code="LOW_BALANCE",
                    threshold=_fmt(line),
                    value=_fmt(lowest),
                )
            )
            picks: list[Transaction] = []
            start = metrics.period_start
            end = metrics.period_end
            if transactions and start and end:
                window_start = max(start, end - timedelta(days=29))
                candidates = [
                    txn
                    for txn in transactions
                    if txn.balance is not None
                    and (day := _parse_date(txn.txn_date)) is not None
                    and window_start <= day <= end
                ]
                if candidates:
                    picks = [min(candidates, key=lambda txn: (txn.balance, -(txn.row_no or 0)))]
            add_evidence("LOW_BALANCE", picks)
    elif lowest is not None:
        notes.append("缺月供与 B01，未判定最低余额阈值")

    platforms = _value(metrics, "B04")
    if platforms is not None and platforms >= config.loan_platform_count:
        conclusions.append(
            Conclusion(
                code="MULTI_LOAN",
                threshold=str(config.loan_platform_count),
                value=_fmt(platforms),
            )
        )
        seen_names: set[str] = set()
        platform_picks: list[Transaction] = []
        for txn in recent_loans:
            name = (txn.counterparty_name or "").strip()
            if name and name not in seen_names:
                seen_names.add(name)
                platform_picks.append(txn)
        add_evidence("MULTI_LOAN", platform_picks)

    if hits is None:
        notes.append("未传入规则命中，未判定涉赌阈值")
    else:
        gambling = hits.tag_txn_counts.get("GAMBLING", 0)
        if gambling >= config.gambling_hit_count:
            conclusions.append(
                Conclusion(
                    code="GAMBLING_HIT",
                    threshold=str(config.gambling_hit_count),
                    value=str(gambling),
                )
            )
            if transactions and len(hits.labels) == len(transactions):
                gambling_txns = [
                    txn
                    for txn, labels in zip(transactions, hits.labels)
                    if "GAMBLING" in {name.upper() for name in labels}
                ]
                add_evidence("GAMBLING_HIT", gambling_txns)

    night = _value(metrics, "D02")
    if night is not None and night > config.night_ratio:
        conclusions.append(
            Conclusion(
                code="NIGHT_TRADING",
                threshold=_fmt(config.night_ratio),
                value=_fmt(night),
            )
        )
        night_txns = [
            txn
            for txn in transactions or []
            if (hour := _hour(txn.trade_time)) is not None and (hour >= 22 or hour < 6)
        ]
        add_evidence("NIGHT_TRADING", night_txns)

    # v2：净流出（占比分支 或 连续月分支，单月需超过金额下限）
    if transactions:
        by_month, total_in, total_out = _month_net(transactions)
        month_map = _month_txns(transactions)
        net = total_in - total_out
        ratio = (-net) / total_in if net < 0 and total_in > 0 else None
        if ratio is not None and ratio >= config.net_outflow_ratio:
            conclusions.append(
                Conclusion(
                    code="NET_OUTFLOW",
                    threshold=_fmt(config.net_outflow_ratio),
                    value=_fmt(ratio.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
                )
            )
            negative_months = [key for key in sorted(by_month) if by_month[key] < 0]
            add_evidence(
                "NET_OUTFLOW",
                [month_map[key][-1] for key in negative_months if month_map.get(key)],
            )
        else:
            run = best = 0
            qualifying_months: list[tuple[int, int]] = []
            for key in _month_span(min(by_month), max(by_month)):
                if by_month.get(key, Decimal("0")) <= -config.net_outflow_month_floor:
                    run += 1
                    best = max(best, run)
                    qualifying_months.append(key)
                else:
                    run = 0
            if best >= config.net_outflow_consecutive_months:
                conclusions.append(
                    Conclusion(
                        code="NET_OUTFLOW",
                        threshold=(
                            f"连续 {config.net_outflow_consecutive_months} 个月净流出"
                            f"（单月≥{_fmt(config.net_outflow_month_floor)} 元）"
                        ),
                        value=f"{best} 个月",
                    )
                )
                add_evidence(
                    "NET_OUTFLOW",
                    [month_map[key][-1] for key in qualifying_months if month_map.get(key)],
                )
    else:
        c01 = _value(metrics, "C01")
        if c01 is not None and c01 < 0:
            notes.append("未传交易明细，净流出仅按 C01 记录，未判定占比与连续月")

    # v2：月均余额下降率 + 期末余额低于月供线
    if transactions:
        month_balances = _month_balances(transactions)
        keys = sorted(month_balances)
        windows = config.balance_decline_windows
        if len(keys) >= windows * 2:
            averages = [
                sum(month_balances[key], Decimal("0")) / Decimal(len(month_balances[key]))
                for key in keys
            ]
            earlier = sum(averages[:windows], Decimal("0")) / Decimal(windows)
            later = sum(averages[-windows:], Decimal("0")) / Decimal(windows)
            decline = (
                ((later - earlier) / earlier).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                )
                if earlier > 0
                else None
            )
            last_balance = _last_balance(transactions, keys[-1])
            if decline is not None and decline <= -config.balance_decline_ratio:
                if payment is not None and payment > 0 and last_balance is not None:
                    line = payment * config.low_balance_multiple
                    if last_balance < line:
                        conclusions.append(
                            Conclusion(
                                code="BALANCE_DECLINE",
                                threshold=(
                                    f"月均余额降 {_fmt(config.balance_decline_ratio * 100)}%"
                                    f"且期末低于 {_fmt(line)}"
                                ),
                                value=f"{_fmt(decline * 100)}%（期末 {_fmt(last_balance)}）",
                            )
                        )
                        last_txn = _last_balance_txn(transactions, keys[-1])
                        add_evidence("BALANCE_DECLINE", [last_txn] if last_txn else [])
                else:
                    notes.append("缺月供与 B01，未判定月均余额下降的期末余额条件")
        elif keys:
            notes.append(f"有效月数 {len(keys)} < {windows * 2}，未判定月均余额下降")
    else:
        notes.append("未传交易明细，未判定月均余额下降")

    # v2：当日进出（占比 + 当日进金额下限 + 有效笔数）
    if transactions:
        day_in: dict[date, Decimal] = {}
        day_out: dict[date, Decimal] = {}
        day_count: dict[date, int] = {}
        for txn in transactions:
            if txn.amount is None:
                continue
            day = _parse_date(txn.txn_date)
            if day is None:
                continue
            day_count[day] = day_count.get(day, 0) + 1
            if txn.direction == "in":
                day_in[day] = day_in.get(day, Decimal("0")) + txn.amount
            else:
                day_out[day] = day_out.get(day, Decimal("0")) + txn.amount
        qualifying = 0
        qualifying_days: set[date] = set()
        for day in set(day_in) & set(day_out):
            high = max(day_in[day], day_out[day])
            close = (
                high > 0
                and min(day_in[day], day_out[day]) / high
                >= Decimal("1") - SAME_DAY_TOLERANCE
            )
            if close and day_in[day] >= config.fast_in_out_min_amount:
                qualifying_days.add(day)
                qualifying += day_count[day]
        if qualifying >= config.fast_in_out_min_txns:
            ratio = (Decimal(qualifying) / Decimal(len(transactions))).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
            if ratio > config.fast_in_out_ratio:
                conclusions.append(
                    Conclusion(
                        code="FAST_IN_OUT",
                        threshold=(
                            f"{_fmt(config.fast_in_out_ratio)}（当日进≥"
                            f"{_fmt(config.fast_in_out_min_amount)} 元、"
                            f"有效笔数≥{config.fast_in_out_min_txns}）"
                        ),
                        value=_fmt(ratio),
                    )
                )
                add_evidence(
                    "FAST_IN_OUT",
                    [
                        txn
                        for txn in transactions
                        if (day := _parse_date(txn.txn_date)) in qualifying_days
                    ],
                )
    else:
        c08 = _value(metrics, "C08")
        if c08 is not None and c08 > config.fast_in_out_ratio:
            notes.append("未传交易明细，当日进出仅按 C08 记录，未核金额与笔数条件")

    # v2：对手方集中度（笔数门槛 + 缺失率告警 + 校准后 HHI）
    if transactions:
        named = [txn for txn in transactions if (txn.counterparty_name or "").strip()]
        missing = len(transactions) - len(named)
        if missing / len(transactions) > config.counterparty_missing_ratio:
            rate = (Decimal(missing) / Decimal(len(transactions)) * 100).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            notes.append(
                f"对手方缺失率 {_fmt(rate)}%"
                f"（{missing}/{len(transactions)} 笔无对手方），"
                "E01/E02 仅按有对手方笔数计算，集中度结论可能失真"
            )
        masked = sum(
            1
            for txn in named
            if set((txn.counterparty_name or "").strip()) <= {"*", "#"}
        )
        if masked:
            notes.append(f"{masked} 笔对手方为掩码名称，E01/E02 集中度可能失真")
        if len(named) < config.counterparty_min_txns:
            notes.append(
                f"有效对手方笔数 {len(named)} < {config.counterparty_min_txns}，"
                "未判定对手方集中度"
            )
        elif config.counterparty_hhi is None:
            notes.append("HHI 阈值未校准（待样本 P95 或业务确认），暂不判定对手方集中度")
        else:
            hhi = _value(metrics, "E01")
            if hhi is not None and hhi >= config.counterparty_hhi:
                conclusions.append(
                    Conclusion(
                        code="COUNTERPARTY_CONCENTRATED",
                        threshold=_fmt(config.counterparty_hhi),
                        value=_fmt(hhi),
                    )
                )
                totals: dict[str, Decimal] = {}
                for txn in transactions:
                    if txn.amount is None:
                        continue
                    name = (txn.counterparty_name or "").strip()
                    if name:
                        totals[name] = totals.get(name, Decimal("0")) + txn.amount
                if totals:
                    top_name = max(totals, key=lambda name: totals[name])
                    add_evidence(
                        "COUNTERPARTY_CONCENTRATED",
                        [
                            txn
                            for txn in transactions
                            if (txn.counterparty_name or "").strip() == top_name
                        ],
                    )
    else:
        notes.append("未传交易明细，未判定对手方缺失率与集中度")

    # v2：新增贷款（笔数 + 金额≥月均收入比例，线索项）
    loan_count = _value(metrics, "B03")
    if loan_count is not None and loan_count >= config.new_loan_min_count:
        if transactions:
            amount = sum((txn.amount or Decimal("0")) for txn in recent_loans)
            a02 = _value(metrics, "A02")
            if a02 is not None and a02 > 0 and amount >= a02 * config.new_loan_min_income_ratio:
                conclusions.append(
                    Conclusion(
                        code="NEW_LOAN",
                        threshold=(
                            f"≥{config.new_loan_min_count} 笔且放款金额≥月均收入×"
                            f"{_fmt(config.new_loan_min_income_ratio)}"
                        ),
                        value=f"{loan_count} 笔 {_fmt(amount)} 元",
                    )
                )
                add_evidence("NEW_LOAN", recent_loans)
            elif a02 is not None and a02 > 0:
                notes.append(
                    f"近 6 个月放款金额 {_fmt(amount)} 元 < 月均收入×"
                    f"{_fmt(config.new_loan_min_income_ratio)}，仅记录不提示"
                )
        else:
            notes.append("未传交易明细，未核放款金额条件")

    # v2：小贷还款（月均频率，线索项）
    repay_count = _value(metrics, "B05")
    coverage = metrics.coverage_months
    if repay_count is not None and repay_count > 0 and coverage:
        if repay_count >= config.small_loan_repay_min_monthly * coverage:
            conclusions.append(
                Conclusion(
                    code="SMALL_LOAN_REPAY",
                    threshold=f"月均≥{config.small_loan_repay_min_monthly} 笔（覆盖 {coverage} 个月）",
                    value=f"{repay_count} 笔",
                )
            )
            add_evidence("SMALL_LOAN_REPAY", small_loan_txns)
        else:
            notes.append(
                f"小贷还款 {repay_count} 笔 < 月均 {config.small_loan_repay_min_monthly} 笔"
                f"（覆盖 {coverage} 个月），仅记录不提示"
            )

    # v2：涉币交易（笔数 + 金额下限，线索项）
    if transactions:
        if hits is not None and len(hits.labels) == len(transactions):
            crypto = [
                txn
                for txn, labels in zip(transactions, hits.labels)
                if "CRYPTO" in {name.upper() for name in labels}
            ]
        else:
            crypto = [txn for txn in transactions if _has(txn.summary, _CRYPTO)]
        amount = sum((txn.amount or Decimal("0")) for txn in crypto)
        if len(crypto) >= config.crypto_min_count and amount >= config.crypto_min_amount:
            conclusions.append(
                Conclusion(
                    code="CRYPTO_HIT",
                    threshold=(
                        f"≥{config.crypto_min_count} 笔且金额≥"
                        f"{_fmt(config.crypto_min_amount)} 元"
                    ),
                    value=f"{len(crypto)} 笔 {_fmt(amount)} 元",
                )
            )
            add_evidence("CRYPTO_HIT", crypto)
        elif crypto:
            notes.append(
                f"涉币交易金额 {_fmt(amount)} 元 < {_fmt(config.crypto_min_amount)} 元，"
                "仅记录不提示"
            )
    else:
        e06 = _value(metrics, "E06")
        if e06 is not None and e06 > 0:
            notes.append("未传交易明细，涉币仅按 E06 记录，未核金额条件")

    return ThresholdResult(
        version=config.version,
        conclusions=conclusions,
        notes=notes,
        evidence=evidence,
    )
