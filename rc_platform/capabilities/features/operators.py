"""算子库：把「数据帧」算成数值/布尔/表/序列的最小集合。

为什么必须只有这一份算子：步骤形态是封存版老数据的既有写法，表达式形态是新作者想写的写法。
两者若各写一遍取值逻辑，同一个口径迟早算出两个数；所以两种形态都只在 invoke() 这一层落下去。

值语义三条（缺一就会出现「悄悄填 0」的旧毛病）：
- 缺输入得 None，不得拿 0 顶替；只有「笔数/个数」这类空集本身就是真值的算子返回 0。
- 金额一律 Decimal：float 只在吸收外部传入时出现一次，内部绝不产生。
- 缺失（None）沿算式向上传播，and/or 按三值逻辑（假可定假、真可定真）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Callable, Iterable, Sequence

from ...core.contracts import TxnRow

NUMERIC = "numeric"
LOGIC = "logic"
GROUP = "group"
WINDOW = "window"
FILTER = "filter"

_FAMILY_LABELS = {
    NUMERIC: "数值",
    LOGIC: "逻辑与比较",
    GROUP: "分组聚合",
    WINDOW: "时间窗",
    FILTER: "过滤（封存版兼容）",
}

RATIO = "比例"
YUAN = "元"
PIECE = "笔"
TIMES = "个"
DAY = "天"


class OperatorError(ValueError):
    """算子的用法错误：未知算子、参数不对、把数值喂给数据帧算子。属于配置错误，必须报出来。"""


class UnknownOperator(OperatorError):
    """算子名不存在；消息里带最接近的候选，让人一眼看出是拼错还是没实现。"""


class UnknownColumn(OperatorError):
    """列名不存在；消息里列出可用列。"""


@dataclass(slots=True)
class Frame:
    """数据帧：一段流水 + 计算过程中发现的缺失列。

    missing 是给「缺输入写清缺什么」用的：算子取值时把整列为空的列记在这里，
    特征层就不必再猜一遍为什么算不出来。
    """
    rows: list[TxnRow] = field(default_factory=list)
    origin: str = ""                                  # 帧来源：报错与测试失败时能看出这帧是原始的还是过滤出来的
    missing: set[str] = field(default_factory=set)

    def __len__(self) -> int:
        return len(self.rows)


@dataclass(slots=True)
class Series:
    """一列值，与所属数据帧逐行对齐；frame 为 None 表示这一列是凭空造出来的（长度仍需一致）。"""
    name: str
    values: list[Any]
    frame: Frame | None = None

    def __len__(self) -> int:
        return len(self.values)


@dataclass(slots=True)
class OpSpec:
    key: str
    family: str
    kind: str                     # agg / scalar / group / filter / window / series
    unit: str
    detail: str
    fn: Callable[..., Any]
    params: tuple[dict, ...] = ()
    key_first: bool = False       # 第一个位置参数是「分组键名」而不是数据帧
    compat: bool = False          # 封存版 atoms 里已有的算子（老步骤数据靠它们直接跑）

    def describe(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "family": self.family,
            "family_label": _FAMILY_LABELS.get(self.family, self.family),
            "kind": self.kind,
            "unit": self.unit,
            "detail": self.detail,
            "params": [dict(p) for p in self.params],
            "compat": self.compat,
        }


_OPS: dict[str, OpSpec] = {}


def operator(
    key: str,
    *,
    family: str,
    kind: str,
    unit: str = "",
    detail: str = "",
    params: Sequence[dict] = (),
    key_first: bool = False,
    compat: bool = False,
):
    """登记一个算子；重名当场报错，避免后注册的静默覆盖前一个口径。"""
    def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
        if key in _OPS:
            raise OperatorError(f"算子重名：{key}")
        _OPS[key] = OpSpec(
            key=key, family=family, kind=kind, unit=unit, detail=detail, fn=fn,
            params=tuple(params), key_first=key_first, compat=compat,
        )
        return fn
    return wrap


def spec_of(key: str) -> OpSpec:
    spec = _OPS.get(key)
    if spec is not None:
        return spec
    import difflib

    near = difflib.get_close_matches(key, list(_OPS), n=3, cutoff=0.6)
    hint = f"；你是不是想写 {'、'.join(near)}" if near else ""
    raise UnknownOperator(f"未知算子 {key!r}（可用算子见 describe()）{hint}")


def operators() -> dict[str, OpSpec]:
    return dict(_OPS)


def families() -> dict[str, str]:
    return dict(_FAMILY_LABELS)


def describe(key: str | None = None) -> Any:
    """给作者与前端看的算子目录：不传 key 返回全部，传了就返回那一个。"""
    if key is not None:
        return spec_of(key).describe()
    return [spec.describe() for spec in _OPS.values()]


# ---------- 值语义 ----------

def _to_decimal(value: Any) -> Decimal | None:
    """把可当钱的值转成 Decimal。

    float 分支只用来吸收外部（JSON/旧库）传进来的浮点，转完立刻脱离 float，内部不再出现。
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("￥", "").replace("¥", "")
        if not text:
            return None
        try:
            return Decimal(text)
        except ArithmeticError:
            return None
    return None


def _truth(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "是"}
    if isinstance(value, (int, float, Decimal)):
        return value != 0
    return bool(value)


def _signed(row: TxnRow) -> Decimal | None:
    """有符号金额：入账为正、出账为负；方向缺失按正号（与封存版按正负记账的约定一致）。"""
    amount = _to_decimal(row.amount)
    if amount is None:
        return None
    return -amount if (row.direction or "").strip().lower() == "out" else amount


def _parse_date(text: str | None) -> date | None:
    if not text:
        return None
    found = re.search(r"(\d{4})\D?(\d{1,2})\D?(\d{1,2})", str(text))
    if not found:
        return None
    try:
        return date(int(found.group(1)), int(found.group(2)), int(found.group(3)))
    except ValueError:
        return None


