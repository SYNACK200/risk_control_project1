"""识别结果自检：把「解析结果」与「原件文字」交叉核对，给出可量化的把握程度。

不追求证明「无误」，而是回答三个问题：
1) 每个解析出来的值，能不能在原件里找到（回查率）；
2) 两个抽取引擎的读数是否一致（跨引擎一致率）；
3) 行数、余额、方向这些结构性关系是否闭合。
"""
from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

import pdfplumber
import pymupdf

NUM_TOKEN = re.compile(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|[+-]?\d+(?:\.\d{1,2})?")


@dataclass
class SelfCheckItem:
    code: str
    name: str
    status: str  # pass / limited / inconsistent
    detail: str
    ratio: float | None = None


@dataclass
class SelfCheckResult:
    status: str
    items: list[SelfCheckItem] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        bad = [i.name for i in self.items if i.status != "pass"]
        return "全部通过" if not bad else "未通过：" + "、".join(bad)


def _norm(text: str) -> str:
    return text.replace(",", "").replace(" ", "").replace("\u3000", "")


def _page_text(raw: bytes) -> list[str]:
    out: list[str] = []
    doc = pymupdf.open(stream=raw, filetype="pdf")
    for i in range(doc.page_count):
        out.append(_norm(doc[i].get_text("text")))
    return out


def _plumber_page_texts(raw: bytes, pages: int) -> list[str]:
    out: list[str] = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages[:pages]:
            words = page.extract_words() or []
            out.append(_norm("".join(w["text"] for w in words)))
    return out


def _plumber_numbers(raw: bytes, limit: int = 3) -> Counter:
    counter: Counter = Counter()
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages[:limit]:
            for w in page.extract_words() or []:
                for tok in NUM_TOKEN.findall(w["text"]):
                    counter[_norm(tok).lstrip("+")] += 1
    return counter


def _pymupdf_numbers(texts: list[str], limit: int = 3) -> Counter:
    counter: Counter = Counter()
    for t in texts[:limit]:
        for tok in NUM_TOKEN.findall(t):
            counter[_norm(tok).lstrip("+")] += 1
    return counter


def run_self_check(
    raw: bytes,
    transactions: list,
    footer_count: int | None = None,
    preread: object | None = None,
) -> SelfCheckResult:
    """transactions: 解析结果（需 txn_date / amount / balance / page_no 属性）。"""
    items: list[SelfCheckItem] = []
    samples: list[str] = []
    texts = _page_text(raw)

    total = len(transactions)
    if total == 0:
        return SelfCheckResult("inconsistent", [SelfCheckItem("S0", "明细存在", "inconsistent", "未解析到任何明细")])

    def pages_of(i: int) -> str:
        t = transactions[i]
        idx = (getattr(t, "page_no", None) or 1) - 1
        idx = min(max(idx, 0), len(texts) - 1)
        return texts[idx]

    # S1 金额回查：解析值必须能在对应页原文里找到
    hit_amt = 0
    for i, t in enumerate(transactions):
        amt = getattr(t, "amount", None)
        if amt is None:
            continue
        token = _norm(format(Decimal(str(amt)), "f")).lstrip("+")
        if token in pages_of(i):
            hit_amt += 1
        elif len(samples) < 5:
            samples.append(f"第 {i+1} 笔金额 {token} 未在原文找到")
    ratio_amt = hit_amt / total
    items.append(SelfCheckItem("S1", "金额回查", "pass" if ratio_amt >= 0.99 else "inconsistent",
                               f"{hit_amt}/{total} 笔金额能在原文定位", round(ratio_amt, 4)))

    # S2 日期回查
    hit_date = sum(1 for i, t in enumerate(transactions)
                   if getattr(t, "txn_date", None) and str(t.txn_date) in pages_of(i))
    ratio_date = hit_date / total
    items.append(SelfCheckItem("S2", "日期回查", "pass" if ratio_date >= 0.99 else "limited",
                               f"{hit_date}/{total} 笔日期能在原文定位", round(ratio_date, 4)))

    # S3 余额回查
    hit_bal = sum(1 for i, t in enumerate(transactions)
                  if getattr(t, "balance", None) is not None
                  and _norm(format(Decimal(str(t.balance)), "f")) in pages_of(i))
    ratio_bal = hit_bal / total
    items.append(SelfCheckItem("S3", "余额回查", "pass" if ratio_bal >= 0.99 else "limited",
                               f"{hit_bal}/{total} 笔余额能在原文定位", round(ratio_bal, 4)))

    # S4 跨引擎一致：同一笔金额在两个引擎的文本里都能找到（token 级比对会被切分差异干扰）
    plumber_pages = _plumber_page_texts(raw, len(texts))
    both = 0
    for i, t in enumerate(transactions):
        amt = getattr(t, "amount", None)
        if amt is None:
            continue
        token = _norm(format(Decimal(str(amt)), "f")).lstrip("+")
        if token in pages_of(i) and token in plumber_pages[min(max((getattr(t, "page_no", None) or 1) - 1, 0), len(plumber_pages) - 1)]:
            both += 1
    ratio_engine = both / total
    items.append(SelfCheckItem("S4", "跨引擎一致",
                               "pass" if ratio_engine >= 0.99 else "limited" if ratio_engine >= 0.9 else "inconsistent",
                               f"{both}/{total} 笔金额在两个引擎文本中均可定位", round(ratio_engine, 4)))

    # S5 行数守恒
    if footer_count is None:
        items.append(SelfCheckItem("S5", "行数守恒", "limited", "文件未声明总笔数，无法核对"))
    else:
        ok = footer_count == total
        items.append(SelfCheckItem("S5", "行数守恒", "pass" if ok else "inconsistent",
                                   f"声明 {footer_count} 笔 vs 解析 {total} 笔"))

    # S6 余额链：方向已知时才推导，未知则跳过（方向缺失是另一条 S7 的问题）
    breaks, skipped = 0, 0
    prev = None
    for t in transactions:
        bal, amt, direction = getattr(t, "balance", None), getattr(t, "amount", None), getattr(t, "direction", None)
        if bal is None or amt is None or direction not in ("in", "out"):
            skipped += 1
            prev = None
            continue
        if prev is not None:
            diff = Decimal(str(bal)) - Decimal(str(prev))
            sign = 1 if direction == "in" else -1
            if abs(diff - sign * Decimal(str(amt))) > Decimal("0.01"):
                breaks += 1
                if len(samples) < 8:
                    samples.append(f"余额链断点：余额 {prev}→{bal}，金额 {amt}（{direction}）")
        prev = bal
    items.append(SelfCheckItem("S6", "余额链闭合", "pass" if breaks == 0 else "inconsistent",
                               f"{breaks} 处不符；{skipped} 笔因方向/余额缺失跳过"))

    # S7 方向与符号一致
    mismatch = 0
    for t in transactions:
        d, s = getattr(t, "direction", None), getattr(t, "direction_source", None)
        if d not in ("in", "out"):
            mismatch += 1
    items.append(SelfCheckItem("S7", "方向完整", "pass" if mismatch == 0 else "limited",
                               f"{mismatch} 笔方向缺失"))

    items.append(_preread_item(preread, transactions))
    bad = [i for i in items if i.status == "inconsistent"]
    status = "inconsistent" if bad else ("limited" if any(i.status == "limited" for i in items) else "pass")
    return SelfCheckResult(status, items, samples)


def _preread_item(preread: object | None, transactions: list) -> SelfCheckItem:
    """S8：预读（不看模板）与模板解析是否互相印证。"""
    if preread is None:
        return SelfCheckItem("S8", "预读一致性", "limited", "未执行预读取，无法互证")
    rows = int(getattr(preread, "txn_like_rows", 0) or 0)
    dates_hit = int(getattr(preread, "date_hits", 0) or 0)
    total = len(transactions)
    parsed_start = _min_date(transactions)
    parsed_end = _max_date(transactions)
    p_start = getattr(preread, "period_start", None)
    p_end = getattr(preread, "period_end", None)
    reasons: list[str] = []
    status = "pass"
    if rows > 0 and total > 0:
        tolerance = max(3, int(round(max(rows, total) * 0.1)))
        if abs(rows - total) > tolerance:
            status = "limited"
            if dates_hit >= total * 0.5:
                reasons.append(
                    f"版式旋转或多列，预读按行只识别出 {rows} 行（日期出现 {dates_hit} 次），"
                    "行数不能独立验证"
                )
            else:
                reasons.append(f"预读疑似 {rows} 行，模板解析 {total} 笔，差 {abs(rows - total)} 笔超出容差")
    elif rows == 0:
        status = "limited"
        reasons.append("预读未识别出明细行（可能无文字层或版式特殊）")
    if p_start and parsed_start and p_start > parsed_start:
        status = "limited" if status == "pass" else status
        reasons.append(f"预读起始日期 {p_start} 晚于解析首笔 {parsed_start}")
    if p_end and parsed_end and p_end < parsed_end:
        status = "limited" if status == "pass" else status
        reasons.append(f"预读结束日期 {p_end} 早于解析末笔 {parsed_end}")
    detail = (
        f"预读 {rows} 行（日期出现 {dates_hit} 次）/ 解析 {total} 笔；"
        f"预读期间 {p_start or '—'}~{p_end or '—'} / 解析 {parsed_start or '—'}~{parsed_end or '—'}"
    )
    if reasons:
        detail += "；" + "；".join(reasons)
    return SelfCheckItem("S8", "预读一致性", status, detail)


def _min_date(transactions: list) -> str | None:
    days = [_norm_date(getattr(t, "txn_date", None)) for t in transactions]
    days = [d for d in days if d]
    return min(days) if days else None


def _max_date(transactions: list) -> str | None:
    days = [_norm_date(getattr(t, "txn_date", None)) for t in transactions]
    days = [d for d in days if d]
    return max(days) if days else None


def _norm_date(value: str | None) -> str | None:
    if not value:
        return None
    m = re.search(r"(20\d{2})\D(\d{1,2})\D(\d{1,2})", str(value))
    if not m:
        return None
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
