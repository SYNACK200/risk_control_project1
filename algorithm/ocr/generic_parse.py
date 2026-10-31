"""表头驱动的通用解析：不依赖模板，用于「未知银行/未知版式」的默认兜底。

思路：先找表头行（含日期、金额、余额等关键词），按表头词的 x 位置切出列，
再把后续行按坐标落列；旋转 90° 的页面按「竖排」处理。识别不出的列不猜，写进 warnings。
"""
from __future__ import annotations

import re

import pymupdf

from decimal import Decimal

from .models import ParseResult, Transaction
from .parse import parse_date, parse_direction, parse_money

COMPACT_DATE = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")


def _date(text: str) -> str | None:
    """支持 2021-05-13 / 2021/05/13 / 20210513 三种写法。"""
    found = parse_date(text)
    if found:
        return found
    match = COMPACT_DATE.search(text or "")
    if match:
        year, month, day = (int(g) for g in match.groups())
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    return None

HEADER_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("txn_date", ("交易日期", "记账日期", "交易时间", "日期", "交易日")),
    ("summary", ("摘要", "交易摘要", "用途", "交易说明")),
    ("income", ("收入金额", "收入", "贷方发生额", "存入金额")),
    ("expense", ("支出金额", "支出", "借方发生额", "支取金额")),
    ("amount", ("交易金额", "发生额", "本币金额", "金额")),
    ("balance", ("余额", "账户余额", "本币余额", "联机余额")),
    ("counterparty", ("对方账号", "对方户名", "对方名称", "交易对手", "对方")),
    ("channel", ("渠道", "交易地点/渠道", "交易地点", "网点")),
)


def _lines(page) -> list[dict]:
    """把页面拆成「行」：横排按 y 聚，竖排（旋转 90）按 x 聚。"""
    data = page.get_text("dict")
    spans = []
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            if not text:
                continue
            x0, y0, x1, y1 = line["bbox"]
            spans.append({"text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                          "vertical": (y1 - y0) > (x1 - x0) * 1.6})
    if not spans:
        return []
    vertical = sum(1 for s in spans if s["vertical"]) > len(spans) / 2
    buckets: dict[int, list[dict]] = {}
    for span in spans:
        key = int(round((span["x0"] if vertical else span["y0"]) / 4.0))
        buckets.setdefault(key, []).append(span)
    rows = []
    for key in sorted(buckets):
        group = buckets[key]
        if vertical:
            group.sort(key=lambda s: s["y0"])
        else:
            group.sort(key=lambda s: s["x0"])
        text = " ".join(s["text"] for s in group)
        rows.append({"text": text, "spans": group, "vertical": vertical})
    return rows


def _header_map(row: dict) -> dict[str, float]:
    """在候选行里找表头：返回 field -> x 中心。命中不足 2 个字段视为不是表头。"""
    mapping: dict[str, float] = {}
    for span in row["spans"]:
        text = span["text"].replace(" ", "")
        for field, aliases in HEADER_ALIASES:
            if field in mapping:
                continue
            if any(alias in text for alias in aliases):
                mapping[field] = (span["x0"] + span["x1"]) / 2 if not row["vertical"] else (span["y0"] + span["y1"]) / 2
                break
    return mapping if len(mapping) >= 2 else {}


def _assign(row: dict, header: dict[str, float]) -> dict[str, str]:
    """按列中心把一行里的片段分配到字段。"""
    cells: dict[str, list[str]] = {}
    centers = sorted(header.items(), key=lambda item: item[1])
    for span in row["spans"]:
        center = (span["x0"] + span["x1"]) / 2 if not row["vertical"] else (span["y0"] + span["y1"]) / 2
        nearest = min(centers, key=lambda item: abs(item[1] - center))
        cells.setdefault(nearest[0], []).append(span["text"])
    return {field: " ".join(values) for field, values in cells.items()}


def parse_generic(raw: bytes, max_pages: int | None = None) -> tuple[ParseResult, list[str]]:
    warnings: list[str] = []
    doc = pymupdf.open(stream=raw, filetype="pdf")
    pages = doc.page_count
    limit = pages if max_pages is None else min(pages, max_pages)
    transactions: list[Transaction] = []
    headers_found = 0
    for page_index in range(limit):
        page = doc[page_index]
        rows = _lines(page)
        header: dict[str, float] = {}
        header_at = -1
        for index, row in enumerate(rows):
            candidate = _header_map(row)
            if candidate:
                header = candidate
                header_at = index
                headers_found += 1
                break
        if header_at < 0:
            continue
        for row in rows[header_at + 1:]:
            cells = _assign(row, header)
            day = _date(cells.get("txn_date", ""))
            if day is None:
                continue
            income = parse_money(cells.get("income", "")) if cells.get("income") else None
            expense = parse_money(cells.get("expense", "")) if cells.get("expense") else None
            raw_amount = cells.get("amount", "")
            amount = income if income is not None else expense
            if amount is None and raw_amount:
                amount = parse_money(raw_amount)
            if amount is None:
                continue
            direction = "in" if income is not None else "out" if expense is not None else None
            if direction is None:
                direction = parse_direction(cells.get("summary", "") + " " + raw_amount, amount)
            negative = "-" in (raw_amount or "") or raw_amount.strip().startswith("−")
            if direction is None and negative:
                direction = "out"
            if direction is None:
                prev = next((t for t in reversed(transactions) if t.balance is not None), None)
                if prev is not None and balance is not None:
                    delta = balance - prev.balance
                    tolerance = abs(amount) * Decimal("0.02") + Decimal("0.01")
                    if abs(abs(delta) - abs(amount)) <= tolerance:
                        direction = "in" if delta > 0 else "out"
            balance = parse_money(cells.get("balance", "")) if cells.get("balance") else None
            summary = cells.get("summary") or None
            counterparty = cells.get("counterparty") or None
            transactions.append(Transaction(
                page_no=page_index + 1,
                row_no=len(transactions) + 1,
                txn_date=day,
                summary=summary,
                counterparty_name=counterparty,
                direction=direction,
                amount=abs(amount) if amount is not None else None,
                balance=balance,
            ))
    doc.close()
    if headers_found == 0:
        warnings.append("通用解析：未找到表头行（含日期/金额/余额的列名），无法按列抽取")
    if not transactions:
        warnings.append("通用解析：未抽取到任何明细行")
    warnings.append(f"通用解析：共扫描 {limit} 页，找到表头 {headers_found} 处，抽取明细 {len(transactions)} 笔")
    result = ParseResult(
        transactions=transactions,
        page_summaries=[],
        footer_count=None,
        page_count=pages,
        warnings=warnings,
    )
    return result, warnings