def _row_hour(row: TxnRow) -> int | None:
    """小时：优先 trade_time，其次 txn_date 里带的时分（有些银行的日期列本身含时间）。"""
    for text in (row.trade_time, row.txn_date):
        if not text:
            continue
        found = re.search(r"(\d{1,2}):(\d{2})", str(text))
        if found:
            hour = int(found.group(1))
            if 0 <= hour <= 23:
                return hour
    return None


def _row_month(row: TxnRow) -> str | None:
    if not row.txn_date:
        return None
    found = re.search(r"(\d{4})\D(\d{1,2})", str(row.txn_date))
    if not found:
        return None
    return f"{int(found.group(1)):04d}-{int(found.group(2)):02d}"


def _row_dow(row: TxnRow) -> int | None:
    day = _parse_date(row.txn_date)
    return None if day is None else day.weekday()


_COLUMNS: dict[str, Callable[[TxnRow], Any]] = {
    "amount": lambda r: _to_decimal(r.amount),
    "balance": lambda r: _to_decimal(r.balance),
    "direction": lambda r: ((r.direction or "").strip().lower() or None),
    "counterparty_name": lambda r: (r.counterparty_name or None),
    "summary": lambda r: (r.summary or None),
    "txn_date": lambda r: (r.txn_date or None),
    "trade_time": lambda r: (r.trade_time or None),
    "reference_no": lambda r: (r.reference_no or None),
    "hour": _row_hour,
    "month": _row_month,
    "dow": _row_dow,
}

_COLUMN_ALIASES = {"date": "txn_date", "counterparty": "counterparty_name", "time": "trade_time"}

# 派生列整列为空时，要报出真正的缺失输入，而不是派生的那个名字
_MISSING_SOURCE = {"hour": "trade_time", "month": "txn_date", "dow": "txn_date"}


def column(frame: Frame, name: str) -> Series:
    """取一列。整列为空时记进 frame.missing，特征层的 reason 才有话可说。"""
    key = _COLUMN_ALIASES.get(name, name)
    getter = _COLUMNS.get(key)
    if getter is None:
        raise UnknownColumn(f"未知列 {name!r}；可用列：{'、'.join(_COLUMNS)}")
    values = [getter(row) for row in frame.rows]
    if values and all(v is None for v in values):
        frame.missing.add(_MISSING_SOURCE.get(key, key))
    return Series(key, values, frame)


def value_of(row: TxnRow, name: str) -> Any:
    key = _COLUMN_ALIASES.get(name, name)
    getter = _COLUMNS.get(key)
    if getter is None:
        raise UnknownColumn(f"未知列 {name!r}；可用列：{'、'.join(_COLUMNS)}")
    return getter(row)


def _as_frame(x: Any, op: str) -> Frame:
    if isinstance(x, Frame):
        return x
    raise OperatorError(
        f"算子 {op} 需要数据帧，收到 {type(x).__name__}；"
        "聚合/分组类算子必须放在步骤的最后，不能再被后续算子消费"
    )


def _frame_values(frame: Frame, column_name: str, signed: bool) -> list[Any]:
    if column_name == "amount":
        values: list[Any] = [(_signed(r) if signed else _to_decimal(r.amount)) for r in frame.rows]
    else:
        values = list(column(frame, column_name).values)
    if values and all(v is None for v in values):
        frame.missing.add(_MISSING_SOURCE.get(column_name, column_name))
    return values


def _collect(x: Any, *, column_name: str = "amount", signed: bool = True) -> tuple[list[Any], Frame | None]:
    """把算子输入统一成「值序列 + 所属数据帧」，序列与帧保留用于解释缺失。"""
    if isinstance(x, Series):
        values = list(x.values)
        if values and all(v is None for v in values) and x.frame is not None:
            x.frame.missing.add(x.name)
        return values, x.frame
    if isinstance(x, Frame):
        return _frame_values(x, column_name, signed), x
    if isinstance(x, dict):
        return [v for group in x.values() for v in (group if isinstance(group, list) else [group])], None
    if isinstance(x, (list, tuple)):
        if x and isinstance(x[0], TxnRow):
            rows = list(x)
            return [(_signed(r) if signed else _to_decimal(r.amount)) for r in rows], None
        return list(x), None
    raise OperatorError(
        f"需要数据帧、序列或分组表，收到 {type(x).__name__}；"
        "数值不能继续被聚合（聚合类算子应当只出现在最后一步）"
    )


def _mask(values: list[Any], where: Any) -> list[Any]:
    if where is None:
        return values
    mask = list(where.values) if isinstance(where, Series) else list(where)
    if len(mask) != len(values):
        raise OperatorError(f"where 条件长度 {len(mask)} 与数据长度 {len(values)} 不一致")
    return [v for v, keep in zip(values, mask) if _truth(keep) is True]


def _numbers(values: Iterable[Any]) -> list[Decimal]:
    return [n for n in (_to_decimal(v) for v in values) if n is not None]


def _note(notes: list[str] | None, text: str) -> None:
    if notes is not None and text not in notes:
        notes.append(text)


def _mean(nums: Sequence[Decimal]) -> Decimal | None:
    return None if not nums else sum(nums, Decimal(0)) / Decimal(len(nums))


def _std(nums: Sequence[Decimal]) -> Decimal | None:
    """样本标准差（n-1）：与封存版口径一致，n<2 无意义。"""
    if len(nums) < 2:
        return None
    mean = sum(nums, Decimal(0)) / Decimal(len(nums))
    var = sum(((n - mean) ** 2 for n in nums), Decimal(0)) / Decimal(len(nums) - 1)
    return var.sqrt()


# ---------- 数值族 ----------

