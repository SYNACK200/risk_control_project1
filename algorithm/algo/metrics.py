from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, Field

from ..ocr.models import Transaction
from .exclusions import ExclusionResult, analyze_exclusions, normalize_name
from .hits import HitResult

METRIC_SET_VERSION = 2  # v2：月均/月供按实际覆盖的自然月折算（原按出现月份数）
SAME_DAY_TOLERANCE = Decimal("0.2")

_SALARY = ("工资", "代发")
_LOAN = ("放款", "贷款发放", "借款", "消费金融", "小额贷款", "网贷")
_LOAN_COUNTERPARTY = (
    "消费金融",
    "小额贷款",
    "借呗",
    "花呗",
    "网商银行",
    "微粒贷",
    "招联",
    "中邮消费",
    "马上消费",
    "捷信",
)
_REPAY = ("还款", "分期", "贷款")
_SMALL_LOAN = ("小贷", "借呗", "花呗", "消费金融", "网贷", "备用金", "分期")
_CASH_OUT = ("取现", "ATM", "现金支取", "现金提取")
_CASH_IN = ("现存", "存现", "现金存入", "现金存款")
_THIRD_PARTY = ("支付宝", "微信", "财付通", "银联", "云闪付", "京东支付", "美团支付")
_CRYPTO = ("虚拟币", "比特币", "以太坊", "USDT", "BTC", "ETH", "火币", "币安", "欧易", "数字货币")

METRIC_DEFS: tuple[tuple[str, str, str], ...] = (
    ("A01", "期间收入合计", "元"),
    ("A02", "月均收入", "元"),
    ("A03", "月收入中位数", "元"),
    ("A04", "收入稳定性", "无量纲"),
    ("A05", "工资占比", "百分比"),
    ("A06", "工资规律月数", "百分比"),
    ("A07", "收入趋势斜率", "元/月"),
    ("A08", "剔除额占比", "百分比"),
    ("B01", "月还款合计", "元/月"),
    ("B02", "债务收入比 DTI", "百分比"),
    ("B03", "新增贷款笔数", "笔"),
    ("B04", "网贷平台数", "个"),
    ("B05", "小贷还款笔数", "笔"),
    ("B06", "信用卡还款额", "元"),
    ("B07", "透支天数", "天"),
    ("B08", "负余额笔数占比", "百分比"),
    ("C01", "净流入", "元"),
    ("C02", "流入流出比", "倍"),
    ("C03", "日均余额", "元"),
    ("C04", "余额波动率", "无量纲"),
    ("C05", "期末余额趋势", "元/月"),
    ("C06", "近三十天最低余额", "元"),
    ("C07", "现金提取占比", "百分比"),
    ("C08", "当日进出占比", "百分比"),
    ("D01", "月度笔数波动", "无量纲"),
    ("D02", "夜间交易占比", "百分比"),
    ("D03", "整数金额占比", "百分比"),
    ("D04", "大额笔数", "笔"),
    ("D05", "单笔最大占比", "百分比"),
    ("D06", "休眠月数", "月"),
    ("D07", "工资到账日波动", "天"),
    ("D08", "期末冲量", "百分比"),
    ("E01", "对手方集中度 HHI", "无量纲"),
    ("E02", "前三大占比", "百分比"),
    ("E03", "关联方占比", "百分比"),
    ("E04", "小贷命中率", "百分比"),
    ("E05", "涉赌命中率", "百分比"),
    ("E06", "虚拟币命中率", "百分比"),
    ("E07", "现金存入占比", "百分比"),
    ("E08", "第三方支付占比", "百分比"),
)

CALIBER_VERSION = 1


class MetricValue(BaseModel):
    code: str
    name: str
    value: Decimal | None = None
    unit: str
    note: str
    caliber_version: int = CALIBER_VERSION


class MonthlyFlow(BaseModel):
    month: str
    income: Decimal
    expense: Decimal


