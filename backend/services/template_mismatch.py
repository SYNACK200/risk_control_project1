"""判断「这份流水跟匹配到的模板差太多」——决定要不要提示用户走临时模板。

用户 2026-11-07 的定义：
  临时模板不入库，只针对这一份流水。
  触发条件不是用户主动想用，而是系统先匹配到某个模板、但发现实际文件和它差太远。

所以这里只做一件事：给出一组信号，说明「当前模板可能不适用」。
不自动修、不自动换模板，把判断交给用户。
"""
from __future__ import annotations

import re
from decimal import Decimal

FOOTER_RE = re.compile(r"本页交易笔数[：:\s]*(\d+)")


def detect_mismatch(result: dict, template_used: dict | None) -> dict | None:
    """检测模板不匹配。返回 None 表示没有明显问题。

    result: analysis.run_analysis 的返回值（transactions / footer_count 都在里面）
     Signals（任一命中即认为可疑）：
      1. 覆盖率低：解析笔数远少于页脚声明
      2. 关键字段空：金额或日期大面积为空
      3. 余额链断裂比例高：余额不等于「上一笔余额 ± 本笔金额」的行占比过高
         —— 列错位最典型的表现就是这个
    """
    if template_used is None:
        return None

    txns = list(result.get("transactions") or [])
    if not txns:
        return {
            "suspect": True,
            "reasons": ["没解析出任何交易，模板的表头/列可能对不上"],
            "signals": {},
        }

    reasons: list[str] = []
    signals: dict = {}

    # 1) 覆盖率
    footer = result.get("footer_count")
    if footer and footer >= 10:
        cov = round(len(txns) / footer, 4)
        signals["coverage"] = cov
        if cov < 0.8:
            reasons.append(f"只解析出 {len(txns)} 笔，文件声明 {footer} 笔（覆盖率 {cov:.0%}）")

    # 2) 关键字段空值率
    def _amt(t):
        return t.get("amount") if isinstance(t, dict) else getattr(t, "amount", None)

    def _date(t):
        return t.get("txn_date") if isinstance(t, dict) else getattr(t, "txn_date", None)

    def _bal(t):
        return t.get("balance") if isinstance(t, dict) else getattr(t, "balance", None)

    no_amount = sum(1 for t in txns if _amt(t) is None)
    no_date = sum(1 for t in txns if not _date(t))
    signals["amount_missing_ratio"] = round(no_amount / len(txns), 4)
    signals["date_missing_ratio"] = round(no_date / len(txns), 4)
    if no_amount / len(txns) > 0.2:
        reasons.append(f"{no_amount}/{len(txns)} 笔没有金额，金额列可能没对上")
    if no_date / len(txns) > 0.2:
        reasons.append(f"{no_date}/{len(txns)} 笔没有日期，日期列可能没对上")

    # 3) 余额链断裂
    breaks = 0
    checked = 0
    prev = None
    for t in txns:
        bal = _bal(t)
        amt = _amt(t)
        if bal is None or amt is None:
            # 余额缺的行不参与链条判断，但也不要把字符串塞进 prev
            if bal is not None:
                try:
                    prev = Decimal(str(bal))
                except Exception:  # noqa: BLE001
                    pass
            continue
        try:
            bal_d = Decimal(str(bal))
            amt_d = Decimal(str(amt))
        except Exception:  # noqa: BLE001
            continue
        if prev is not None:
            checked += 1
            expect = prev + amt_d
            if abs(expect - bal_d) > Decimal("0.02"):
                breaks += 1
        prev = bal_d
    if checked >= 5:
        ratio = round(breaks / checked, 4)
        signals["balance_break_ratio"] = ratio
        if ratio > 0.3:
            reasons.append(f"余额链有 {breaks}/{checked} 处接不上（{ratio:.0%}），列大概率错位了")

    if not reasons:
        return None
    return {"suspect": True, "reasons": reasons, "signals": signals,
            "template": template_used.get("bank_code") if template_used else None}