@operator("sum", family=NUMERIC, kind="agg", unit=YUAN, compat=True,
          detail="求和。数据帧上按「入账正、出账负」求和（净额）；signed=false 时按金额绝对值求和。",
          params=[{"name": "column", "type": "str", "default": "amount", "detail": "取哪一列"},
                  {"name": "signed", "type": "bool", "default": True, "detail": "是否按收付方向带符号"},
                  {"name": "where", "type": "bool序列", "default": None, "detail": "逐行筛选条件"}])
def op_sum(x, *, column="amount", signed=True, where=None, notes=None):
    nums = _numbers(_mask(_collect(x, column_name=column, signed=signed)[0], where))
    if not nums:
        _note(notes, "没有可求和的金额")
        return None
    return sum(nums, Decimal(0))


@operator("count", family=NUMERIC, kind="agg", unit=PIECE, compat=True,
          detail="计数。数据帧上数笔数（空帧得 0 笔，是真的 0 笔）；序列上数非空值。",
          params=[{"name": "where", "type": "bool序列", "default": None, "detail": "逐行筛选条件"}])
def op_count(x=None, *, where=None, notes=None):
    if isinstance(x, Frame):
        if where is None:
            return len(x.rows)
        mask = list(where.values) if isinstance(where, Series) else list(where)
        if len(mask) != len(x.rows):
            raise OperatorError(f"where 条件长度 {len(mask)} 与笔数 {len(x.rows)} 不一致")
        flags = [_truth(flag) for flag in mask]
        matched = sum(1 for flag in flags if flag is True)
        # 一笔都没命中、但有些行根本无法判定时，0 是假的：宁可说不知道，也不谎报「0 笔」
        if matched == 0 and any(flag is None for flag in flags):
            _note(notes, "条件无法判定（相关列整列为空），不能据此报 0 笔")
            return None
        return matched
    if isinstance(x, dict):
        return len(x)
    if x is None:
        raise OperatorError("算子 count 需要数据帧、序列或分组表，收到 None")
    values = _mask(_collect(x)[0], where)
    return sum(1 for v in values if v is not None)


@operator("mean", family=NUMERIC, kind="agg", unit=YUAN, compat=True, detail="均值；空集得 None（不是 0）。",
          params=[{"name": "column", "type": "str", "default": "amount", "detail": "取哪一列"},
                  {"name": "signed", "type": "bool", "default": True, "detail": "是否带符号"},
                  {"name": "where", "type": "bool序列", "default": None, "detail": "逐行筛选条件"}])
def op_mean(x, *, column="amount", signed=True, where=None, notes=None):
    nums = _numbers(_mask(_collect(x, column_name=column, signed=signed)[0], where))
    if not nums:
        _note(notes, "没有可求均值的金额")
        return None
    return _mean(nums)


@operator("median", family=NUMERIC, kind="agg", unit=YUAN, compat=True, detail="中位数，比均值抗极端值。",
          params=[{"name": "column", "type": "str", "default": "amount", "detail": "取哪一列"},
                  {"name": "signed", "type": "bool", "default": True, "detail": "是否带符号"},
                  {"name": "where", "type": "bool序列", "default": None, "detail": "逐行筛选条件"}])
def op_median(x, *, column="amount", signed=True, where=None, notes=None):
    nums = sorted(_numbers(_mask(_collect(x, column_name=column, signed=signed)[0], where)))
    if not nums:
        _note(notes, "没有可求中位数的金额")
        return None
    mid = len(nums) // 2
    return nums[mid] if len(nums) % 2 else (nums[mid - 1] + nums[mid]) / Decimal(2)


@operator("std", family=NUMERIC, kind="agg", unit=YUAN, compat=True, detail="样本标准差；少于 2 笔得 None。",
          params=[{"name": "column", "type": "str", "default": "amount", "detail": "取哪一列"},
                  {"name": "signed", "type": "bool", "default": True, "detail": "是否带符号"},
                  {"name": "where", "type": "bool序列", "default": None, "detail": "逐行筛选条件"}])
def op_std(x, *, column="amount", signed=True, where=None, notes=None):
    nums = _numbers(_mask(_collect(x, column_name=column, signed=signed)[0], where))
    result = _std(nums)
    if result is None:
        _note(notes, "少于 2 笔，标准差无定义")
    return result


@operator("max", family=NUMERIC, kind="agg", unit=YUAN, compat=True, detail="最大值；也能对分组表取最大值。",
          params=[{"name": "column", "type": "str", "default": "amount", "detail": "取哪一列"},
                  {"name": "signed", "type": "bool", "default": True, "detail": "是否带符号"},
                  {"name": "where", "type": "bool序列", "default": None, "detail": "逐行筛选条件"}])
def op_max(x, *, column="amount", signed=True, where=None, notes=None):
    nums = _numbers(_mask(_collect(x, column_name=column, signed=signed)[0], where))
    if not nums:
        _note(notes, "没有可比较的金额")
        return None
    return max(nums)


@operator("min", family=NUMERIC, kind="agg", unit=YUAN, compat=True, detail="最小值；也能对分组表取最小值。",
          params=[{"name": "column", "type": "str", "default": "amount", "detail": "取哪一列"},
                  {"name": "signed", "type": "bool", "default": True, "detail": "是否带符号"},
                  {"name": "where", "type": "bool序列", "default": None, "detail": "逐行筛选条件"}])
def op_min(x, *, column="amount", signed=True, where=None, notes=None):
    nums = _numbers(_mask(_collect(x, column_name=column, signed=signed)[0], where))
    if not nums:
        _note(notes, "没有可比较的金额")
        return None
    return min(nums)


@operator("cv", family=NUMERIC, kind="agg", unit=RATIO,
          detail="变异系数 = 标准差/均值绝对值；均值 0 时无意义，得 None 而不是无穷大。",
          params=[{"name": "column", "type": "str", "default": "amount", "detail": "取哪一列"},
                  {"name": "signed", "type": "bool", "default": True, "detail": "是否带符号"},
                  {"name": "where", "type": "bool序列", "default": None, "detail": "逐行筛选条件"}])
