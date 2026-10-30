from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field

from ..ocr.models import Transaction
from .hits import HitResult
from .metrics import (
    SAME_DAY_TOLERANCE,
    MetricSet,
    _CRYPTO,
    _LOAN,
    _LOAN_COUNTERPARTY,
    _SMALL_LOAN,
    _has,
    _months_before,
    _parse_date,
)

THRESHOLD_VERSION = 2
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

    dti = _value(metrics, "B02")
    if dti is not None and dti >= config.dti_high:
        conclusions.append(
            Conclusion(code="DTI_HIGH", threshold=_fmt(config.dti_high), value=_fmt(dti))
        )

    income_cv = _value(metrics, "A04")
    if income_cv is not None and income_cv >= config.income_cv_high:
        conclusions.append(
            Conclusion(
                code="INCOME_UNSTABLE",
                threshold=_fmt(config.income_cv_high),
                value=_fmt(income_cv),
            )
        )

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

    night = _value(metrics, "D02")
    if night is not None and night > config.night_ratio:
        conclusions.append(
            Conclusion(
                code="NIGHT_TRADING",
                threshold=_fmt(config.night_ratio),
                value=_fmt(night),
            )
        )

    # v2：净流出（占比分支 或 连续月分支，单月需超过金额下限）
    if transactions:
        by_month, total_in, total_out = _month_net(transactions)
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
        else:
            run = best = 0
            for key in _month_span(min(by_month), max(by_month)):
                if by_month.get(key, Decimal("0")) <= -config.net_outflow_month_floor:
                    run += 1
                    best = max(best, run)
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
        for day in set(day_in) & set(day_out):
            high = max(day_in[day], day_out[day])
            close = (
                high > 0
                and min(day_in[day], day_out[day]) / high
                >= Decimal("1") - SAME_DAY_TOLERANCE
            )
            if close and day_in[day] >= config.fast_in_out_min_amount:
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
    else:
        notes.append("未传交易明细，未判定对手方缺失率与集中度")

    # v2：新增贷款（笔数 + 金额≥月均收入比例，线索项）
    loan_count = _value(metrics, "B03")
    if loan_count is not None and loan_count >= config.new_loan_min_count:
        if transactions:
            end = metrics.period_end
            if end is None:
                days = [_parse_date(txn.txn_date) for txn in transactions]
                end = max((day for day in days if day is not None), default=None)
            if end is not None:
                window_start = _months_before(end, 6)
                amount = sum(
                    (
                        txn.amount or Decimal("0")
                        for txn in transactions
                        if (day := _parse_date(txn.txn_date)) is not None
                        and window_start <= day <= end
                        and txn.direction == "in"
                        and (
                            _has(txn.summary, _LOAN)
                            or _has(txn.counterparty_name, _LOAN_COUNTERPARTY)
                        )
                    ),
                    Decimal("0"),
                )
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
                elif a02 is not None and a02 > 0:
                    notes.append(
                        f"近 6 个月放款金额 {_fmt(amount)} 元 < 月均收入×"
                        f"{_fmt(config.new_loan_min_income_ratio)}，仅记录不提示"
                    )
            else:
                notes.append("缺交易日期，未核放款金额条件")
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
    )


@dataclass(frozen=True)
class ThresholdDef:
    """一个可调参数的定义：给页面渲染、给后端校验、给报告解释用。"""
    key: str
    label: str
    group: str
    kind: str  # ratio | amount | int | int_optional
    unit: str
    default: str | int | None
    minimum: str | int | None
    maximum: str | int | None
    desc: str
    impacts: tuple[str, ...]
    calibrated: bool = True


