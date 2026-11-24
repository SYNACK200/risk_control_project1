"""模板必需列的判定：一份版式「必须读到的列」到底缺没缺。

为什么单独一个模块：解析侧（报告的限制说明）和模板侧（试跑诊断）都要用同一套判据，
两处各写一遍的结果就是「试跑说齐了、报告说我缺列」这种自相矛盾。

判据按语义而不是按字段名一对一：把金额拆成「收入金额 / 支出金额」的版式，
没有 amount 列也能算出金额与方向。
"""
from __future__ import annotations

# 某个必需列可以由哪些实际标注列满足
SATISFIED_BY: dict[str, set[str]] = {
    "amount": {"amount", "amount_in", "amount_out"},
    "direction": {"direction", "amount_in", "amount_out"},
    "txn_date": {"txn_date", "trade_time"},
    "counterparty": {"counterparty", "counterparty_name"},
    "counterparty_name": {"counterparty_name", "counterparty"},
}


def missing_required(field_map: dict | None, required: list[str] | None) -> list[str]:
    """返回确实缺的必需列（语义满足的不算缺）。"""
    mapped = set((field_map or {}).keys())
    missing = []
    for field in (required or []):
        candidates = SATISFIED_BY.get(field, {field})
        if not (candidates & mapped):
            missing.append(field)
    return missing