def op_cv(x, *, column="amount", signed=True, where=None, notes=None):
    nums = _numbers(_mask(_collect(x, column_name=column, signed=signed)[0], where))
    std = _std(nums)
    if std is None:
        _note(notes, "少于 2 笔，变异系数无定义")
        return None
    mean = _mean(nums)
    if mean is None or mean == 0:
        _note(notes, "均值为 0，变异系数无定义")
        return None
    return std / abs(mean)


@operator("pct_change", family=NUMERIC, kind="series", unit=RATIO, compat=True,
          detail="相邻两笔的变化率，与本帧逐行对齐（首行为 None）；基数为 0 的那一笔为 None。")
def op_pct_change(x, *, column="amount", notes=None):
    values = _collect(x, column_name=column)[0]
    nums = [_to_decimal(v) for v in values]
    out: list[Any] = [None] * (1 if nums else 0)
    for prev, cur in zip(nums, nums[1:]):
        if prev is None or cur is None or prev == 0:
            out.append(None)
        else:
            out.append((cur - prev) / abs(prev))
    return Series("pct_change", out, x if isinstance(x, Frame) else None)


@operator("diff1", family=NUMERIC, kind="series", unit=YUAN, compat=True,
          detail="相邻两笔金额之差，与本帧逐行对齐（首行为 None）。")
def op_diff1(x, *, column="amount", notes=None):
    values = _collect(x, column_name=column)[0]
    nums = [_to_decimal(v) for v in values]
    out: list[Any] = [None] * (1 if nums else 0)
    for prev, cur in zip(nums, nums[1:]):
        out.append(None if prev is None or cur is None else cur - prev)
    return Series("diff1", out, x if isinstance(x, Frame) else None)


@operator("cumsum", family=NUMERIC, kind="series", unit=YUAN, compat=True,
          detail="按行顺序累计求和；空值行沿用上一个累计值。")
def op_cumsum(x, *, column="amount", notes=None):
    values = _collect(x, column_name=column)[0]
    total = Decimal(0)
    out: list[Any] = []
    for value in values:
        number = _to_decimal(value)
        if number is not None:
            total += number
        out.append(total)
    return Series("cumsum", out, x if isinstance(x, Frame) else None)


@operator("window_sum", family=NUMERIC, kind="series", unit=YUAN, compat=True,
          detail="最近 N 笔求和（滚动窗），前 N-1 行为 None。",
          params=[{"name": "n", "type": "int", "default": 7, "detail": "窗口笔数"}])
def op_window_sum(x, *, n=7, column="amount", notes=None):
    if int(n) < 1:
        raise OperatorError("window_sum 的 n 必须 >= 1")
    values = _collect(x, column_name=column)[0]
    nums = [_to_decimal(v) for v in values]
    out: list[Any] = []
    for index in range(len(nums)):
        start = index + 1 - int(n)
        if start < 0:
            out.append(None)
            continue
        window = [v for v in nums[start:index + 1] if v is not None]
        out.append(sum(window, Decimal(0)) if window else None)
    return Series("window_sum", out, x if isinstance(x, Frame) else None)


@operator("last", family=NUMERIC, kind="agg", unit=YUAN, detail="最后一个非空值（例如期末余额）。",
          params=[{"name": "column", "type": "str", "default": "amount", "detail": "取哪一列"},
                  {"name": "signed", "type": "bool", "default": True, "detail": "是否带符号"}])
def op_last(x, *, column="amount", signed=True, where=None, notes=None):
    values = _mask(_collect(x, column_name=column, signed=signed)[0], where)
    for value in reversed(values):
        if value is not None:
            return value
    _note(notes, "没有可用值")
    return None


@operator("first", family=NUMERIC, kind="agg", unit=YUAN, detail="第一个非空值（例如期初余额）。",
          params=[{"name": "column", "type": "str", "default": "amount", "detail": "取哪一列"},
                  {"name": "signed", "type": "bool", "default": True, "detail": "是否带符号"}])
def op_first(x, *, column="amount", signed=True, where=None, notes=None):
    values = _mask(_collect(x, column_name=column, signed=signed)[0], where)
    for value in values:
        if value is not None:
            return value
    _note(notes, "没有可用值")
    return None


# ---------- 标量算子（表达式里的算术与比较都落到这里） ----------

def _pair(a: Any, b: Any) -> tuple[Any, Any]:
    """比较/算术前统一类型：两边都能当数字就用 Decimal 比，否则按字符串比。"""
    left, right = _to_decimal(a), _to_decimal(b)
    if left is not None and right is not None:
        return left, right
    normalized_a = a.strip() if isinstance(a, str) else a
    normalized_b = b.strip() if isinstance(b, str) else b
    return normalized_a, normalized_b


@operator("add", family=NUMERIC, kind="scalar", unit=YUAN, detail="加法；任一侧缺失即缺失。")
def op_add(a, b, *, notes=None):
    left, right = _to_decimal(a), _to_decimal(b)
    return None if left is None or right is None else left + right


@operator("sub", family=NUMERIC, kind="scalar", unit=YUAN, detail="减法；任一侧缺失即缺失。")
def op_sub(a, b, *, notes=None):
    left, right = _to_decimal(a), _to_decimal(b)
    return None if left is None or right is None else left - right


@operator("mul", family=NUMERIC, kind="scalar", unit=YUAN, detail="乘法；任一侧缺失即缺失。")
def op_mul(a, b, *, notes=None):
    left, right = _to_decimal(a), _to_decimal(b)
    return None if left is None or right is None else left * right


@operator("div", family=NUMERIC, kind="scalar", unit=RATIO,
          detail="除法；分母为 0 或缺一侧都得 None（不抛异常，条件分支才有机会兜住）。")
def op_div(a, b, *, notes=None):
    left, right = _to_decimal(a), _to_decimal(b)
    if left is None or right is None:
        return None
    if right == 0:
        _note(notes, "分母为 0，比值无定义")
        return None
    return left / right


