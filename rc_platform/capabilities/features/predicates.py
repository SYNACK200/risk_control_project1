"""行级比较与分布比较：把「筛哪些行」从写死变成可组合的算子。

三类比较，对应三种人话：
- 时间维：晚上 18 点后、周末、某月 —— in_hours / is_weekend / in_months
- 数值维：金额在区间内、超过某值 —— amount_between / amount_gt
- 分布维：离均值几个标准差、分位、百分位 —— zscore / pct_rank / quantile

它们都返回「一列真假」（mask），直接喂给聚合算子的 where 参数：
    sum(amount, where=in_hours('18:00','23:59'))
    count(where=zscore() > 3)
    count(where=pct_rank() >= 0.99)

缺列时返回**全空**而不是全假：全假会被读成「0 笔」，把「没数据」说成「没发生」。
"""
from __future__ import annotations

from decimal import Decimal

from .operators import (
    NUMERIC, OperatorError, Series, _to_decimal, operator,
)
from .operators import column as column_of


def _rows_of(x) -> list:
    from .operators import Frame

    if isinstance(x, Frame):
        return list(x.rows)
    raise OperatorError(f"这个算子需要数据帧，收到 {type(x).__name__}")


def _blank(count: int) -> Series:
    """缺列时的 mask：全空，不是全假。"""
    return Series(name="mask", values=[None] * count, frame=None)


def _minutes(text: str) -> int | None:
    parts = (text or "").strip().split(":")
    if len(parts) < 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


@operator("in_hours", family=NUMERIC, kind="window", unit="笔", compat=False,
          detail="按交易时分筛选（含两端）；支持跨零点，如 '22:00'~'05:59'。缺交易时间返回全空。",
          params=[{"name": "start", "type": "str", "default": "18:00"},
                  {"name": "end", "type": "str", "default": "23:59"}])
def op_in_hours(x, start="18:00", end="23:59", *, notes=None):
    rows = _rows_of(x)
    low, high = _minutes(start), _minutes(end)
    if low is None or high is None:
        raise OperatorError(f"in_hours 的时间格式应为 HH:MM，收到 {start!r}/{end!r}")

    values: list[bool | None] = []
    for row in rows:
        text = (row.trade_time or "").strip()
        if not text:
            values.append(None)
            continue
        current = _minutes(text)
        if current is None:
            values.append(None)
            continue
        inside = low <= current <= high if low <= high else (current >= low or current <= high)
        values.append(inside)

    if values and all(value is None for value in values):
        if notes is not None:
            notes.append("缺列：trade_time（该列在全部交易上都没有值）")
        return _blank(len(rows))
    return Series(name="in_hours", values=values, frame=None)


@operator("is_weekend", family=NUMERIC, kind="window", unit="笔", compat=False,
          detail="周六/周日为真；缺交易日期返回全空。")
def op_is_weekend(x, *, notes=None):
    from datetime import date

    rows = _rows_of(x)
    values: list[bool | None] = []
    for row in rows:
        text = (row.txn_date or "")[:10]
        if len(text) < 10:
            values.append(None)
            continue
        try:
            day = date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
        except ValueError:
            values.append(None)
            continue
        values.append(day.weekday() >= 5)
    if values and all(value is None for value in values):
        if notes is not None:
            notes.append("缺列：txn_date")
        return _blank(len(rows))
    return Series(name="is_weekend", values=values, frame=None)


@operator("in_months", family=NUMERIC, kind="window", unit="笔", compat=False,
          detail="按自然月筛选（1–12，可多选），例如 in_months(1,2,3)。",
          params=[{"name": "months", "type": "int", "default": None}])
def op_in_months(x, *months, notes=None):
    rows = _rows_of(x)
    wanted = {int(item) for item in months if item is not None}
    if not wanted:
        raise OperatorError("in_months 至少要给一个月")
    values: list[bool | None] = []
    for row in rows:
        text = (row.txn_date or "")[:10]
        if len(text) < 10:
            values.append(None)
            continue
        try:
            values.append(int(text[5:7]) in wanted)
        except ValueError:
            values.append(None)
    if values and all(value is None for value in values):
        if notes is not None:
            notes.append("缺列：txn_date")
        return _blank(len(rows))
    return Series(name="in_months", values=values, frame=None)


def _numbers(rows) -> list[Decimal | None]:
    return [_to_decimal(getattr(row, "amount", None)) for row in rows]


@operator("zscore", family=NUMERIC, kind="series", unit="无量纲", compat=False,
          detail="逐笔标准分 (x-均值)/标准差；用样本标准差，标准差为 0 时返回 None。",
          params=[{"name": "column", "type": "str", "default": "amount"}])
def op_zscore(x, *, column="amount", notes=None):
    rows = _rows_of(x)
    values = [_to_decimal(v) for v in column_of(_frame_like(rows), column).values]
    numbers = [v for v in values if v is not None]
    if len(numbers) < 2:
        if notes is not None:
            notes.append("样本不足 2 笔，无法计算分布")
        return Series(name="zscore", values=[None] * len(values), frame=None)
    mean = sum(numbers, Decimal(0)) / Decimal(len(numbers))
    variance = sum(((n - mean) ** 2 for n in numbers), Decimal(0)) / Decimal(len(numbers) - 1)
    std = variance.sqrt()
    if std == 0:
        if notes is not None:
            notes.append("标准差为 0（数值无波动），标准分无意义")
        return Series(name="zscore", values=[None] * len(values), frame=None)
    return Series(name="zscore", values=[None if v is None else (v - mean) / std for v in values], frame=None)