THRESHOLD_DEFS: tuple[ThresholdDef, ...] = (
    # 收入能力
    ThresholdDef("income_cv_high", "收入波动上限（CV）", "收入能力", "ratio", "倍",
                 "0.5", "0.05", "3", "月度收入变异系数超过该值判定收入不稳定。", ("INCOME_UNSTABLE",)),
    ThresholdDef("dti_high", "债务收入比上限（DTI）", "收入能力", "ratio", "倍",
                 "0.5", "0.05", "2", "月还款 ÷ 月均收入超过该值判定负债偏高。", ("DTI_HIGH",)),
    # 负债与还款
    ThresholdDef("loan_platform_count", "网贷平台数上限", "负债与还款", "int", "家",
                 3, 1, 50, "出现过的网贷平台超过该家数判定多头借贷。", ("MULTI_LOAN",)),
    ThresholdDef("small_loan_repay_min_monthly", "小额贷款月还款次数上限", "负债与还款", "int", "次/月",
                 1, 0, 50, "小额贷款类还款每月超过该次数判定小额贷依赖。", ("SMALL_LOAN_REPAY",)),
    ThresholdDef("new_loan_min_count", "新增贷款笔数下限", "负债与还款", "int", "笔",
                 1, 1, 100, "观察期内新增贷款达到该笔数判定新增负债。", ("NEW_LOAN",)),
    ThresholdDef("new_loan_min_income_ratio", "新增贷款占比下限", "负债与还款", "ratio", "倍",
                 "0.3", "0", "5", "新增贷款金额占期间收入达到该比例才判定（未校准）。", ("NEW_LOAN",), calibrated=False),
    # 资金与余额
    ThresholdDef("low_balance_multiple", "低余额倍数", "资金与余额", "ratio", "倍",
                 "1.0", "0", "10", "期末余额低于「月均支出 × 该倍数」判定余额偏低。", ("LOW_BALANCE",)),
    ThresholdDef("net_outflow_ratio", "净流出比例阈值", "资金与余额", "ratio", "倍",
                 "0.3", "0", "5", "某月净流出超过月均收入该比例计为净流出月。", ("NET_OUTFLOW",)),
    ThresholdDef("net_outflow_consecutive_months", "净流出连续月数", "资金与余额", "int", "个月",
                 2, 1, 24, "连续净流出达到该月数判定资金紧张。", ("NET_OUTFLOW",)),
    ThresholdDef("net_outflow_month_floor", "净流出最小金额", "资金与余额", "amount", "元",
                 "100", "0", "1000000", "净流出低于该金额的月份不计入（未校准）。", ("NET_OUTFLOW",), calibrated=False),
    ThresholdDef("balance_decline_ratio", "余额下降幅度", "资金与余额", "ratio", "倍",
                 "0.1", "0", "5", "余额在一段时间内下降超过该比例判定余额下滑。", ("BALANCE_DECLINE",)),
    ThresholdDef("balance_decline_windows", "余额下滑观察窗口", "资金与余额", "int", "个月",
                 3, 1, 24, "用最近多少个月观察余额下滑。", ("BALANCE_DECLINE",)),
    ThresholdDef("fast_in_out_ratio", "快进快出比例", "资金与余额", "ratio", "倍",
                 "0.2", "0", "5", "入账后短时间内大比例转出判定快进快出。", ("FAST_IN_OUT",)),
    ThresholdDef("fast_in_out_min_amount", "快进快出最小金额", "资金与余额", "amount", "元",
                 "500", "0", "1000000", "低于该金额的快速转出不计入（未校准）。", ("FAST_IN_OUT",), calibrated=False),
    ThresholdDef("fast_in_out_min_txns", "快进快出最少笔数", "资金与余额", "int", "笔",
                 3, 1, 100, "达到该笔数才判定快进快出。", ("FAST_IN_OUT",)),
    # 对手方与集中度
    ThresholdDef("counterparty_min_txns", "集中度最小样本笔数", "对手方与集中度", "int", "笔",
                 20, 1, 10000, "少于该笔数不做集中度判定（样本不足）。", ("COUNTERPARTY_CONCENTRATED",)),
    ThresholdDef("counterparty_missing_ratio", "对手方缺失比例上限", "对手方与集中度", "ratio", "倍",
                 "0.2", "0", "1", "对手方信息缺失超过该比例时集中度结论降级。", ("COUNTERPARTY_CONCENTRATED",)),
    ThresholdDef("counterparty_hhi", "HHI 集中度阈值", "对手方与集中度", "ratio", "指数",
                 None, "0", "1", "HHI 超过该值判定集中度高；留空 = 不判定（未校准）。", ("COUNTERPARTY_CONCENTRATED",), calibrated=False),
    # 异常行为
    ThresholdDef("gambling_hit_count", "博彩命中次数", "异常行为", "int", "次",
                 1, 1, 100, "命中博彩类对手方达到该次数判定。", ("GAMBLING_HIT",)),
    ThresholdDef("night_ratio", "夜间交易占比", "异常行为", "ratio", "倍",
                 "0.1", "0", "1", "夜间（默认 0-6 点）交易占比超过该值判定。", ("NIGHT_TRADING",)),
    ThresholdDef("crypto_min_count", "虚拟币交易笔数", "异常行为", "int", "笔",
                 1, 1, 100, "虚拟币相关交易达到该笔数判定。", ("CRYPTO_HIT",)),
    ThresholdDef("crypto_min_amount", "虚拟币最小金额", "异常行为", "amount", "元",
                 "1000", "0", "10000000", "虚拟币交易金额达到该值才计入（未校准）。", ("CRYPTO_HIT",), calibrated=False),
)


def threshold_defs() -> list[dict]:
    """给接口/页面用的定义列表。"""
    return [
        {
            "key": d.key,
            "label": d.label,
            "group": d.group,
            "kind": d.kind,
            "unit": d.unit,
            "default": d.default,
            "minimum": d.minimum,
            "maximum": d.maximum,
            "desc": d.desc,
            "impacts": list(d.impacts),
            "calibrated": d.calibrated,
        }
        for d in THRESHOLD_DEFS
    ]


def validate_values(values: dict) -> dict:
    """按定义表校验一组参数：范围、类型、未知键。返回规范化后的配置字典。"""
    known = {d.key: d for d in THRESHOLD_DEFS}
    unknown = set(values) - set(known) - {"version"}
    if unknown:
        raise ValueError(f"未知参数：{', '.join(sorted(unknown))}")
    cleaned: dict = {}
    for key, raw in values.items():
        if key == "version":
            continue
        definition = known[key]
        if raw is None or raw == "":
            if definition.kind != "ratio" or definition.key != "counterparty_hhi":
                raise ValueError(f"{definition.label} 不能为空")
            cleaned[key] = None
            continue
        if definition.kind in ("int", "int_optional"):
            try:
                number = int(Decimal(str(raw)))
            except Exception as exc:
                raise ValueError(f"{definition.label} 必须是整数") from exc
        else:
            try:
                number = Decimal(str(raw))
            except Exception as exc:
                raise ValueError(f"{definition.label} 必须是数字") from exc
        if definition.minimum is not None and number < Decimal(str(definition.minimum)):
            raise ValueError(f"{definition.label} 不能小于 {definition.minimum}")
        if definition.maximum is not None and number > Decimal(str(definition.maximum)):
            raise ValueError(f"{definition.label} 不能大于 {definition.maximum}")
        cleaned[key] = number if definition.kind in ("int", "int_optional") else str(number)
    missing = set(known) - set(cleaned) - {"counterparty_hhi"}
    if missing:
        raise ValueError(f"缺少参数：{', '.join(sorted(missing))}")
    return cleaned