@operator("neg", family=NUMERIC, kind="scalar", unit=YUAN, detail="取负；缺失即缺失。")
def op_neg(a, *, notes=None):
    number = _to_decimal(a)
    return None if number is None else -number


@operator("abs", family=NUMERIC, kind="scalar", unit=YUAN, detail="取绝对值；缺失即缺失。")
def op_abs(a, *, notes=None):
    number = _to_decimal(a)
    return None if number is None else abs(number)


def _compare(key: str, a: Any, b: Any) -> bool | None:
    if a is None or b is None:
        return None
    left, right = _pair(a, b)
    try:
        if key == "gt":
            return left > right
        if key == "ge":
            return left >= right
        if key == "lt":
            return left < right
        if key == "le":
            return left <= right
        if key == "eq":
            return left == right
        return left != right
    except TypeError:
        return None


@operator("gt", family=LOGIC, kind="scalar", detail="大于；任一侧缺失即缺失。")
def op_gt(a, b, *, notes=None):
    return _compare("gt", a, b)


@operator("ge", family=LOGIC, kind="scalar", detail="大于等于；任一侧缺失即缺失。")
def op_ge(a, b, *, notes=None):
    return _compare("ge", a, b)


@operator("lt", family=LOGIC, kind="scalar", detail="小于；任一侧缺失即缺失。")
def op_lt(a, b, *, notes=None):
    return _compare("lt", a, b)


@operator("le", family=LOGIC, kind="scalar", detail="小于等于；任一侧缺失即缺失。")
def op_le(a, b, *, notes=None):
    return _compare("le", a, b)


@operator("eq", family=LOGIC, kind="scalar", detail="等于；数字按数值比，其余按字符串比。")
def op_eq(a, b, *, notes=None):
    return _compare("eq", a, b)


@operator("ne", family=LOGIC, kind="scalar", detail="不等于；任一侧缺失即缺失。")
def op_ne(a, b, *, notes=None):
    return _compare("ne", a, b)


@operator("and", family=LOGIC, kind="scalar", detail="三值与：有一侧为假即假，否则有缺失即缺失。")
def op_and(a, b, *, notes=None):
    left, right = _truth(a), _truth(b)
    if left is False or right is False:
        return False
    if left is None or right is None:
        return None
    return True


@operator("or", family=LOGIC, kind="scalar", detail="三值或：有一侧为真即真，否则有缺失即缺失。")
def op_or(a, b, *, notes=None):
    left, right = _truth(a), _truth(b)
    if left is True or right is True:
        return True
    if left is None or right is None:
        return None
    return False


@operator("not", family=LOGIC, kind="scalar", detail="三值非：缺失仍缺失。")
def op_not(a, *, notes=None):
    value = _truth(a)
    return None if value is None else (not value)


@operator("if_else", family=LOGIC, kind="scalar", detail="条件选择；条件缺失则结果缺失。")
def op_if_else(cond, yes, no, *, notes=None):
    flag = _truth(cond)
    if flag is None:
        return None
    return yes if flag else no


# ---------- 分组聚合族 ----------

def _group_key(by: Any, op: str) -> str:
    """分组键允许两种给法：列名字符串（步骤形态）或 Series（表达式里直接写列名）。"""
    if isinstance(by, Series):
        return by.name
    if isinstance(by, str) and by:
        return _COLUMN_ALIASES.get(by, by)
    raise OperatorError(f"算子 {op} 的分组键必须是列名或字符串，收到 {type(by).__name__}")


def _groups(x: Any, by: Any, op: str) -> dict[str, Any]:
    key = _group_key(by, op)
    if isinstance(x, dict):
        return dict(x)
    frame = _as_frame(x, op)
    grouped: dict[str, list[TxnRow]] = {}
    blank = "未识别对手方" if key == "counterparty_name" else ("未知月份" if key == "month" else "未识别")
    for row in frame.rows:
        raw = value_of(row, key)
        label = blank if raw is None or raw == "" else str(raw)
        grouped.setdefault(label, []).append(row)
    return grouped


@operator("group_by", family=GROUP, kind="group", unit="组", key_first=True, compat=True,
          detail="按某列分组，得到「组名 -> 行列表」的表。",
          params=[{"name": "column", "type": "str", "default": "counterparty_name", "detail": "分组列"}])
def op_group_by(x, *, column="counterparty_name", notes=None):
    frame = _as_frame(x, "group_by")
    return _groups(frame, column, "group_by")


@operator("group_by_counterparty", family=GROUP, kind="group", unit="组", compat=True,
          detail="按对手方分组的封存版写法（等价于 group_by(counterparty_name)）。")
def op_group_by_counterparty(x, *, notes=None):
    return _groups(x, "counterparty_name", "group_by_counterparty")


@operator("group_by_month", family=GROUP, kind="group", unit="组", compat=True,
          detail="按 YYYY-MM 分组的封存版写法（等价于 monthly()）。")
def op_group_by_month(x, *, notes=None):
    return _groups(x, "month", "group_by_month")


@operator("monthly", family=GROUP, kind="group", unit="组", detail="按月分组：组名是 YYYY-MM。")
def op_monthly(x, *, notes=None):
    return _groups(x, "month", "monthly")


def _agg_groups(x: Any, by: Any, fn: Callable[[Any], Any], op: str) -> dict[str, Any]:
    grouped = _groups(x, by, op)
    out: dict[str, Any] = {}
    for label, rows in grouped.items():
        value = fn(rows)
        if value is not None:
            out[label] = value
    return out


@operator("sum_by", family=GROUP, kind="agg", unit=YUAN, key_first=True,
          detail="分组求和：返回「组名 -> 金额」，组名顺序即输入顺序。",
          params=[{"name": "by", "type": "str", "default": "counterparty_name", "detail": "分组列"},
                  {"name": "signed", "type": "bool", "default": True, "detail": "是否带符号"}])
