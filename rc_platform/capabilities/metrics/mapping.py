"""指标 <-> 特征 的映射表：把「两套口径」变成一张显式清单。

为什么要有这张表：指标（B01、A01…）和特征（f_out_total、f_in_total…）现在各有一套实现，
同一个概念两个值，改口径要改两处，漏一处没有任何东西会提醒你。

这张表做两件事：
1. 能映射的，写成表达式，由特征引擎算——这样口径只有一个来源
2. 映射不了的，写清**卡在哪**（缺哪个算子/哪份输入），而不是悄悄跳过

配 tools/metric_parity 使用：凡是标了 expr 的，逐值与旧实现比对；对不上就红。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from ..features import expr as expr_mod
from ..features.operators import Frame, OperatorError
from . import ops_metrics  # noqa: F401  注册指标口径专用算子（导入即注册）


@dataclass(frozen=True, slots=True)
class MetricMapping:
    code: str
    name: str
    expr: str | None = None
    blocked: str | None = None      # 映射不了的原因：缺算子 / 缺输入 / 口径未定
    scale: int = 4                  # 比对时的量化位数：金额 2，比例 4

    @property
    def mapped(self) -> bool:
        return self.expr is not None


MAPPINGS: dict[str, MetricMapping] = {
    "A01": MetricMapping("A01", "期间收入合计", "sum(amount, where=direction=='in')", scale=2),
    # 语义类：词库已就绪；无命中按旧口径给 0（跑过没命中 = 0，没跑 = none）。
    # 这条约定由产品定，代码只用 if_else 显式写出来，不藏在算子默认值里。
    "A05": MetricMapping("A05", "工资占比",
                         "if_else(count(where=in_lexicon(name='salary')) == 0, 0, "
                         "sum(amount, where=in_lexicon(name='salary')) / sum(amount, where=direction=='in'))"),
    # 分母是「全部出账」不是收入：实测 1000/3300.5=0.3030 才和旧口径一致
    "C07": MetricMapping("C07", "现金提取占比",
                         "if_else(count(where=in_lexicon(name='cash') and direction=='out') == 0, 0, "
                         "sum(amount, where=in_lexicon(name='cash') and direction=='out') / "
                         "sum(amount, where=direction=='out'))"),
    "E06": MetricMapping("E06", "虚拟币命中率",
                         "if_else(count(where=in_lexicon(name='crypto')) == 0, 0, "
                         "count(where=in_lexicon(name='crypto')) / count())"),
    "E07": MetricMapping("E07", "现金存入占比",
                         "if_else(count(where=in_lexicon(name='cash') and direction=='in') == 0, 0, "
                         "sum(amount, where=in_lexicon(name='cash') and direction=='in') / "
                         "sum(amount, where=direction=='in'))"),
    "E08": MetricMapping("E08", "第三方支付占比",
                         "if_else(count(where=in_lexicon(name='third_party')) == 0, 0, "
                         "sum(amount, where=in_lexicon(name='third_party')) / sum(amount, signed=false))"),
    "C01": MetricMapping("C01", "净流入",
                         "sum(amount, where=direction=='in') - sum(amount, where=direction=='out')", scale=2),
    "C02": MetricMapping("C02", "流入流出比",
                         "sum(amount, where=direction=='in') / sum(amount, where=direction=='out')"),
    # 实测对不上：旧值 0.3061，本实现 0.3215（样本标准差/均值）。
    # 换成总体标准差是 0.2935，也对不上。旧的样本集口径（是否按日去重、用哪个均值）必须先确认，
    # 这就是「两套口径」的活证据——不对照就永远发现不了。
    "A02": MetricMapping("A02", "月均收入",
                         "sum(amount, where=direction=='in') / coverage_months()", scale=2),
    "A03": MetricMapping("A03", "月收入中位数",
                         "median(monthly_values(column='amount', where=direction=='in'))", scale=2),
    "B07": MetricMapping("B07", "透支天数", "overdraft_days()", scale=0),
    "C03": MetricMapping("C03", "日均余额", "mean(daily_balances())", scale=2),
    "C04": MetricMapping("C04", "余额波动率",
                         "pstdev(daily_balances()) / mean(daily_balances())"),
    "A04": MetricMapping("A04", "收入稳定性",
                         "if_else(month_count() < 2, none, "
                         "pstdev(monthly_values(column='amount', where=direction=='in')) / "
                         "abs(mean(monthly_values(column='amount', where=direction=='in'))))"),
    "A07": MetricMapping("A07", "收入趋势斜率",
                         "slope(monthly_values(column='amount', where=direction=='in'))", scale=2),
    "C05": MetricMapping("C05", "期末余额趋势", "slope(month_end_balances())", scale=2),
    "D01": MetricMapping("D01", "月度笔数波动",
                         "if_else(month_count() < 2, none, "
                         "pstdev(monthly_values(agg='count')) / mean(monthly_values(agg='count')))"),
    "D06": MetricMapping("D06", "休眠月数", "idle_months()", scale=0),
    "E01": MetricMapping("E01", "对手方集中度 HHI", "share_square_sum()"),
    "E02": MetricMapping("E02", "前三大占比", "top_share(k=3)"),
    "C06": MetricMapping("C06", "近三十天最低余额", "min(balance)"),
    "B08": MetricMapping("B08", "负余额笔数占比", "count(where=balance < 0) / count()"),
    "D05": MetricMapping("D05", "单笔最大占比",
                         "max(amount, where=direction=='in') / (sum(amount, where=direction=='in') + sum(amount, where=direction=='out'))"),
    "D02": MetricMapping("D02", "夜间交易占比",
                         "count(where=(direction=='in' or direction=='out') and hour(trade_time) >= 22) / count()",
                         blocked=None),
}

# 未映射指标的**具体原因**。按「缺什么」分类，而不是一句「还没做」——
# 每条都指向一个明确要补的能力，否则这张清单就没有决策价值。
# 词库与文本算子已经有了（features/lexicon.py + contains/matches/in_lexicon），
# 但语义指标还卡在另一件事上：无命中时的约定不同——旧口径给 0.0000，特征引擎给 none 并要求写清原因。
# 这不是 bug，是两种产品观：0 会让报告看起来「查过了，没有」，none 会说「没查到/没数据」。
# 要先由业务定下约定，再决定是给表达式加 guard 还是给映射表加 zero_when_empty 标记。
_TEXT_LIBRARY = "词库与文本算子已就绪；待定「无命中」约定（旧口径 0 / 引擎 none）后才能切换"
_MONTH_SERIES = "缺日历月序列算子：要按自然月补空月后再聚合/回归"
_NEEDS_EXCLUSION = "缺剔除层结果：依赖六类剔除（同名互转/退款/放款/理财/信用卡/代付）"
_DAY_SERIES = "缺按日序列算子：要按交易日分组后再算同日进出、月末窗口这类量"
_MODULO = "缺取模/整数判定算子：\'amount % 100 == 0\' 这类形态判断现在写不出来"
_SALARY_DAY = "缺「工资到账日」识别（语义词库）+ 日序列，两者都要"

_REPAY_CLASS = "缺还款类语义分类（房贷/消费贷/分期/信用卡）：既要词库也要月序列，先有分类才能算月供"
_BLOCKED: dict[str, str] = {
    # 规则/词库类（14 项）：本质不是算子问题，交给「命中词库」能力
    "A05": _TEXT_LIBRARY, "A06": _TEXT_LIBRARY, "B03": _TEXT_LIBRARY, "B04": _TEXT_LIBRARY,
    "B05": _TEXT_LIBRARY, "B06": _TEXT_LIBRARY, "C07": _TEXT_LIBRARY, "D04": _TEXT_LIBRARY,
    "E03": _TEXT_LIBRARY, "E04": _TEXT_LIBRARY, "E05": _TEXT_LIBRARY,

    # 还款分类（2 项）：分类 + 月序列都要
    "B01": _REPAY_CLASS, "B02": _REPAY_CLASS,
    # 序列与算子缺口（4 项）
    "C08": _DAY_SERIES, "D08": _DAY_SERIES,
    "D03": _MODULO,
    "D07": _SALARY_DAY,
    # 依赖剔除层（1 项）
    "A08": _NEEDS_EXCLUSION,
}

_BLOCKED_DEFAULT = "尚未映射：等映射表补齐后再动旧实现"

ALL_CODES: dict[str, str] = {
    "A01": "期间收入合计", "A02": "月均收入", "A03": "月收入中位数", "A04": "收入稳定性",
    "A05": "工资占比", "A06": "工资规律月数", "A07": "收入趋势斜率", "A08": "剔除额占比",
    "B01": "月还款合计", "B02": "债务收入比 DTI", "B03": "新增贷款笔数", "B04": "网贷平台数",
    "B05": "小贷还款笔数", "B06": "信用卡还款额", "B07": "透支天数", "B08": "负余额笔数占比",
    "C01": "净流入", "C02": "流入流出比", "C03": "日均余额", "C04": "余额波动率",
    "C05": "期末余额趋势", "C06": "近三十天最低余额", "C07": "现金提取占比", "C08": "当日进出占比",
    "D01": "月度笔数波动", "D02": "夜间交易占比", "D03": "整数金额占比", "D04": "大额笔数",
    "D05": "单笔最大占比", "D06": "休眠月数", "D07": "工资到账日波动", "D08": "期末冲量",
    "E01": "对手方集中度 HHI", "E02": "前三大占比", "E03": "关联方占比", "E04": "小贷命中率",
    "E05": "涉赌命中率", "E06": "虚拟币命中率", "E07": "现金存入占比", "E08": "第三方支付占比",
}


def registry() -> dict[str, MetricMapping]:
    """完整清单：已映射的用表达式，未映射的带原因。少一个指标都会被发现。"""
    out: dict[str, MetricMapping] = {}
    for code, name in ALL_CODES.items():
        out[code] = MAPPINGS.get(code) or MetricMapping(code, name, blocked=_BLOCKED.get(code, _BLOCKED_DEFAULT))
    return out


def evaluate(statement) -> dict[str, Decimal | None]:
    """只算已映射的那些；未映射的不出现（不是 0）。"""
    frame = Frame(list(statement.rows))
    values: dict[str, Decimal | None] = {}
    for code, mapping in registry().items():
        if not mapping.mapped:
            continue
        notes: list[str] = []
        try:
            raw = expr_mod.eval_expr(mapping.expr, frame, notes=notes)
        except (OperatorError, expr_mod.ExprError):
            values[code] = None
            continue
        values[code] = _as_decimal(raw)
    return values


def _as_decimal(value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def coverage() -> dict[str, int]:
    total = len(ALL_CODES)
    mapped = sum(1 for item in registry().values() if item.mapped)
    return {"total": total, "mapped": mapped, "blocked": total - mapped}
