"""指标口径专用算子：把「日历月 / 日终余额 / 分组二次聚合」这三类补齐。

为什么放在 metrics 而不是 features：这些算子的语义是**指标口径**的一部分
（覆盖自然月怎么算、日终余额怎么结转、HHI 用不用绝对值），换掉任何一个都会让指标变数。
放在指标能力里，口径和指标绑在一起，改的时候不会漏。

算子仍然注册进全局算子库，所以表达式里照常可以写、可以组合。
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

from ..features.operators import Frame, OperatorError, Series, operator, _to_decimal
from ..features.operators import NUMERIC, RATIO, YUAN

DAY = "天"
PIECE = "笔"


def _rows(x) -> list:
    if isinstance(x, Frame):
        return list(x.rows)
    if isinstance(x, (list, tuple)) and (not x or hasattr(x[0], "txn_date")):
        return list(x)
    raise OperatorError(f"需要数据帧，收到 {type(x).__name__}")


def _date(value) -> date | None:
    text = (value or "").strip()
    if len(text) < 10:
        return None
    try:
        return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except (ValueError, TypeError):
        return None


def _exact_months(start: date, end: date) -> float:
    """按自然月比例累加：整月计 1，首末不完整按当月天数折算（与旧口径逐位一致）。"""
    total = 0.0
    current = start
    while current <= end:
        days_in_month = calendar.monthrange(current.year, current.month)[1]
        segment_end = min(end, date(current.year, current.month, days_in_month))
        total += ((segment_end - current).days + 1) / days_in_month
        current = segment_end + timedelta(days=1)
    return round(total, 4)


def _months_between(start: date, end: date) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        out.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def _period(rows) -> tuple[date, date] | None:
    dates = [d for d in (_date(row.txn_date) for row in rows) if d is not None]
    return (min(dates), max(dates)) if dates else None


@operator("coverage_months", family=NUMERIC, kind="agg", unit="月", compat=False,
          detail="覆盖的自然月数（整月计 1，首末不完整按当月天数折算）；不足 min_months 时取 min_months。",
          params=[{"name": "min_months", "type": "int", "default": 1,
                   "detail": "下限。旧口径把不足一个月按一个月计（4 天流水不会把月均收入放大 7 倍）"}])
def op_coverage_months(x, *, min_months=1, notes=None):
    rows = _rows(x)
    period = _period(rows)
    if period is None:
        return None
    months = Decimal(str(_exact_months(*period)))
    floor = Decimal(str(min_months))
    return months if months >= floor else floor


@operator("month_count", family=NUMERIC, kind="agg", unit="月", compat=False,
          detail="覆盖期间跨了几个自然月（含空月）。与 coverage_months 不同：后者按天折算。")
def op_month_count(x, *, notes=None):
    period = _period(_rows(x))
    if period is None:
        return None
    return Decimal(len(_months_between(*period)))


@operator("slope", family=NUMERIC, kind="agg", unit=RATIO, compat=False,
          detail="对序列按序号做最小二乘回归，返回斜率；少于 2 个点返回 None。")
def op_slope(x, *, notes=None):
    values = list(x.values) if isinstance(x, Series) else None
    if values is None:
        raise OperatorError("slope 需要序列（例如 monthly_values / month_end_balances）")
    numbers = [v for v in (_to_decimal(v) for v in values) if v is not None]
    if len(numbers) < 2:
        return None
    xs = [Decimal(index) for index in range(len(numbers))]
    x_mean = sum(xs, Decimal(0)) / Decimal(len(xs))
    y_mean = sum(numbers, Decimal(0)) / Decimal(len(numbers))
    denominator = sum(((x - x_mean) ** 2 for x in xs), Decimal(0))
    if denominator == 0:
        return None
    numerator = sum(((x - x_mean) * (y - y_mean) for x, y in zip(xs, numbers)), Decimal(0))
    return numerator / denominator


@operator("month_end_balances", family=NUMERIC, kind="agg", unit=YUAN, compat=False,
          detail="覆盖月内各月最后一天的日终余额（末月按账期末日截断）。")
def op_month_end_balances(x, *, notes=None):
    rows = _rows(x)
    series = op_daily_balances(x)
    if series is None:
        if notes is not None and rows:
            notes.append("缺列：balance（或交易日期无法解析）")
        return Series(name="month_end_balance", values=[], frame=None)
    period = _period(rows)
    if period is None:
        return Series(name="month_end_balance", values=[], frame=None)
    start, end = period
    days = [start + timedelta(days=index) for index in range((end - start).days + 1)]
    by_day = dict(zip(days, series.values))
    out: list[Decimal] = []
    for year, month in _months_between(start, end):
        last_day = date(year, month, calendar.monthrange(year, month)[1])
        if last_day > end:
            last_day = end
        if last_day in by_day:
            out.append(by_day[last_day])
    return Series(name="month_end_balance", values=out, frame=None)


@operator("monthly_values", family=NUMERIC, kind="agg", unit=YUAN, compat=False,
          detail="覆盖月内逐月的值（空月计 0）；agg=sum 求和、agg=count 计数。",
          params=[{"name": "column", "type": "str", "default": "amount"},
                  {"name": "where", "type": "bool序列", "default": None},
                  {"name": "agg", "type": "str", "default": "sum", "detail": "sum / count"}])
def op_monthly_values(x, *, column="amount", where=None, agg="sum", notes=None):
    rows = _rows(x)
    period = _period(rows)
    if period is None:
        return None
    start, end = period
    buckets: dict[tuple[int, int], Decimal] = {
        key: Decimal(0) for key in _months_between(start, end)
    }
    if where is None:
        mask = [True] * len(rows)
    else:
        values = list(where.values) if isinstance(where, Series) else list(where)
        if len(values) != len(rows):
            raise OperatorError(f"where 长度 {len(values)} 与数据 {len(rows)} 不一致")
        mask = [bool(v) for v in values]
    for row, keep in zip(rows, mask):
        if not keep:
            continue
        day = _date(row.txn_date)
        if day is None:
            continue
        key = (day.year, day.month)
        if key not in buckets:
            continue
        if agg == "count":
            buckets[key] += 1
            continue
        amount = _to_decimal(row.amount)
        if amount is None:
            continue
        buckets[key] += amount if row.direction != "out" else -amount
    return Series(name=f"monthly_{agg}", values=[buckets[key] for key in sorted(buckets)], frame=None)


@operator("daily_balances", family=NUMERIC, kind="agg", unit=YUAN, compat=False,
          detail="日终余额序列：按日取当天最后一笔余额，无交易日结转；期初未知时首笔之前不计。")
def op_daily_balances(x, *, notes=None):
    rows = _rows(x)
    period = _period(rows)
    if period is None:
        return None
    by_day: dict[date, Decimal] = {}
    for row in rows:
        day = _date(row.txn_date)
        balance = _to_decimal(row.balance)
        if day is None or balance is None:
            continue
        by_day[day] = balance
    if not by_day:
        return None
    start, end = min(by_day), max(by_day)
    series: list[Decimal] = []
    current = None
    day = start
    while day <= end:
        if day in by_day:
            current = by_day[day]
        if current is not None:
            series.append(current)
        day += timedelta(days=1)
    return Series(name="daily_balance", values=series, frame=None)


@operator("pstdev", family=NUMERIC, kind="agg", unit=YUAN, compat=False,
          detail="总体标准差（除以 n）。注意与 features 里的 std 不同：那个是样本标准差。")
def op_pstdev(x, *, notes=None):
    values = list(x.values) if isinstance(x, Series) else [
        _to_decimal(row.balance) for row in _rows(x) if _to_decimal(row.balance) is not None
    ]
    numbers = [v for v in (_to_decimal(v) for v in values) if v is not None]
    if len(numbers) < 1:
        return None
    mean = sum(numbers, Decimal(0)) / Decimal(len(numbers))
    variance = sum(((n - mean) ** 2 for n in numbers), Decimal(0)) / Decimal(len(numbers))
    return variance.sqrt()


@operator("overdraft_days", family=NUMERIC, kind="agg", unit=DAY, compat=False,
          detail="日终余额为负的天数。")
def op_overdraft_days(x, *, notes=None):
    series = op_daily_balances(x)
    if series is None:
        return None
    return Decimal(sum(1 for value in series.values if value < 0))


@operator("idle_months", family=NUMERIC, kind="agg", unit="月", compat=False,
          detail="整月无交易的月数（覆盖月内）。")
def op_idle_months(x, *, notes=None):
    series = op_monthly_values(x, agg="count")
    if series is None:
        return None
    return Decimal(sum(1 for value in series.values if value == 0))


def _counterparty_totals(rows):
    totals: dict[str, Decimal] = {}
    for row in rows:
        amount = _to_decimal(row.amount)
        name = (row.counterparty_name or "").strip()
        if amount is None or not name:
            continue
        totals[name] = totals.get(name, Decimal(0)) + amount
    return totals


@operator("share_square_sum", family=NUMERIC, kind="agg", unit=RATIO, compat=False,
          detail="按对手方汇总金额后求占比平方和（HHI）。",
          params=[{"name": "by", "type": "str", "default": "counterparty_name"}])
def op_share_square_sum(x, *, by="counterparty_name", notes=None):
    totals = _counterparty_totals(_rows(x))
    total = sum(totals.values(), Decimal(0))
    if total <= 0:
        return None
    return sum(((value / total) ** 2 for value in totals.values()), Decimal(0))


@operator("top_share", family=NUMERIC, kind="agg", unit=RATIO, compat=False,
          detail="金额前 k 大对手方合计 ÷ 对手方总额。",
          params=[{"name": "k", "type": "int", "default": 3}])
def op_top_share(x, *, k=3, notes=None):
    totals = _counterparty_totals(_rows(x))
    total = sum(totals.values(), Decimal(0))
    if total <= 0:
        return None
    ranked = sorted(totals.values(), reverse=True)[: int(k)]
    return sum(ranked, Decimal(0)) / total