def op_sum_by(x, by="counterparty_name", *, signed=True, notes=None):
    return _agg_groups(x, by, lambda rows: op_sum(rows, signed=signed, notes=notes), "sum_by")


@operator("mean_by", family=GROUP, kind="agg", unit=YUAN, key_first=True,
          detail="分组求均值：返回「组名 -> 均值」。",
          params=[{"name": "by", "type": "str", "default": "counterparty_name", "detail": "分组列"},
                  {"name": "signed", "type": "bool", "default": True, "detail": "是否带符号"}])
def op_mean_by(x, by="counterparty_name", *, signed=True, notes=None):
    return _agg_groups(x, by, lambda rows: op_mean(rows, signed=signed, notes=notes), "mean_by")


@operator("count_by", family=GROUP, kind="agg", unit=PIECE, key_first=True,
          detail="分组计数：返回「组名 -> 笔数」。",
          params=[{"name": "by", "type": "str", "default": "counterparty_name", "detail": "分组列"}])
def op_count_by(x, by="counterparty_name", *, notes=None):
    return _agg_groups(x, by, lambda rows: len(rows) if isinstance(rows, list) else 1, "count_by")


@operator("distinct_count", family=GROUP, kind="agg", unit=TIMES, key_first=True,
          detail="不同取值个数（忽略空值，不把缺失当成一个对手方）。",
          params=[{"name": "by", "type": "str", "default": "counterparty_name", "detail": "去重列"}])
def op_distinct_count(x, by="counterparty_name", *, notes=None):
    key = _group_key(by, "distinct_count")
    if isinstance(x, dict):
        return len(x)
    frame = _as_frame(x, "distinct_count")
    values = [value_of(row, key) for row in frame.rows]
    if not values or all(v in (None, "") for v in values):
        # 整列都没有值就如实说不知道，返回 0 会谎称「没有对手方」
        frame.missing.add(key)
        _note(notes, f"没有任何非空的 {key}，无法统计去重个数")
        return None
    return len({str(v) for v in values if v not in (None, "")})


@operator("rank_by", family=GROUP, kind="agg", unit=YUAN, key_first=True,
          detail="分组后排序：返回按值降序的「组名 -> 金额」，取头部即集中度。",
          params=[{"name": "by", "type": "str", "default": "counterparty_name", "detail": "分组列"},
                  {"name": "mode", "type": "str", "default": "sum", "detail": "sum/count/mean"},
                  {"name": "desc", "type": "bool", "default": True, "detail": "是否降序"}])
def op_rank_by(x, by="counterparty_name", *, mode="sum", desc=True, signed=True, notes=None):
    grouped = _groups(x, by, "rank_by")
    modes = {
        "sum": lambda rows: op_sum(rows, signed=signed, notes=notes),
        "count": lambda rows: len(rows) if isinstance(rows, list) else 1,
        "mean": lambda rows: op_mean(rows, signed=signed, notes=notes),
    }
    agg = modes.get(str(mode))
    if agg is None:
        raise OperatorError(f"rank_by 的 mode 只能是 {'/'.join(modes)}，收到 {mode!r}")
    values = {label: agg(rows) for label, rows in grouped.items()}
    pairs = [(label, value) for label, value in values.items() if value is not None]
    pairs.sort(key=lambda kv: kv[1], reverse=bool(desc))
    return dict(pairs)


@operator("monthly_agg", family=GROUP, kind="agg", unit=YUAN, compat=True,
          detail="按月分组再聚合，mode 取 sum/count/mean/max/min。",
          params=[{"name": "mode", "type": "str", "default": "sum", "detail": "聚合方式"},
                  {"name": "signed", "type": "bool", "default": True, "detail": "是否带符号"}])
def op_monthly_agg(x, *, mode="sum", signed=True, notes=None):
    grouped = _groups(x, "month", "monthly_agg")
    modes = {
        "sum": lambda rows: op_sum(rows, signed=signed, notes=notes),
        "count": lambda rows: len(rows) if isinstance(rows, list) else 1,
        "mean": lambda rows: op_mean(rows, signed=signed, notes=notes),
        "max": lambda rows: op_max(rows, signed=signed, notes=notes),
        "min": lambda rows: op_min(rows, signed=signed, notes=notes),
    }
    agg = modes.get(str(mode))
    if agg is None:
        raise OperatorError(f"monthly_agg 的 mode 只能是 {'/'.join(modes)}，收到 {mode!r}")
    return {label: value for label, value in ((k, agg(v)) for k, v in grouped.items()) if value is not None}


# ---------- 时间窗族 ----------

@operator("within_days", family=WINDOW, kind="window", unit=DAY,
          detail="保留最近 N 天（含端点）的交易；锚点是本帧最大交易日，缺日期列则返回空帧。",
          params=[{"name": "days", "type": "int", "default": 90, "detail": "回溯天数"},
                  {"name": "ref", "type": "str", "default": None, "detail": "锚点日期 YYYY-MM-DD，缺省取本帧最大日期"}])
def op_within_days(x, *, days=90, ref=None, notes=None):
    frame = _as_frame(x, "within_days")
    if int(days) < 1:
        raise OperatorError("within_days 的 days 必须 >= 1")
    dates = [d for d in (_parse_date(row.txn_date) for row in frame.rows) if d is not None]
    if not dates:
        frame.missing.add("txn_date")
        return Frame([], origin=f"最近{int(days)}天（无日期可用）")
    anchor = _parse_date(ref) if ref else max(dates)
    if anchor is None:
        raise OperatorError(f"within_days 的 ref 不是合法日期：{ref!r}")
    cutoff = anchor - timedelta(days=int(days))
    kept: list[TxnRow] = []
    for row in frame.rows:
        row_date = _parse_date(row.txn_date)
        if row_date is not None and cutoff <= row_date <= anchor:
            kept.append(row)
    return Frame(kept, origin=f"最近{int(days)}天（锚点 {anchor.isoformat()}）")


