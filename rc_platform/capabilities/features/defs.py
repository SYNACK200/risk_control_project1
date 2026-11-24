"""特征定义与计算：把算子/表达式装成一条可复算的特征。

为什么把 reason 当成一等公民：指标系统最坏的失败不是算错，而是缺列时悄悄填 0——
下游拿 0 去评分，报告看起来一切正常。所以「算不出来」必须带着原因显式出现。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Sequence

from ...core.contracts import FeatureSet, Statement
from . import expr as expr_mod
from .operators import Frame, OperatorError, run_steps

SCHEMA: dict[str, Any] = {
    "columns": ["code", "name", "value", "unit", "reason", "version"],
    "value_types": ["Decimal", "int", "bool", "str", "None"],
    "amount_type": "Decimal（禁止 float）",
    "null_policy": "缺输入为 None 且 reason 写明缺什么；只有笔数/个数这类空集本身是真值的特征可以为 0",
}


class FeatureDefError(ValueError):
    """特征定义写错了（两种形态都缺、steps 算不出标量、算子名不存在）。属于配置错误，必须报出来。"""


@dataclass(slots=True)
class FeatureDef:
    """一条特征的定义：两种形态二选一，一个特征是「一个标量」。

    version 跟着特征走而不是跟着文件走：口径改了要能一眼看出是哪一版算出来的。
    """
    code: str
    name: str
    unit: str = ""
    steps: list[dict] | None = None
    expr: str | None = None
    version: str = "1.0"
    description: str = ""
    category: str = "基础统计"

    def __post_init__(self) -> None:
        if not self.code or not self.name:
            raise FeatureDefError("特征必须有 code 与 name")
        if bool(self.steps) == bool(self.expr):
            raise FeatureDefError(f"特征 {self.code}：steps 与 expr 必须二选一（现在两者{'都有' if self.steps else '都没有'}）")
        if self.steps is not None:
            if not isinstance(self.steps, (list, tuple)) or not self.steps:
                raise FeatureDefError(f"特征 {self.code}：steps 必须是非空列表")
            for index, step in enumerate(self.steps, 1):
                if not isinstance(step, dict) or not str(step.get("atom") or ""):
                    raise FeatureDefError(f"特征 {self.code} 第 {index} 步必须形如 {{'atom': 算子名, 'args': {{...}}}}")

    def describe(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "unit": self.unit,
            "form": "steps" if self.steps else "expr",
            "body": self.steps if self.steps else self.expr,
            "version": self.version,
            "description": self.description,
            "category": self.category,
        }


def _normalize(raw: Any, definition: FeatureDef) -> Any:
    """只允许标量出门：表/序列说明这条定义收尾收错了。"""
    if raw is None or isinstance(raw, (bool, Decimal, int, str)):
        return raw
    if isinstance(raw, float):
        # 内部绝不产生 float；这一步只是把外部混进来的浮点在门口换成 Decimal
        return Decimal(str(raw))
    raise FeatureDefError(
        f"特征 {definition.code} 必须算出标量，实际算出 {type(raw).__name__}；"
        "请用聚合类算子（sum/mean/count/max/…）收尾"
    )


def _reason(frame: Frame, notes: Sequence[str]) -> str:
    if not frame.rows:
        return "明细为空：没有可用的交易记录"
    if frame.missing:
        return f"缺列：{'、'.join(sorted(frame.missing))}（该列在全部交易上都没有值）"
    if notes:
        return "；".join(dict.fromkeys(notes))
    return "按条件过滤后没有可聚合的数据"


def evaluate(definition: FeatureDef, rows: Iterable[Any]) -> tuple[Any, str]:
    """算一条特征，返回 (值, 原因)；算不出来时值必为 None 且原因为空串以外的说明。"""
    frame = Frame(list(rows), origin=f"{definition.code} 的帧")
    notes: list[str] = []
    try:
        if definition.steps is not None:
            raw = run_steps(definition.steps, frame=frame, notes=notes)
        else:
            raw = expr_mod.eval_expr(definition.expr or "", frame, notes=notes)
    except expr_mod.ExprError as exc:
        raise FeatureDefError(f"特征 {definition.code} 的表达式有误：{exc}") from None
    except OperatorError as exc:
        raise FeatureDefError(f"特征 {definition.code} 的计算描述有误：{exc}") from None
    value = _normalize(raw, definition)
    return value, ("" if value is not None else _reason(frame, notes))


def compute(defs: Iterable[FeatureDef], statement: Statement, *, version: str = "1.0") -> FeatureSet:
    """按定义逐条算特征；一条算不出来不影响其余，缺什么写在它自己的 reason 里。"""
    rows = list(getattr(statement, "rows", None) or [])
    records: list[dict[str, Any]] = []
    for definition in defs:
        value, reason = evaluate(definition, rows)
        records.append({
            "code": definition.code,
            "name": definition.name,
            "value": value,
            "unit": definition.unit,
            "reason": reason,
            "version": definition.version,
        })
    return FeatureSet(records=records, schema=dict(SCHEMA), version=version)


NIGHT = "(hour>=22) or (hour<=5)"
OUT = "direction=='out'"
IN_ = "direction=='in'"


BUILTIN_FEATURES: tuple[FeatureDef, ...] = (
    FeatureDef(code="f_txn_count", name="交易笔数", unit="笔",
               expr="count()",
               description="全部明细的行数；也是后面各项占比的分母。"),
    FeatureDef(code="f_in_total", name="入账总额", unit="元",
               expr="sum(amount, where=direction=='in')",
               description="收付方向为入账的金额合计。"),
    FeatureDef(code="f_out_total", name="出账总额", unit="元",
               expr="sum(amount, where=direction=='out')",
               description="收付方向为出账的金额合计。"),
    FeatureDef(code="f_net_flow", name="净流入", unit="元",
               expr="sum(amount, where=direction=='in') - sum(amount, where=direction=='out')",
               description="入账减出账，看这段时间资金是净进还是净出。"),
    FeatureDef(code="f_in_out_ratio", name="收支比", unit="比例",
               expr="if_else(sum(amount, where=direction=='in') == 0, none, "
                    "sum(amount, where=direction=='out') / sum(amount, where=direction=='in'))",
               description="出账/入账；没有入账时无意义，得 None 而不是 0。"),
    FeatureDef(code="f_out_mean", name="出账均值", unit="元",
               expr="mean(amount, where=direction=='out')",
               description="单笔出账的平均金额。"),
    FeatureDef(code="f_out_median", name="出账中位数", unit="元",
               expr="median(amount, where=direction=='out')",
               description="比均值抗极端值，用来判断「均值是不是被一两笔大额抬起来的」。"),
    FeatureDef(code="f_out_std", name="出账标准差", unit="元",
               expr="std(amount, where=direction=='out')",
               description="出账金额的波动幅度；少于 2 笔得 None。"),
    FeatureDef(code="f_out_cv", name="出账变异系数", unit="比例",
               expr="cv(amount, where=direction=='out')",
               description="标准差/均值，跨客户可比地看金额稳不稳。"),
    FeatureDef(code="f_out_max", name="单笔最大出账", unit="元",
               expr="max(amount, where=direction=='out')",
               description="最大的一笔出账。"),
    FeatureDef(code="f_night_count", name="夜间交易笔数", unit="笔",
               expr=f"count(where={NIGHT})",
               description="22:00-05:59 之间的交易笔数；依赖 trade_time，缺时间列则为 None。"),
    FeatureDef(code="f_night_out_total", name="夜间出账总额", unit="元",
               steps=[{"atom": "filter_direction", "args": {"value": "out"}},
                      {"atom": "hour_band", "args": {"band": "night"}},
                      {"atom": "sum", "args": {"signed": False}}],
               description="步骤形态示例：先筛出账、再筛夜间、最后按金额绝对值求和。"),
    FeatureDef(code="f_night_out_share", name="夜间出账占比", unit="比例",
               expr=f"sum(amount, where=({OUT}) and ({NIGHT})) / sum(amount, where={OUT})",
               description="夜间出账额占全部出账额的比例。"),
    FeatureDef(code="f_counterparty_count", name="交易对手方数", unit="个",
               expr="distinct_count(counterparty_name)",
               description="去重后的对手方个数（忽略空值）。"),
    FeatureDef(code="f_top_counterparty_share", name="最大对手方金额占比", unit="比例",
               expr="max(sum_by(counterparty_name, signed=false)) / sum(amount)",
               description="单个对手方的金额占比上限；越高说明资金越集中。"),
    FeatureDef(code="f_balance_min", name="期间最低余额", unit="元",
               expr="min(balance)",
               description="余额列的最小值；账单没有余额列时为 None（缺列）。"),
    FeatureDef(code="f_balance_last", name="期末余额", unit="元",
               expr="last(balance)",
               description="按行序最后一个非空余额，用来和下一期期初对账。"),
    FeatureDef(code="f_month_count", name="覆盖月份数", unit="个",
               expr="count(monthly())",
               description="流水覆盖的自然月个数。"),
    FeatureDef(code="f_month_out_max", name="单月最高出账", unit="元",
               steps=[{"atom": "filter_direction", "args": {"value": "out"}},
                      {"atom": "monthly_agg", "args": {"mode": "sum", "signed": False}},
                      {"atom": "max"}],
               description="按月汇总出账后取最高的一个月。"),
    FeatureDef(code="f_month_out_cv", name="月度出账波动", unit="比例",
               steps=[{"atom": "filter_direction", "args": {"value": "out"}},
                      {"atom": "monthly_agg", "args": {"mode": "sum", "signed": False}},
                      {"atom": "cv"}],
               description="月度出账额的变异系数，看现金流是否稳定。"),
    FeatureDef(code="f_span_days", name="账期覆盖天数", unit="天",
               expr="span_days()",
               description="最大交易日减最小交易日加 1。"),
    FeatureDef(code="f_weekend_out_total", name="周末出账总额", unit="元",
               expr=f"sum(amount, where=({OUT}) and dow>=5)",
               description="周六周日的出账合计（dow 取 5/6）。"),
    FeatureDef(code="f_recent90_out_total", name="近90天出账总额", unit="元",
               steps=[{"atom": "within_days", "args": {"days": 90}},
                      {"atom": "filter_direction", "args": {"value": "out"}},
                      {"atom": "sum", "args": {"signed": False}}],
               description="以本帧最大交易日为锚点回溯 90 天的出账合计。"),
    FeatureDef(code="f_out_pct_change_max", name="单笔最大跳变", unit="比例",
               expr="max(pct_change(amount))",
               category="鲁棒与异常",
               description="相邻两笔金额变化率的最大值，用来发现单笔跳变。"),
    # ---- 新增信贷风控衍生特征（Lab 演示与复用） ----
    FeatureDef(code="f_robust_outlier_count", name="鲁棒异常大额出账笔数", unit="笔",
               expr="count(where=(direction=='out') and (robust_zscore() > 3.5))",
               category="鲁棒与异常",
               description="基于中位数与 MAD 稳健 Z 分数识别长尾异常出账笔数，比标准差更抗极端偏态。"),
    FeatureDef(code="f_amount_iqr_ratio", name="金额四分位离散比", unit="比例",
               expr="iqr() / median(amount)",
               category="鲁棒与异常",
               description="金额四分位距与中位数之比，用于刻画常规流水波动幅度的稳健程度。"),
    FeatureDef(code="f_weekend_out_share", name="周末出账金额占比", unit="比例",
               expr=f"sum(amount, where=({OUT}) and dow>=5) / sum(amount, where={OUT})",
               category="时间行为",
               description="周六、周日出账金额占总出账额的比例，辅助识别非工作日消费与夜间高频。"),
    FeatureDef(code="f_night_large_out_count", name="夜间高分位大额出账笔数", unit="笔",
               expr=f"count(where=({OUT}) and in_hours('22:00','05:59') and (pct_rank() >= 0.9))",
               category="时间行为",
               description="同时满足夜间时段（22:00-05:59）与全账期金额前 10% 分位的交叉高危出账笔数。"),
    FeatureDef(code="f_salary_in_share", name="工资入账占比", unit="比例",
               expr=f"sum(amount, where=({IN_}) and in_lexicon(name='salary')) / sum(amount, where={IN_})",
               category="收入与偿债",
               description="摘要命中工资薪酬词库的入账金额占总入账比例，评估稳定代发薪资成色。"),
    FeatureDef(code="f_online_loan_out_share", name="网贷小贷出账占比", unit="比例",
               expr=f"sum(amount, where=({OUT}) and in_lexicon(name='online_loan')) / sum(amount, where={OUT})",
               category="收入与偿债",
               description="摘要或附言命中网贷/消金平台词库的出账金额占总出账比例，揭示隐性共债压力。"),
    FeatureDef(code="f_debt_service_ratio", name="广义偿债支出收入比", unit="比例",
               expr=f"sum(amount, where=({OUT}) and (in_lexicon(name='loan_repayment') or in_lexicon(name='credit_card'))) / sum(amount, where={IN_})",
               category="收入与偿债",
               description="贷款还款与信用卡还款合计支出占当期总入账比，用于横向对照核心 DTI 指标。"),
    FeatureDef(code="f_third_party_flow_share", name="三方支付流转占比", unit="比例",
               expr="sum(amount, where=in_lexicon(name='third_party')) / sum(amount)",
               category="收入与偿债",
               description="经由微信、支付宝等第三方支付渠道收付的金额占全部流水总额的比例。"),
    FeatureDef(code="f_high_risk_hits", name="涉赌与虚拟币高危命中笔数", unit="笔",
               expr="count(where=in_lexicon(name='gambling') or in_lexicon(name='crypto'))",
               category="黑灰高危行为",
               description="全文摘要命中博彩或虚拟货币词库的黑灰行为硬触发笔数。"),
    FeatureDef(code="f_cash_out_share", name="现金支取占比", unit="比例",
               expr=f"sum(amount, where=({OUT}) and in_lexicon(name='cash')) / sum(amount, where={OUT})",
               category="黑灰高危行为",
               description="ATM/柜面取现等脱离可追踪清算链路的出账金额占总出账额比例。"),
    FeatureDef(code="f_counterparty_hhi", name="对手方金额赫芬达尔指数", unit="指数",
               expr="share_square_sum()",
               category="集中度与稳定性",
               description="按交易对手方金额占比平方求和（HHI），越接近 1 表示资金往来越集中于单一对手。"),
    FeatureDef(code="f_top3_counterparty_share", name="前三大对手方金额占比", unit="比例",
               expr="top_share(k=3)",
               category="集中度与稳定性",
               description="前 3 大交易对手方金额占总流水的比重，用于识别空壳走账或单一资金池。"),
    FeatureDef(code="f_overdraft_days", name="日终余额透支天数", unit="天",
               expr="overdraft_days()",
               category="集中度与稳定性",
               description="统计期间内日终余额小于 0 的天数，反映短期流动性失血风险。"),
    FeatureDef(code="f_month_end_balance_slope", name="月末余额走势斜率", unit="元/月",
               expr="slope(month_end_balances())",
               category="集中度与稳定性",
               description="对各自然月末余额做最小二乘线性回归的斜率，正值为蓄水累积、负值为持续消耗。"),
    FeatureDef(code="f_recent30_flow_ratio", name="近30天资金活跃集中度", unit="比例",
               expr="sum(within_days(days=30), signed=false) / sum(signed=false)",
               category="时间行为",
               description="最近 30 天内流水发生额占全账期总发生额比例，识别突击刷流水或近期异常放量。"),
    # ---- 第二批演示型衍生特征（覆盖入账稳定性、金额形态、流动性） ----
    FeatureDef(code="f_in_mean", name="入账均值", unit="元",
               expr="mean(amount, where=direction=='in')",
               category="收入与偿债",
               description="单笔入账的平均金额；与出账均值对比可看出「进小出大」的资金消耗形态。"),
    FeatureDef(code="f_in_cv", name="入账变异系数", unit="比例",
               expr="cv(amount, where=direction=='in')",
               category="收入与偿债",
               description="入账金额的标准差/均值；越低说明收入越规律（工资型），越高越像经营或临时进账。"),
    FeatureDef(code="f_month_in_cv", name="月度入账波动", unit="比例",
               steps=[{"atom": "filter_direction", "args": {"value": "in"}},
                      {"atom": "monthly_agg", "args": {"mode": "sum", "signed": False}},
                      {"atom": "cv"}],
               category="收入与偿债",
               description="按月汇总入账后再算变异系数，跨月看收入稳定性，比单笔口径更贴近还款能力。"),
    FeatureDef(code="f_round_amount_share", name="整数金额占比", unit="比例",
               expr="count(where=(direction=='out') and (round(amount) == amount)) / count(where=direction=='out')",
               category="鲁棒与异常",
               description="金额恰好是整数的出账笔数占比；异常偏高常见于凑整走账、刷单或人工造流水。"),
    FeatureDef(code="f_large_out_share", name="大额出账金额占比", unit="比例",
               expr="sum(amount, where=(direction=='out') and (amount >= 20000), signed=false) / sum(amount, where=direction=='out', signed=false)",
               category="集中度与稳定性",
               description="单笔 2 万元以上的出账合计占全部出账的比例，衡量资金流出是否集中在少数大额交易上。"),
    FeatureDef(code="f_idle_months", name="无交易月数", unit="月",
               expr="idle_months()",
               category="时间行为",
               description="账期覆盖范围内没有任何交易的月份数；休眠期多说明这份流水并非日常主账户。"),
    FeatureDef(code="f_balance_delta_rate", name="期末较期初余额变化率", unit="比例",
               expr="last(balance) / first(balance) - 1",
               category="集中度与稳定性",
               description="期末余额相对期初的变化比例；正值为净积累、负值为净消耗，辅助判断资金是否在流出。"),
)


def builtin_features() -> tuple[FeatureDef, ...]:
    return BUILTIN_FEATURES
