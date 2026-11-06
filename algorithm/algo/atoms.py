"""计算元（atoms）：把流水抽象成可组合的基础计算，供银行侧自行组织自定义指标。

为什么需要：
    现在指标是写死的 40 项，业务想加一个「近三个月夜间小额高频的占比」只能改代码。
    指标口径页能登记公式，但没有可用的计算语言——没有 sum/分组/时间窗这些基础件，
    「自定义指标」就只能写自然语言描述。

设计取向（对标 pandas，但只保留风控真正用得到的）：
    - 每个计算元是纯函数，输入 Txn 序列（含 date/amount/balance/direction/counterparty/summary），
      输出数值或序列，不依赖外部状态。
    - 组合方式：先用 filter / group_by 缩小数据集，再用 agg 聚合，最后用 window 切时间窗。
    - 不做表达式解析器（那是另一个工程）；口径页登记的是「计算元 + 参数」的结构化描述，
      执行时按描述逐步调用，可解释、可审计。

字段口径（与前端字段映射一致）：
    date        交易日 YYYY-MM-DD
    amount      金额（正=入账，负=出账；收付方向缺失时按正负约定）
    balance     交易后余额
    direction   in / out（可能缺失）
    counterparty 对方户名/账号
    summary     摘要
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Iterable

Number = float


@dataclass
class TxnView:
    """计算元的输入单元：一份流水里的一笔交易，字段归一。"""
    date: str | None = None
    amount: float | None = None
    balance: float | None = None
    direction: str | None = None
    counterparty: str | None = None
    summary: str | None = None


@dataclass
class Atom:
    """一个计算元：名称、说明、参数与实现。"""
    key: str
    label: str
    kind: str            # filter / transform / agg / window / group
    unit: str            # 元 / 笔 / 次 / 月 / 比例
    detail: str
    params: list[dict] = field(default_factory=list)
    example: str = ""
    fn: Callable[..., Any] | None = None


def _amt(txns: Iterable[TxnView]) -> list[float]:
    return [float(t.amount) for t in txns if t.amount is not None]


# ---------- 聚合类 ----------

def agg_sum(txns: Iterable[TxnView]) -> float:
    return sum(_amt(txns))


def agg_count(txns: Iterable[TxnView]) -> int:
    return len(list(txns))


def agg_mean(txns: Iterable[TxnView]) -> float | None:
    xs = _amt(txns)
    return sum(xs) / len(xs) if xs else None


def agg_median(txns: Iterable[TxnView]) -> float | None:
    xs = sorted(_amt(txns))
    if not xs:
        return None
    mid = len(xs) // 2
    return xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2


def agg_max(txns: Iterable[TxnView]) -> float | None:
    xs = _amt(txns)
    return max(xs) if xs else None


def agg_min(txns: Iterable[TxnView]) -> float | None:
    xs = _amt(txns)
    return min(xs) if xs else None


def agg_std(txns: Iterable[TxnView]) -> float | None:
    xs = _amt(txns)
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


# ---------- 序列类 ----------

def seq_diff1(txns: Iterable[TxnView]) -> list[float]:
    """相邻两笔金额的差：看单笔跳变是否异常。"""
    xs = _amt(txns)
    return [b - a for a, b in zip(xs, xs[1:])]


def seq_pct_change(txns: Iterable[TxnView]) -> list[float | None]:
    xs = _amt(txns)
    out: list[float | None] = []
    for a, b in zip(xs, xs[1:]):
        out.append(None if a == 0 else (b - a) / abs(a))
    return out


def seq_cumsum(txns: Iterable[TxnView]) -> list[float]:
    xs = _amt(txns)
    total = 0.0
    out = []
    for x in xs:
        total += x
        out.append(total)
    return out


def window_sum(txns: Iterable[TxnView], n: int = 7) -> list[float | None]:
    """滚动 N 笔求和：看短期内资金集中度。"""
    xs = _amt(txns)
    out: list[float | None] = []
    for i in range(len(xs)):
        if i + 1 < n:
            out.append(None)
        else:
            out.append(sum(xs[i + 1 - n: i + 1]))
    return out


# ---------- 过滤 / 分组 ----------

def filt_direction(txns: Iterable[TxnView], value: str = "out") -> list[TxnView]:
    return [t for t in txns if (t.direction or "") == value]


def filt_amount_abs_ge(txns: Iterable[TxnView], value: float = 10000) -> list[TxnView]:
    return [t for t in txns if t.amount is not None and abs(t.amount) >= value]


def filt_counterparty_contains(txns: Iterable[TxnView], value: str = "") -> list[TxnView]:
    return [t for t in txns if t.counterparty and value and value in t.counterparty]


def group_by_counterparty(txns: Iterable[TxnView]) -> dict[str, list[TxnView]]:
    g: dict[str, list[TxnView]] = defaultdict(list)
    for t in txns:
        g[t.counterparty or "未识别对手方"].append(t)
    return dict(g)


def group_by_month(txns: Iterable[TxnView]) -> dict[str, list[TxnView]]:
    g: dict[str, list[TxnView]] = defaultdict(list)
    for t in txns:
        key = (t.date or "")[:7] or "未知月份"
        g[key].append(t)
    return dict(g)


def monthly_agg(txns: Iterable[TxnView], mode: str = "sum") -> dict[str, float]:
    fn = {"sum": agg_sum, "count": agg_count, "mean": agg_mean,
          "max": agg_max, "min": agg_min}.get(mode, agg_sum)
    out: dict[str, float] = {}
    for month, group in group_by_month(txns).items():
        v = fn(group)
        if v is not None:
            out[month] = float(v)
    return out


# ---------- 注册表 ----------

ATOMS: list[Atom] = [
    Atom("sum", "求和", "agg", "元", "把金额加起来；入账为正、出账为负时即是净额。",
         example="近 6 个月净流入 = sum(全部交易)"),
    Atom("count", "计数", "agg", "笔", "统计交易笔数。",
         example="单笔≥1 万元的笔数 = count(filter_amount_abs_ge(10000))"),
    Atom("mean", "均值", "agg", "元", "平均值；缺失金额的交易不计入。",
         example="月均消费 = mean(全部出账)"),
    Atom("median", "中位数", "agg", "元", "中位数，比均值抗极端值。",
         example="单笔金额中位数 = median(全部交易)"),
    Atom("max", "最大值", "agg", "元", "最大金额。", example="单笔最大流出 = min(全部交易) 的绝对值"),
    Atom("min", "最小值", "agg", "元", "最小金额（出账为负时即最大流出）。"),
    Atom("std", "标准差", "agg", "元", "金额波动；越大越不稳定。"),
    Atom("diff1", "一阶差分", "transform", "元", "相邻两笔金额之差；用来发现单笔跳变。"),
    Atom("pct_change", "变化率", "transform", "比例", "相邻两笔的相对变化。"),
    Atom("cumsum", "累计和", "transform", "元", "按时间顺序累计；可与余额互相印证。"),
    Atom("window_sum", "滚动求和", "window", "元", "最近 N 笔的和，参数 n 默认 7。",
         params=[{"name": "n", "type": "int", "default": 7, "detail": "窗口笔数"}]),
    Atom("filter_direction", "按收付方向过滤", "filter", "笔", "只保留 in / out。",
         params=[{"name": "value", "type": "str", "default": "out", "detail": "in 或 out"}]),
    Atom("filter_amount_abs_ge", "按金额绝对值过滤", "filter", "笔", "只保留 |金额| ≥ 阈值的交易。",
         params=[{"name": "value", "type": "float", "default": 10000, "detail": "金额阈值（元）"}]),
    Atom("filter_counterparty_contains", "按对手方包含过滤", "filter", "笔", "对手方名称包含指定文字。",
         params=[{"name": "value", "type": "str", "default": "", "detail": "包含的文字"}]),
    Atom("group_by_counterparty", "按对手方分组", "group", "组", "按对方户名/账号分组，用于集中度分析。"),
    Atom("group_by_month", "按月分组", "group", "组", "按 YYYY-MM 分组。"),
    Atom("monthly_agg", "按月聚合", "group", "元", "先按月分组再聚合，mode 取 sum/count/mean/max/min。",
         params=[{"name": "mode", "type": "str", "default": "sum", "detail": "聚合方式"}]),
]

ATOM_BY_KEY: dict[str, Atom] = {a.key: a for a in ATOMS}

_FN_MAP: dict[str, Callable[..., Any]] = {
    "sum": agg_sum, "count": agg_count, "mean": agg_mean, "median": agg_median,
    "max": agg_max, "min": agg_min, "std": agg_std,
    "diff1": seq_diff1, "pct_change": seq_pct_change, "cumsum": seq_cumsum,
    "window_sum": window_sum,
    "filter_direction": filt_direction, "filter_amount_abs_ge": filt_amount_abs_ge,
    "filter_counterparty_contains": filt_counterparty_contains,
    "group_by_counterparty": group_by_counterparty, "group_by_month": group_by_month,
    "monthly_agg": monthly_agg,
}


def catalog() -> list[dict]:
    """给前端/银行侧看的计算元目录。"""
    return [
        {
            "key": a.key, "label": a.label, "kind": a.kind, "unit": a.unit,
            "detail": a.detail, "params": a.params, "example": a.example,
        }
        for a in ATOMS
    ]


def evaluate(steps: list[dict], txns: list[TxnView] | list[dict]) -> Any:
    """按「计算元 + 参数」的步骤描述依次执行，返回最后一步的结果。

    步骤形如 [{"atom": "filter_direction", "args": {"value": "out"}},
              {"atom": "sum"}]
    中间结果可以是 list[TxnView] 或 dict[str, list[TxnView]] 或数值；
    只有 list[TxnView] 能继续被下一步消费，分歧会明确报错而不是静默返回 None。
    """
    data: Any = [
        TxnView(**t) if isinstance(t, dict) else t for t in txns
    ]
    for i, step in enumerate(steps):
        key = str(step.get("atom") or "")
        fn = _FN_MAP.get(key)
        if fn is None:
            raise ValueError(f"第 {i + 1} 步：未知计算元 {key}")
        args = step.get("args") or {}
        if isinstance(data, dict):
            data = list(data.values())
        if not isinstance(data, list):
            raise ValueError(f"第 {i + 1} 步：上一步结果是数值，无法继续组合；聚合类计算元应放在最后")
        data = fn(data, **args) if args else fn(data)
    return data