class MetricSet(BaseModel):
    metric_set_version: int = METRIC_SET_VERSION
    period_start: date | None = None
    period_end: date | None = None
    coverage_months: int | None = None
    coverage_start: date | None = None
    coverage_end: date | None = None
    coverage_days: int | None = None
    coverage_months_exact: float | None = None
    metrics: list[MetricValue] = Field(default_factory=list)
    trend: list[MonthlyFlow] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    exclusions: ExclusionResult | None = None

    def by_code(self, code: str) -> MetricValue:
        for metric in self.metrics:
            if metric.code == code:
                return metric
        raise KeyError(code)


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _ratio(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))


def _pstdev(values: list[Decimal]) -> Decimal:
    mean = _mean(values)
    variance = sum(((value - mean) ** 2 for value in values), Decimal("0")) / Decimal(
        len(values)
    )
    return variance.sqrt()


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _slope(values: list[Decimal]) -> Decimal | None:
    if len(values) < 2:
        return None
    xs = [Decimal(index) for index in range(len(values))]
    x_mean, y_mean = _mean(xs), _mean(values)
    denominator = sum(((x - x_mean) ** 2 for x in xs), Decimal("0"))
    if denominator == 0:
        return None
    numerator = sum(
        ((x - x_mean) * (y - y_mean) for x, y in zip(xs, values)), Decimal("0")
    )
    return numerator / denominator


def _has(text: str | None, needles: tuple[str, ...]) -> bool:
    if not text:
        return False
    upper = text.upper()
    return any(needle.upper() in upper for needle in needles)