@operator("between_dates", family=WINDOW, kind="window", unit=DAY,
          detail="保留 start..end（含端点）之间的交易；只给一端就是单边开区间。",
          params=[{"name": "start", "type": "str", "default": None, "detail": "起始日 YYYY-MM-DD"},
                  {"name": "end", "type": "str", "default": None, "detail": "结束日 YYYY-MM-DD"}])
def op_between_dates(x, *, start=None, end=None, notes=None):
    frame = _as_frame(x, "between_dates")
    low = _parse_date(start) if start else None
    high = _parse_date(end) if end else None
    if start and low is None:
        raise OperatorError(f"between_dates 的 start 不是合法日期：{start!r}")
    if end and high is None:
        raise OperatorError(f"between_dates 的 end 不是合法日期：{end!r}")
    kept: list[TxnRow] = []
    for row in frame.rows:
        row_date = _parse_date(row.txn_date)
        if row_date is None:
            continue
        if low is not None and row_date < low:
            continue
        if high is not None and row_date > high:
            continue
        kept.append(row)
    return Frame(kept, origin=f"{start or '起'}~{end or '止'}")


@operator("by_hour", family=WINDOW, kind="agg", unit=PIECE,
          detail="按小时分组统计，组名是两位小时 00..23。",
          params=[{"name": "mode", "type": "str", "default": "count", "detail": "count/sum"}])
def op_by_hour(x, *, mode="count", signed=False, notes=None):
    frame = _as_frame(x, "by_hour")
    buckets: dict[str, list[TxnRow]] = {}
    for row in frame.rows:
        hour = _row_hour(row)
        if hour is None:
            continue
        buckets.setdefault(f"{hour:02d}", []).append(row)
    if not buckets:
        frame.missing.add("trade_time")
        return {}
    if str(mode) == "count":
        return {key: len(rows) for key, rows in sorted(buckets.items())}
    if str(mode) == "sum":
        return {key: op_sum(rows, signed=signed, notes=notes) for key, rows in sorted(buckets.items())}
    raise OperatorError(f"by_hour 的 mode 只能是 count/sum，收到 {mode!r}")


@operator("hour_band", family=WINDOW, kind="window", unit=PIECE,
          detail="按时段过滤：night 22:00-05:59、morning 06-11、afternoon 12-17、evening 18-21、day 06-21。",
          params=[{"name": "band", "type": "str", "default": "night", "detail": "时段名"}])
def op_hour_band(x, *, band="night", notes=None):
    frame = _as_frame(x, "hour_band")
    bands: dict[str, Callable[[int], bool]] = {
        "night": lambda h: h >= 22 or h <= 5,
        "morning": lambda h: 6 <= h <= 11,
        "afternoon": lambda h: 12 <= h <= 17,
        "evening": lambda h: 18 <= h <= 21,
        "day": lambda h: 6 <= h <= 21,
    }
    rule = bands.get(str(band))
    if rule is None:
        raise OperatorError(f"hour_band 的 band 只能是 {'/'.join(bands)}，收到 {band!r}")
    kept: list[TxnRow] = []
    for row in frame.rows:
        hour = _row_hour(row)
        if hour is not None and rule(hour):
            kept.append(row)
    if not kept and all(_row_hour(row) is None for row in frame.rows):
        frame.missing.add("trade_time")
    return Frame(kept, origin=f"时段 {band}")


@operator("by_dow", family=WINDOW, kind="agg", unit=PIECE,
          detail="按星期分组统计，组名是周一..周日。",
          params=[{"name": "mode", "type": "str", "default": "count", "detail": "count/sum"}])
def op_by_dow(x, *, mode="count", signed=False, notes=None):
    frame = _as_frame(x, "by_dow")
    names = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
    buckets: dict[str, list[TxnRow]] = {}
    for row in frame.rows:
        dow = _row_dow(row)
        if dow is None:
            continue
        buckets.setdefault(names[dow], []).append(row)
    if not buckets:
        frame.missing.add("txn_date")
        return {}
    if str(mode) == "count":
        return {name: len(buckets[name]) for name in names if name in buckets}
    if str(mode) == "sum":
        return {name: op_sum(buckets[name], signed=signed, notes=notes) for name in names if name in buckets}
    raise OperatorError(f"by_dow 的 mode 只能是 count/sum，收到 {mode!r}")


@operator("span_days", family=WINDOW, kind="agg", unit=DAY,
          detail="账期覆盖天数（最大日 - 最小日 + 1）；没有可用日期得 None。")
def op_span_days(x, *, notes=None):
    frame = _as_frame(x, "span_days")
    dates = [d for d in (_parse_date(row.txn_date) for row in frame.rows) if d is not None]
    if not dates:
        frame.missing.add("txn_date")
        _note(notes, "没有可用交易日，无法计算账期天数")
        return None
    return (max(dates) - min(dates)).days + 1


# ---------- 过滤族（封存版 atoms 的老写法） ----------

@operator("filter_direction", family=FILTER, kind="filter", unit=PIECE, compat=True,
          detail="只保留指定收付方向（in/out）。",
          params=[{"name": "value", "type": "str", "default": "out", "detail": "in 或 out"}])
def op_filter_direction(x, *, value="out", notes=None):
    frame = _as_frame(x, "filter_direction")
    wanted = str(value).strip().lower()
    if wanted not in ("in", "out"):
        raise OperatorError(f"filter_direction 的 value 只能是 in/out，收到 {value!r}")
    kept = [row for row in frame.rows if (row.direction or "").strip().lower() == wanted]
    if not kept and all((row.direction or "") == "" for row in frame.rows):
        frame.missing.add("direction")
    return Frame(kept, origin=f"方向 {wanted}")


@operator("filter_amount_abs_ge", family=FILTER, kind="filter", unit=PIECE, compat=True,
          detail="只保留金额绝对值不小于阈值的交易。",
          params=[{"name": "value", "type": "float", "default": 10000, "detail": "金额阈值（元）"}])
