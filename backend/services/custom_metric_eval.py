"""把自定义指标的计算步骤（steps）真正跑起来。

为什么单独一层：
    自定义指标以前只登记口径文字，不参与计算。现在允许用计算元（atoms）描述步骤，
    这里负责把算法层的 Transaction 转成 atoms 能吃的 TxnView、执行步骤、并把结果
    按统一形状交回报告。失败必须说清哪一步错了，不能悄悄给 null 当成「无数据」。
"""
from __future__ import annotations

from typing import Any


def _to_view(transactions: list[Any]) -> list[dict]:
    """Transaction -> atoms.TxnView 的入参。方向缺失时按金额正负推断。"""
    out: list[dict] = []
    for txn in transactions:
        amount = getattr(txn, "amount", None)
        direction = getattr(txn, "direction", None)
        if direction is None and amount is not None:
            direction = "in" if float(amount) >= 0 else "out"
        out.append({
            "date": getattr(txn, "txn_date", None),
            "amount": float(amount) if amount is not None else None,
            "balance": float(getattr(txn, "balance", 0)) if getattr(txn, "balance", None) is not None else None,
            "direction": direction,
            "counterparty": getattr(txn, "counterparty", None),
            "summary": getattr(txn, "summary", None),
        })
    return out


def evaluate_custom(steps: list | None, transactions: list[Any]) -> dict:
    """执行一个自定义指标，返回 {value, unit, error, steps_used}。"""
    if not steps:
        return {"value": None, "error": "未配置计算步骤", "steps_used": 0}
    try:
        from algorithm.algo.atoms import evaluate

        result = evaluate(steps, _to_view(transactions))
        if isinstance(result, (int, float)):
            value: Any = float(result)
        elif isinstance(result, list):
            value = float(sum(result)) if result and all(
                isinstance(x, (int, float)) for x in result) else None
        elif isinstance(result, dict):
            value = float(sum(v for v in result.values() if isinstance(v, (int, float))))
        else:
            value = None
        return {"value": value, "error": None if value is not None else "结果不是数值，无法作为指标", "steps_used": len(steps)}
    except Exception as exc:  # noqa: BLE001 - 单个指标失败不该拖垮整份报告
        return {"value": None, "error": str(exc)[:120], "steps_used": len(steps)}
