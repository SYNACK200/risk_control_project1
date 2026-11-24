"""数学与微积分算子：把表达式从「加减乘除」扩到「乘方开方、对数指数、积分微分」。

为什么要单独一个模块：特征引擎的算子表已经很满，数学函数是一族独立的、可机械验证的东西，
放一起改起来容易互相踩。注册表是全局的，所以放在哪个文件不影响可用性。

离散序列上的微积分口径（写死在这里，避免各处自己解释）：
- 积分 = 累加（cumsum）。离散点上没有连续积分，累加是唯一不引入假设的做法。
- 微分 = 相邻差分（diff），可指定阶数；二阶就是「变化率的变化率」。
- 两者互逆（先 diff 再 cumsum 会丢掉首项，这是离散情形的固有损耗，不补 0 假装没丢）。
"""
from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation

from .operators import (
    NUMERIC, OperatorError, Series, _to_decimal, operator,
)

UNIT_PLAIN = "无量纲"


def _scalar(value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Series):
        raise OperatorError("这个位置需要单个数值，收到一列值；请用聚合算子（sum/mean/…）先收成标量")
    return _to_decimal(value)


def _series(value) -> list[Decimal | None]:
    if isinstance(value, Series):
        return [_to_decimal(v) for v in value.values]
    raise OperatorError("这个算子需要一列值（序列），例如 monthly_values(...) 或 daily_balances()")


@operator("pow", family=NUMERIC, kind="scalar", unit=UNIT_PLAIN,
          detail="乘方；指数可以是小数。负数底数配非整数指数时返回 None。",
          params=[{"name": "base", "type": "number"}, {"name": "exp", "type": "number", "default": 2}])
def op_pow(x, exp=2, notes=None):
    left = _scalar(x)
    right = _scalar(exp)
    if left is None or right is None:
        return None
    try:
        return Decimal(str(float(left) ** float(right)))
    except (InvalidOperation, ValueError, OverflowError):
        return None


@operator("sqrt", family=NUMERIC, kind="scalar", unit=UNIT_PLAIN,
          detail="开平方；负数返回 None（不返回复数，也不静默取绝对值）。")
def op_sqrt(x, notes=None):
    value = _scalar(x)
    if value is None:
        return None
    if value < 0:
        return None
    return Decimal(str(math.sqrt(float(value))))


@operator("exp", family=NUMERIC, kind="scalar", unit=UNIT_PLAIN, detail="自然指数 e^x。")
def op_exp(x, notes=None):
    value = _scalar(x)
    if value is None:
        return None
    try:
        return Decimal(str(math.exp(float(value))))
    except OverflowError:
        return None


@operator("ln", family=NUMERIC, kind="scalar", unit=UNIT_PLAIN, detail="自然对数；非正数返回 None。")
def op_ln(x, notes=None):
    value = _scalar(x)
    if value is None or value <= 0:
        return None
    return Decimal(str(math.log(float(value))))


@operator("log10", family=NUMERIC, kind="scalar", unit=UNIT_PLAIN, detail="以 10 为底的对数；非正数返回 None。")
def op_log10(x, notes=None):
    value = _scalar(x)
    if value is None or value <= 0:
        return None
    return Decimal(str(math.log10(float(value))))


@operator("floor", family=NUMERIC, kind="scalar", unit=UNIT_PLAIN, detail="向下取整。")
def op_floor(x, notes=None):
    value = _scalar(x)
    return None if value is None else Decimal(math.floor(value))


@operator("ceil", family=NUMERIC, kind="scalar", unit=UNIT_PLAIN, detail="向上取整。")
def op_ceil(x, notes=None):
    value = _scalar(x)
    return None if value is None else Decimal(math.ceil(value))


@operator("round", family=NUMERIC, kind="scalar", unit=UNIT_PLAIN,
          detail="四舍五入到指定小数位。",
          params=[{"name": "digits", "type": "int", "default": 2}])
def op_round(x, digits=2, notes=None):
    value = _scalar(x)
    if value is None:
        return None
    return Decimal(round(value, int(digits)))


@operator("integrate", family=NUMERIC, kind="series", unit=UNIT_PLAIN,
          detail="对序列做累加（离散积分）：第 i 项 = 前 i 项之和。")
def op_integrate(x, notes=None):
    values = _series(x)
    total = Decimal(0)
    out: list[Decimal | None] = []
    for value in values:
        if value is None:
            out.append(None)
            continue
        total += value
        out.append(total)
    return Series(name="integral", values=out, frame=None)


@operator("derivative", family=NUMERIC, kind="series", unit=UNIT_PLAIN,
          detail="对序列做差分（离散微分），可指定阶数；首项因缺前一项为 None。",
          params=[{"name": "order", "type": "int", "default": 1}])
def op_derivative(x, order=1, notes=None):
    values = _series(x)
    current = list(values)
    for _ in range(max(1, int(order))):
        nxt: list[Decimal | None] = [None]
        for prev, cur in zip(current, current[1:]):
            nxt.append(None if prev is None or cur is None else cur - prev)
        current = nxt
    return Series(name="derivative", values=current, frame=None)