def op_filter_amount_abs_ge(x, *, value=10000, notes=None):
    frame = _as_frame(x, "filter_amount_abs_ge")
    threshold = _to_decimal(value)
    if threshold is None:
        raise OperatorError(f"filter_amount_abs_ge 的 value 不是合法数值：{value!r}")
    kept: list[TxnRow] = []
    for row in frame.rows:
        amount = _to_decimal(row.amount)
        if amount is not None and abs(amount) >= threshold:
            kept.append(row)
    if not kept and all(row.amount is None for row in frame.rows):
        frame.missing.add("amount")
    return Frame(kept, origin=f"金额绝对值不低于 {threshold}")


@operator("filter_counterparty_contains", family=FILTER, kind="filter", unit=PIECE, compat=True,
          detail="只保留对手方名称包含指定文字的交易（空串不过滤任何行）。",
          params=[{"name": "value", "type": "str", "default": "", "detail": "包含的文字"}])
def op_filter_counterparty_contains(x, *, value="", notes=None):
    frame = _as_frame(x, "filter_counterparty_contains")
    needle = str(value or "")
    kept = [row for row in frame.rows
            if needle and row.counterparty_name and needle in row.counterparty_name]
    if not kept and all(not row.counterparty_name for row in frame.rows):
        frame.missing.add("counterparty_name")
    return Frame(kept, origin=f"对手方含 {needle}")


# ---------- 唯一执行入口 ----------

def _accepts_notes(fn: Callable[..., Any]) -> bool:
    code = getattr(fn, "__code__", None)
    return bool(code) and "notes" in code.co_varnames


def _call(spec: OpSpec, args: tuple, kwargs: dict, notes: list[str] | None) -> Any:
    if _accepts_notes(spec.fn):
        kwargs = {**kwargs, "notes": notes}
    try:
        return spec.fn(*args, **kwargs)
    except TypeError as exc:
        raise OperatorError(f"算子 {spec.key} 的参数不对：{exc}") from None
    except ArithmeticError as exc:
        raise OperatorError(f"算子 {spec.key} 计算失败：{exc}") from None


def _vectorize(spec: OpSpec, args: tuple, kwargs: dict, notes: list[str] | None) -> Series:
    """标量算子在遇到列时逐行展开：这是表达式能写「amount if direction=='out' else 0」的原因。"""
    lengths = {len(a) for a in args if isinstance(a, Series)}
    lengths |= {len(v) for v in kwargs.values() if isinstance(v, Series)}
    if len(lengths) > 1:
        raise OperatorError(f"算子 {spec.key} 的列长度不一致：{sorted(lengths)}")
    length = lengths.pop() if lengths else 0
    frame = next((a.frame for a in args if isinstance(a, Series) and a.frame is not None), None)
    out: list[Any] = []
    for index in range(length):
        row_args = tuple(a.values[index] if isinstance(a, Series) else a for a in args)
        row_kwargs = {k: (v.values[index] if isinstance(v, Series) else v) for k, v in kwargs.items()}
        out.append(_call(spec, row_args, row_kwargs, notes))
    return Series(spec.key, out, frame)


def invoke(key: str, *args: Any, notes: list[str] | None = None, **kwargs: Any) -> Any:
    """唯一执行入口：步骤形态与表达式形态都从这里进，算子语义只有一份。"""
    spec = spec_of(key)
    if spec.kind == "scalar" and any(isinstance(a, Series) for a in args + tuple(kwargs.values())):
        return _vectorize(spec, args, kwargs, notes)
    return _call(spec, args, kwargs, notes)


def invoke_for_expr(key: str, frame: Frame, positional: list[Any], keyword: dict[str, Any],
                    notes: list[str] | None = None) -> Any:
    """表达式调用点：先按算子种类补齐「数据帧」这个隐式第一参数。"""
    spec = spec_of(key)
    if spec.kind == "scalar":
        return invoke(key, *positional, notes=notes, **keyword)
    if spec.key_first:
        return invoke(key, frame, *positional, notes=notes, **keyword)
    if spec.kind in ("agg", "series"):
        if positional and isinstance(positional[0], (Frame, Series, dict, list, tuple)):
            return invoke(key, *positional, notes=notes, **keyword)
        if positional:
            raise OperatorError(
                f"算子 {key} 的第一个参数必须是数据帧或列，收到 {type(positional[0]).__name__}"
            )
        return invoke(key, frame, notes=notes, **keyword)
    # group / window / filter / series：数据帧永远在第一位，其余位置参数都是它的参数
    return invoke(key, frame, *positional, notes=notes, **keyword)


def run_steps(steps: Sequence[dict], data: Any = None, *, notes: list[str] | None = None,
              frame: Frame | None = None) -> Any:
    """按「算子 + 参数」逐步执行，返回最后一步的结果。

    步骤形态就是封存版 CustomMetric.steps 的写法：老数据不改一个字就能跑。
    """
    if data is None:
        if frame is None:
            raise OperatorError("run_steps 需要数据帧或行列表作为起点")
        data = frame
    elif not isinstance(data, Frame) and isinstance(data, (list, tuple)):
        data = Frame(list(data))
    notes = [] if notes is None else notes
    if not isinstance(steps, (list, tuple)):
        raise OperatorError(f"steps 必须是列表，收到 {type(steps).__name__}")
    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            raise OperatorError(f"第 {index} 步不是字典：{step!r}")
        key = str(step.get("atom") or step.get("operator") or "")
        if not key:
            raise OperatorError(f"第 {index} 步缺少 atom 名称")
        args = dict(step.get("args") or {})
        try:
            data = invoke(key, data, notes=notes, **args)
        except UnknownOperator:
            raise
        except OperatorError as exc:
            raise OperatorError(f"第 {index} 步（{key}）：{exc}") from None
    return data