@operator("pct_rank", family=NUMERIC, kind="series", unit="比例", compat=False,
          detail="逐笔百分位（0–1，升序排位/笔数）；相同值取同一排位。",
          params=[{"name": "column", "type": "str", "default": "amount"}])
def op_pct_rank(x, *, column="amount", notes=None):
    rows = _rows_of(x)
    values = [_to_decimal(v) for v in column_of(_frame_like(rows), column).values]
    numbers = sorted(v for v in values if v is not None)
    if len(numbers) < 2:
        return Series(name="pct_rank", values=[None] * len(values), frame=None)
    out: list[Decimal | None] = []
    for value in values:
        if value is None:
            out.append(None)
            continue
        rank = sum(1 for n in numbers if n <= value)
        out.append(Decimal(rank) / Decimal(len(numbers)))
    return Series(name="pct_rank", values=out, frame=None)


@operator("quantile", family=NUMERIC, kind="agg", unit="元", compat=False,
          detail="分位值（线性插值，与 numpy 默认一致）；q 在 0–1 之间。",
          params=[{"name": "column", "type": "str", "default": "amount"},
                  {"name": "q", "type": "number", "default": 0.9}])
def op_quantile(x, *, q=0.9, column="amount", notes=None):
    rows = _rows_of(x)
    numbers = sorted(v for v in (_to_decimal(getattr(row, column, None)) for row in rows) if v is not None)
    if not numbers:
        return None
    ratio = float(q)
    if not 0 <= ratio <= 1:
        raise OperatorError("quantile 的 q 必须在 0–1 之间")
    position = (len(numbers) - 1) * ratio
    low = int(position)
    high = min(low + 1, len(numbers) - 1)
    weight = Decimal(str(position - low))
    return numbers[low] + (numbers[high] - numbers[low]) * weight


def _frame_like(rows):
    from .operators import Frame

    return Frame(list(rows))


@operator("amount_between", family=NUMERIC, kind="window", unit="笔", compat=False,
          detail="金额区间筛选（含端点，按绝对值）；任一端留空表示不设限。",
          params=[{"name": "low", "type": "number", "default": None},
                  {"name": "high", "type": "number", "default": None}])
def op_amount_between(x, low=None, high=None, *, notes=None):
    rows = _rows_of(x)
    low_value = None if low is None else _to_decimal(low)
    high_value = None if high is None else _to_decimal(high)
    values: list[bool | None] = []
    for value in _numbers(rows):
        if value is None:
            values.append(None)
            continue
        amount = abs(value)
        ok = True
        if low_value is not None and amount < low_value:
            ok = False
        if high_value is not None and amount > high_value:
            ok = False
        values.append(ok)
    return Series(name="amount_between", values=values, frame=None)

@operator("mad", family=NUMERIC, kind="agg", unit="元", compat=False,
          detail="中位数绝对偏差 median(|x - median|)；对长尾比标准差稳，适合金额分布。",
          params=[{"name": "column", "type": "str", "default": "amount"}])
def op_mad(x, *, column="amount", notes=None):
    rows = _rows_of(x)
    numbers = sorted(v for v in (_to_decimal(getattr(row, column, None)) for row in rows) if v is not None)
    if not numbers:
        return None
    middle = len(numbers) // 2
    median = numbers[middle] if len(numbers) % 2 else (numbers[middle - 1] + numbers[middle]) / 2
    deviations = sorted(abs(n - median) for n in numbers)
    size = len(deviations)
    half = size // 2
    return deviations[half] if size % 2 else (deviations[half - 1] + deviations[half]) / 2


@operator("iqr", family=NUMERIC, kind="agg", unit="元", compat=False,
          detail="四分位距 Q3 - Q1（线性插值口径，与 quantile 一致）。",
          params=[{"name": "column", "type": "str", "default": "amount"}])
def op_iqr(x, *, column="amount", notes=None):
    q1 = op_quantile(x, q=0.25, column=column)
    q3 = op_quantile(x, q=0.75, column=column)
    if q1 is None or q3 is None:
        return None
    return q3 - q1


@operator("robust_zscore", family=NUMERIC, kind="series", unit="无量纲", compat=False,
          detail="稳健标准分 0.6745*(x-中位数)/MAD；长尾分布下比 zscore 更能挑出真正的离群点。",
          params=[{"name": "column", "type": "str", "default": "amount"}])
def op_robust_zscore(x, *, column="amount", notes=None):
    rows = _rows_of(x)
    values = [_to_decimal(getattr(row, column, None)) for row in rows]
    numbers = [v for v in values if v is not None]
    if len(numbers) < 2:
        if notes is not None:
            notes.append("样本不足 2 笔，无法计算分布")
        return Series(name="robust_zscore", values=[None] * len(values), frame=None)
    middle = len(numbers) // 2
    ordered = sorted(numbers)
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    deviations = sorted(abs(n - median) for n in ordered)
    half = len(deviations) // 2
    mad = deviations[half] if len(deviations) % 2 else (deviations[half - 1] + deviations[half]) / 2
    if mad == 0:
        if notes is not None:
            notes.append("MAD 为 0（多数值相同），稳健标准分无意义")
        return Series(name="robust_zscore", values=[None] * len(values), frame=None)
    scale = Decimal("0.6745") / mad
    return Series(name="robust_zscore",
                  values=[None if v is None else (v - median) * scale for v in values], frame=None)