def _parse_date(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _month_key(value: date) -> tuple[int, int]:
    return value.year, value.month


def _exact_months(start: date, end: date) -> float:
    """按自然月比例累加：整月计 1，首末不完整按当月天数折算。"""
    import calendar
    from datetime import timedelta

    total = 0.0
    cur = start
    while cur <= end:
        days_in_month = calendar.monthrange(cur.year, cur.month)[1]
        seg_end = min(end, date(cur.year, cur.month, days_in_month))
        total += ((seg_end - cur).days + 1) / days_in_month
        cur = seg_end + timedelta(days=1)
    return round(total, 4)


def _months(start: date, end: date) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        result.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def _months_before(value: date, months: int) -> date:
    year, month = value.year, value.month - months
    while month <= 0:
        year, month = year - 1, month + 12
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _hour(text: str | None) -> int | None:
    if not text:
        return None
    part = text.strip().split(" ")[-1].split("T")[-1]
    token = part.split(":")[0]
    try:
        hour = int(token)
    except ValueError:
        return None
    return hour if 0 <= hour <= 23 else None


def _day_balances(
    transactions: list[Transaction],
    dates: list[date | None],
    start: date,
    end: date,
    opening: Decimal | None,
) -> dict[date, Decimal]:
    by_day: dict[date, Decimal] = {}
    for txn, day in zip(transactions, dates):
        if day is not None and txn.balance is not None:
            by_day[day] = txn.balance
    series: dict[date, Decimal] = {}
    current = opening
    day = start
    while day <= end:
        if day in by_day:
            current = by_day[day]
        if current is not None:
            series[day] = current
        day += timedelta(days=1)
    return series


def _counterparty_totals(
    transactions: list[Transaction],
) -> tuple[dict[str, Decimal], Decimal, int]:
    totals: dict[str, Decimal] = {}
    missing = 0
    for txn in transactions:
        if txn.amount is None:
            continue
        name = (txn.counterparty_name or "").strip()
        if not name:
            missing += 1
            continue
        totals[name] = totals.get(name, Decimal("0")) + txn.amount
    return totals, sum(totals.values(), Decimal("0")), missing


def compute_metrics(
    transactions: list[Transaction],
    *,
    exclusions: ExclusionResult | None = None,
    holder_name: str | None = None,
    opening_balance: Decimal | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    trade_times: list[str | None] | None = None,
    labels: list[set[str]] | None = None,
    hits: HitResult | None = None,
    related_names: set[str] | None = None,
    large_amount_threshold: Decimal | None = None,
) -> MetricSet:
    """40 项指标；缺输入返回 null 并写明原因，不填 0、不估计。"""
    if exclusions is None:
        exclusions = analyze_exclusions(transactions, holder_name=holder_name)
    if labels is None and hits is not None:
        labels = hits.labels
    if trade_times is None:
        trade_times = [txn.trade_time for txn in transactions]
    elif len(trade_times) != len(transactions):
        raise ValueError("trade_times 长度必须与交易笔数一致")
    if labels is not None and len(labels) != len(transactions):
        raise ValueError("labels 长度必须与交易笔数一致")

    dates = [_parse_date(txn.txn_date) for txn in transactions]
    known = [day for day in dates if day is not None]
    start = period_start or (min(known) if known else None)
    end = period_end or (max(known) if known else None)
    months = _months(start, end) if start and end else []
    coverage = len(months) if months else None
    coverage_days = (end - start).days + 1 if start and end else None
    coverage_exact = _exact_months(start, end) if start and end else None
    coverage_clamped = False
    if coverage_exact is not None and coverage_exact < 1:
        # 业务口径：覆盖不足 1 个整月时按月均折算会失真，统一按 1 个月计并写明假设
        coverage_exact = 1.0
        coverage_clamped = True
    missing_dates = len(known) < len(transactions)
    missing_direction = sum(
        1 for txn in transactions if txn.direction not in ("in", "out") and txn.amount is not None
    )
    inflow_count = sum(1 for txn in transactions if txn.direction == "in" and txn.amount is not None)

    kept = set(exclusions.kept_indices)
    inflow_raw = [txn.amount for txn in transactions if txn.direction == "in" and txn.amount is not None]
    outflow_raw = [txn.amount for txn in transactions if txn.direction == "out" and txn.amount is not None]
    kept_inflow = [
        txn.amount
        for index, txn in enumerate(transactions)
        if index in kept and txn.direction == "in" and txn.amount is not None
    ]
    total_in = sum(inflow_raw, Decimal("0"))
    total_out = sum(outflow_raw, Decimal("0"))
    income = sum(kept_inflow, Decimal("0"))
    amounts = [txn.amount for txn in transactions if txn.amount is not None]

    monthly_income = {key: Decimal("0") for key in months}
    monthly_expense = {key: Decimal("0") for key in months}
    monthly_count = {key: 0 for key in months}
    monthly_salary = {key: 0 for key in months}
    salary_days: list[int] = []
    kept_inflow_by_day: dict[date, Decimal] = {}
    for index, (txn, day) in enumerate(zip(transactions, dates)):
        if day is None or not months:
            continue
        key = _month_key(day)
        if key not in monthly_income:
            continue
        monthly_count[key] += 1
        if txn.direction == "out" and txn.amount is not None:
            monthly_expense[key] += txn.amount
        if index in kept and txn.direction == "in" and txn.amount is not None:
            monthly_income[key] += txn.amount
            kept_inflow_by_day[day] = kept_inflow_by_day.get(day, Decimal("0")) + txn.amount
            if _has(txn.summary, _SALARY):
                monthly_salary[key] += 1
                salary_days.append(day.day)

    values: dict[str, tuple[Decimal | None, str]] = {}

    def put(code: str, value: Decimal | None, note: str) -> None:
        values[code] = (value, note)

    # A 组
    income_unknown = bool(transactions) and inflow_count == 0 and missing_direction > 0
    if not transactions:
        put("A01", None, "无交易明细")
    elif income_unknown:
        put("A01", None, f"未识别到入账方向（{missing_direction} 笔方向缺失），收入类指标不可算")
    else:
        put("A01", _money(income), "剔除六类后的入账合计")
    if coverage_exact and not income_unknown:
        put("A02", _money(income / Decimal(str(coverage_exact))),
            f"A01 ÷ 实际覆盖 {coverage_exact} 个整月（{coverage_days} 天，首末月按当月天数折算）")
    elif income_unknown:
        put("A02", None, "A01 不可算（入账方向缺失）")
    else:
        put("A02", None, "缺交易日期，无法确定覆盖期间")
    if months:
        monthly_values = [monthly_income[key] for key in months]
        put("A03", _money(_median(monthly_values)), "覆盖月内各月入账中位数（空月计 0）")
        if len(monthly_values) >= 2 and _mean(monthly_values) != 0:
            put(
                "A04",
                _ratio(_pstdev(monthly_values) / abs(_mean(monthly_values))),
                "各月入账标准差 ÷ 均值绝对值（总体标准差）",
            )
        else:
            put("A04", None, "覆盖月不足两个月或月均入账为 0")
        slope = _slope(monthly_values)
        put(
            "A07",
            _money(slope) if slope is not None else None,
            "月度入账对月份序号的一元线性回归斜率"
            if slope is not None
            else "覆盖月不足两个月，无法回归",
        )
    else:
        for code, note in (
            ("A03", "缺交易日期，无法按月聚合"),
            ("A04", "缺交易日期，无法按月聚合"),
            ("A07", "缺交易日期，无法按月聚合"),
        ):
            put(code, None, note)
    salary_amount = sum(
        (
            txn.amount
            for index, txn in enumerate(transactions)
            if index in kept
            and txn.direction == "in"
            and txn.amount is not None
            and _has(txn.summary, _SALARY)
        ),
        Decimal("0"),
    )
    if income and coverage:
        put("A05", _ratio(salary_amount / income), "工资/代发入账 ÷ A01")
        put(
            "A06",
            _ratio(Decimal(_longest_run(monthly_salary)) / Decimal(coverage)),
            "最长连续有工资入账月数 ÷ 覆盖月数",
        )
    else:
        reason = "A01 为 0" if coverage else "缺交易日期，无法确定覆盖月数"
        put("A05", None, reason)
        put("A06", None, reason)
    if exclusions.inflow_before:
        put(
            "A08",
            _ratio((exclusions.inflow_before - exclusions.inflow_after) / exclusions.inflow_before),
            "被剔除入账 ÷ 剔除前入账",
        )
    else:
        put("A08", None, "剔除前入账为 0")

    # B 组
    repay_total = sum(
        (
            txn.amount
            for txn in transactions
            if txn.direction == "out" and txn.amount is not None and _has(txn.summary, _REPAY)
        ),
        Decimal("0"),
    )
    if coverage_exact:
        b01 = repay_total / Decimal(str(coverage_exact))
        put("B01", _money(b01), f"还款/分期/贷款出账合计 ÷ 实际覆盖 {coverage_exact} 个整月")
        if income:
            put("B02", _ratio(b01 / (income / Decimal(str(coverage_exact)))),
                "B01 ÷ A02" + ("（未识别到还款类出账，不代表无负债）" if repay_total == 0 else ""))
        else:
            put("B02", None, "A02 为 0 或不可算")
    else:
        put("B01", None, "缺交易日期，无法确定覆盖月数")
        put("B02", None, "缺交易日期，无法确定覆盖月数")

    if end is not None:
        window_start = _months_before(end, 6)
        recent_loans = [
            txn
            for txn, day in zip(transactions, dates)
            if day is not None
            and window_start <= day <= end
            and txn.direction == "in"
            and (_has(txn.summary, _LOAN) or _has(txn.counterparty_name, _LOAN_COUNTERPARTY))
        ]
        put("B03", Decimal(len(recent_loans)), "期末前六个月放款类入账笔数")
        names = {txn.counterparty_name.strip() for txn in recent_loans if (txn.counterparty_name or "").strip()}
        if recent_loans and not names:
            put("B04", None, "放款类入账均缺对手方名称")
        else:
            missing = sum(1 for txn in recent_loans if not (txn.counterparty_name or "").strip())
            note = "放款类入账的不同对手方去重数"
            put("B04", Decimal(len(names)), note + (f"；{missing} 笔无对手方未计入" if missing else ""))
    else:
        put("B03", None, "缺交易日期，无法确定近六个月")
        put("B04", None, "缺交易日期，无法确定近六个月")

    if transactions:
        put(
            "B05",
            Decimal(
                sum(
                    1
                    for txn in transactions
                    if txn.direction == "out" and _has(txn.summary, _SMALL_LOAN)
                )
            ),
            "小贷/借呗/花呗等出账笔数",
        )
    else:
        put("B05", None, "无交易明细")
    if transactions:
        card_total = sum(
            (
                txn.amount
                for txn in transactions
                if txn.direction == "out"
                and txn.amount is not None
                and (_has(txn.summary, ("信用卡",)) or _has(txn.counterparty_name, ("信用卡",)))
            ),
            Decimal("0"),
        )
        put("B06", _money(card_total), "信用卡类出账合计")
    else:
        put("B06", None, "无交易明细")

    balances = _day_balances(transactions, dates, start, end, opening_balance) if start and end else {}
    if balances:
        negative_days = sum(1 for value in balances.values() if value < 0)
        put("B07", Decimal(negative_days), "日终余额为负的天数")
    else:
        put("B07", None, "缺交易日期或余额，无法还原日终余额")
    balance_rows = [txn.balance for txn in transactions if txn.balance is not None]
    if balance_rows:
        negative_rows = sum(1 for value in balance_rows if value < 0)
        missing_balance = len(transactions) - len(balance_rows)
        note = "余额为负的笔数 ÷ 总笔数"
        put(
            "B08",
            _ratio(Decimal(negative_rows) / Decimal(len(transactions))),
            note + (f"；{missing_balance} 笔无余额未计入分子" if missing_balance else ""),
        )
    else:
        put("B08", None, "无余额字段")

    # C 组
    if income or total_out:
        put("C01", _money(income - total_out), "A01 − 全部出账（出账未按剔除口径抵扣）")
    else:
        put("C01", None, "无收支数据")
    if total_out:
        put("C02", _ratio(total_in / total_out), "全部入账 ÷ 全部出账")
    else:
        put("C02", None, "出账为 0")

    if balances:
        series = list(balances.values())
        average = _mean(series)
        missing_head = opening_balance is None and min(balances) > start
        put(
            "C03",
            _money(average),
            "日终余额按日算术平均（无交易日结转）"
            + ("；期初余额未知，首笔前日期未计" if missing_head else ""),
        )
        if len(series) >= 2 and average > 0:
            put("C04", _ratio(_pstdev(series) / average), "日终余额标准差 ÷ 均值")
        else:
            put("C04", None, "日终余额不足两天或均值不为正")
        month_ends: list[Decimal] = []
        for year, month in months:
            last_day = date(year, month, calendar.monthrange(year, month)[1])
            if last_day > end:
                last_day = end
            if last_day in balances:
                month_ends.append(balances[last_day])
        slope = _slope(month_ends)
        put(
            "C05",
            _money(slope) if slope is not None else None,
            "各月月末余额回归斜率" if slope is not None else "有效月末余额不足两个月",
        )
        window_start = max(start, end - timedelta(days=29))
        window = [value for day, value in balances.items() if window_start <= day <= end]
        put(
            "C06",
            _money(min(window)) if window else None,
            "期末前 30 天日终余额最小值" if window else "近三十天无可用余额",
        )
    else:
        for code in ("C03", "C04", "C05", "C06"):
            put(code, None, "缺交易日期或余额，无法还原日终余额")

    cash_out = sum(
        (
            txn.amount
            for txn in transactions
            if txn.direction == "out" and txn.amount is not None and _has(txn.summary, _CASH_OUT)
        ),
        Decimal("0"),
    )
    put(
        "C07",
        _ratio(cash_out / total_out) if total_out else None,
        "取现/ATM 出账 ÷ 全部出账" if total_out else "出账为 0",
    )

    day_in: dict[date, Decimal] = {}
    day_out: dict[date, Decimal] = {}
    for txn, day in zip(transactions, dates):
        if day is None or txn.amount is None:
            continue
        if txn.direction == "in":
            day_in[day] = day_in.get(day, Decimal("0")) + txn.amount
        elif txn.direction == "out":
            day_out[day] = day_out.get(day, Decimal("0")) + txn.amount
    if transactions:
        close_days = {
            day
            for day in set(day_in) & set(day_out)
            if max(day_in[day], day_out[day]) > 0
            and min(day_in[day], day_out[day]) / max(day_in[day], day_out[day])
            >= Decimal("1") - SAME_DAY_TOLERANCE
        }
        counted = sum(1 for day in dates if day in close_days)
        put(
            "C08",
            _ratio(Decimal(counted) / Decimal(len(transactions))),
            "同日进出金额相差 20% 以内的交易日笔数 ÷ 总笔数",
        )
    else:
        put("C08", None, "无交易明细")

    # D 组
    if months:
        counts = [Decimal(monthly_count[key]) for key in months]
        if len(counts) >= 2 and _mean(counts) != 0:
            put("D01", _ratio(_pstdev(counts) / _mean(counts)), "各月笔数标准差 ÷ 均值")
        else:
            put("D01", None, "覆盖月不足两个月或月均笔数为 0")
        put("D06", Decimal(sum(1 for key in months if monthly_count[key] == 0)), "整月无交易的月数")
    else:
        put("D01", None, "缺交易日期，无法按月聚合")
        put("D06", None, "缺交易日期，无法按月聚合")

    if trade_times and any(_hour(item) is not None for item in trade_times):
        timed = [(txn, _hour(time)) for txn, time in zip(transactions, trade_times)]
        timed = [(txn, hour) for txn, hour in timed if hour is not None]
        night = sum(1 for _, hour in timed if hour >= 22 or hour < 6)
        put("D02", _ratio(Decimal(night) / Decimal(len(timed))), "22 时至次日 6 时笔数 ÷ 有交易时间笔数")
    else:
        put("D02", None, "交易明细无 trade_time（原件未印时分秒），无法计算夜间占比")

    with_amount = [value for value in amounts if value is not None]
    if with_amount:
        integers = sum(1 for value in with_amount if value % Decimal("100") == 0)
        missing_amount = len(transactions) - len(with_amount)
        note = "整百金额笔数 ÷ 总笔数"
        put(
            "D03",
            _ratio(Decimal(integers) / Decimal(len(transactions))),
            note + (f"；{missing_amount} 笔无金额未计入分子" if missing_amount else ""),
        )
    else:
        put("D03", None, "无金额字段")

    if large_amount_threshold is None:
        put("D04", None, "缺本行分位阈值")
    else:
        put(
            "D04",
            Decimal(sum(1 for value in with_amount if value > large_amount_threshold)),
            "单笔超过本行分位阈值的笔数",
        )

    total_amount = sum(with_amount, Decimal("0"))
    put(
        "D05",
        _ratio(max(with_amount) / total_amount) if with_amount and total_amount else None,
        "最大单笔金额 ÷ 全部金额" if with_amount and total_amount else "无金额数据",
    )

    if len(salary_days) >= 2:
        days = [Decimal(day) for day in salary_days]
        put("D07", _ratio(_pstdev(days)), "工资入账日（几号）标准差")
    else:
        put("D07", None, "工资入账不足两笔")

    if months and income:
        impulse = Decimal("0")
        for year, month in months:
            last_day = date(year, month, calendar.monthrange(year, month)[1])
            window_end = min(last_day, end)
            window_start = window_end - timedelta(days=2)
            for day, value in kept_inflow_by_day.items():
                if window_start <= day <= window_end:
                    impulse += value
        put("D08", _ratio(impulse / income), "各月末三天入账 ÷ 剔除后入账合计")
    else:
        put("D08", None, "缺交易日期或剔除后入账为 0")

    # E 组
    totals, counterparty_total, missing_counterparty = _counterparty_totals(transactions)
    missing_note = f"；{missing_counterparty} 笔无对手方未计入" if missing_counterparty else ""
    if totals and counterparty_total:
        shares = [value / counterparty_total for value in totals.values()]
        put("E01", _ratio(sum((share * share for share in shares), Decimal("0"))), "各对手方金额占比平方和" + missing_note)
        top3 = sum(sorted(totals.values(), reverse=True)[:3], Decimal("0"))
        put("E02", _ratio(top3 / counterparty_total), "金额前三大对手方 ÷ 对手方总额" + missing_note)
    else:
        put("E01", None, "无对手方金额")
        put("E02", None, "无对手方金额")

    if related_names is None:
        put("E03", None, "缺关系数据")
    elif totals and counterparty_total:
        related = {normalize_name(name) for name in related_names}
        related_total = sum(
            (value for name, value in totals.items() if normalize_name(name) in related),
            Decimal("0"),
        )
        put("E03", _ratio(related_total / counterparty_total), "关联对手方金额 ÷ 对手方总额")
    else:
        put("E03", Decimal("0"), "提供了关系数据，但无对手方金额")

    for code, tag, label in (
        ("E04", "LOAN", "[LOAN]"),
        ("E05", "GAMBLING", "[GAMBLING]"),
    ):
        if labels is None:
            put(code, None, f"缺 {label} 标签（未传入规则命中）")
        elif not transactions:
            put(code, None, "无交易明细")
        else:
            hit = sum(1 for item in labels if tag in {name.upper() for name in item})
            put(code, _ratio(Decimal(hit) / Decimal(len(transactions))), f"{label} 标签笔数 ÷ 总笔数")

    if transactions:
        if labels is not None:
            crypto = sum(1 for item in labels if "CRYPTO" in {name.upper() for name in item})
            note = "[CRYPTO] 标签笔数 ÷ 总笔数"
        else:
            crypto = sum(1 for txn in transactions if _has(txn.summary, _CRYPTO))
            note = "内置词库命中笔数 ÷ 总笔数；未传入规则命中"
        put("E06", _ratio(Decimal(crypto) / Decimal(len(transactions))), note)
    else:
        put("E06", None, "无交易明细")

    cash_in = sum(
        (
            txn.amount
            for index, txn in enumerate(transactions)
            if index in kept
            and txn.direction == "in"
            and txn.amount is not None
            and _has(txn.summary, _CASH_IN)
        ),
        Decimal("0"),
    )
    put(
        "E07",
        _ratio(cash_in / income) if income else None,
        "存现类入账 ÷ A01" if income else "A01 为 0",
    )

    if total_amount:
        third = sum(
            (
                txn.amount
                for txn in transactions
                if txn.amount is not None
                and (_has(txn.summary, _THIRD_PARTY) or _has(txn.counterparty_name, _THIRD_PARTY))
            ),
            Decimal("0"),
        )
        put("E08", _ratio(third / total_amount), "第三方支付渠道金额 ÷ 全部金额")
    else:
        put("E08", None, "无金额数据")

    notes = list(exclusions.notes)
    if hits is not None:
        notes.append(f"标签来自规则库 v{hits.library_version}，仅作线索")
    if missing_dates:
        notes.append(f"{missing_dates} 笔缺交易日期，未计入按月指标")

    metrics = [
        MetricValue(
            code=code,
            name=name,
            value=values.get(code, (None, "未计算"))[0],
            unit=unit,
            note=values.get(code, (None, "未计算"))[1],
        )
        for code, name, unit in METRIC_DEFS
    ]

    trend = [
        MonthlyFlow(
            month=f"{year:04d}-{month:02d}",
            income=_money(monthly_income[(year, month)]),
            expense=_money(monthly_expense[(year, month)]),
        )
        for year, month in months
    ]

    if coverage_days:
        notes.append(
            f"月均类指标按实际覆盖 {coverage_exact} 个整月折算（{coverage_days} 天，首末月按比例）；"
            f"首末月不完整，与按整月计数会有差异"
        )
    if coverage_clamped:
        notes.append("明细覆盖不足 1 个整月，月均/月供按 1 个月折算，结果可能偏高，请以更长期间材料复核")
    return MetricSet(
        period_start=start,
        period_end=end,
        coverage_months=coverage,
        coverage_start=start,
        coverage_end=end,
        coverage_days=coverage_days,
        coverage_months_exact=coverage_exact,
        metrics=metrics,
        trend=trend,
        notes=notes,
        exclusions=exclusions,
    )


def _longest_run(monthly_salary: dict[tuple[int, int], int]) -> int:
    longest = current = 0
    for key in monthly_salary:
        if monthly_salary[key] > 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest
