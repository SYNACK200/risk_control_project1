"""自有切行切值：从「版式 + 词」直接产出逐笔明细。

为什么不再借旧解析器：旧解析器的列边界是「表头词中心推算」，一旦表头识别偏了就整列错位；
新版的列边界来自锚点扩散长出来的包络，切值与边界是同一份几何，不会各说各话。

切行口径：以「视觉行」为最小单位，一行里同时有日期和金额才算一笔；
没有日期也没有金额的行，如果紧跟上一条明细，就当作它的续行（摘要换行很常见）。
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from ...core.contracts import ColumnBand, LayoutPlan, Statement, TxnRow, TableRegion
from ..layout.words import PageWords, Word, group_lines

DATE_RE = re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})")
SHORT_DATE_RE = re.compile(r"(\d{2})[-/](\d{1,2})[-/](\d{1,2})")
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?")
MONEY_CLEAN = str.maketrans({"¥": "", "￥": "", "，": "", ",": "", " ": "", "\u00a0": ""})

SUMMARY_NOISE = ("合计", "小计", "本页", "本页合计", "笔数", "页码", "承前页", "过次页")

IN_CHARS = ("收", "入", "贷")
OUT_CHARS = ("支", "出", "借")


def parse_money(text: str) -> Decimal | None:
    value = text.translate(MONEY_CLEAN).strip()
    if not value:
        return None
    negative = value.startswith("-") or value.startswith("−")
    value = value.lstrip("-−")
    if value.count(".") > 1:
        # 千分位被去掉后仍多点：取最后一个点作为小数点
        head, _, tail = value.rpartition(".")
        value = head.replace(".", "") + "." + tail
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return None
    return -amount if negative else amount


def parse_date(text: str) -> str | None:
    match = DATE_RE.search(text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"
    match = SHORT_DATE_RE.search(text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return f"{2000 + year:04d}-{month:02d}-{day:02d}"
    return None


def parse_time(text: str) -> str | None:
    match = TIME_RE.search(text)
    if not match:
        return None
    hour, minute, second = match.group(1), match.group(2), match.group(3) or "00"
    return f"{int(hour):02d}:{int(minute):02d}:{int(second):02d}"


def parse_direction(text: str) -> str | None:
    value = text.strip()
    for char in value:
        if char in IN_CHARS:
            return "in"
        if char in OUT_CHARS:
            return "out"
    return None


def _bounds(region: TableRegion, width: float) -> list[tuple[str, float, float]]:
    out = []
    for column in region.columns:
        left = column.x * width
        out.append((column.field, left, left + column.w * width))
    return out


def _assign(tokens: list[Word], bounds: list[tuple[str, float, float]]) -> dict[str, list[Word]]:
    """把一个 token 归到「横向重叠最多」的那一列；都不重叠时归给最近的列。"""
    cells: dict[str, list[Word]] = {}
    for token in tokens:
        best_field = None
        best_overlap = 0.0
        nearest = None
        nearest_gap = None
        for field, left, right in bounds:
            overlap = min(token.x1, right) - max(token.x0, left)
            if overlap > best_overlap:
                best_overlap, best_field = overlap, field
            center = (left + right) / 2
            gap = abs(token.cx - center)
            if nearest_gap is None or gap < nearest_gap:
                nearest_gap, nearest = gap, field
        field = best_field or nearest
        if field:
            cells.setdefault(field, []).append(token)
    for value in cells.values():
        value.sort(key=lambda w: w.x0)
    return cells


def _text(tokens: list[Word]) -> str:
    return " ".join(token.text for token in tokens).strip()


def _first_money(tokens: list[Word]) -> Decimal | None:
    """一个列格里可能有别的字（微信的「支付方式」就被并进金额列），取第一个能解析的数。"""
    for token in tokens:
        value = parse_money(token.text)
        if value is not None:
            return value
    return None


def _row_from_cells(cells: dict[str, list[Word]], page_no: int, row_no: int) -> TxnRow | None:
    date_text = _text(cells.get("txn_date", []))
    txn_date = parse_date(date_text) if date_text else None
    trade_time = parse_time(date_text) if date_text else None

    direction = parse_direction(_text(cells.get("direction", []))) if cells.get("direction") else None

    amount: Decimal | None = None
    if cells.get("amount_in"):
        amount = _first_money(cells["amount_in"])
        if amount is not None:
            direction = direction or "in"
    if cells.get("amount_out"):
        out_amount = _first_money(cells["amount_out"])
        if out_amount is not None:
            amount, direction = abs(out_amount), direction or "out"
    if amount is None and cells.get("amount"):
        raw = _first_money(cells["amount"])
        if raw is not None:
            amount = abs(raw)
            if raw < 0:
                direction = direction or "out"

    balance = _first_money(cells["balance"]) if cells.get("balance") else None
    if balance is not None and amount is not None and not direction:
        direction = "in" if balance > 0 else direction

    summary = _text(cells.get("summary", [])) or None
    counterparty = _text(cells.get("counterparty") or cells.get("counterparty_name") or []) or None
    reference_no = _text(cells.get("reference_no", [])) or None

    if txn_date is None and amount is None:
        return None
    if summary and any(word in summary for word in SUMMARY_NOISE):
        return None

    extra = {}
    known = {"txn_date", "amount", "amount_in", "amount_out", "balance",
             "summary", "counterparty", "counterparty_name", "direction", "reference_no"}
    for field, tokens in cells.items():
        if field not in known:
            extra[field] = _text(tokens)
    confidences = [token.confidence for tokens in cells.values() for token in tokens]
    return TxnRow(
        txn_date=txn_date,
        trade_time=trade_time,
        reference_no=reference_no,
        direction=direction,
        amount=amount,
        balance=balance,
        summary=summary,
        counterparty_name=counterparty,
        page_no=page_no,
        row_no=row_no,
        confidence=sum(confidences) / len(confidences) if confidences else 1.0,
        extra=extra or None,
    )


def _is_header(cells: dict[str, list[Word]]) -> bool:
    hits = 0
    for tokens in cells.values():
        text = _text(tokens)
        if not text:
            continue
        if any(noise in text for noise in SUMMARY_NOISE):
            return True
        from ..layout import keywords as kw
        if kw.match_header_field(text):
            hits += 1
    return hits >= 2


def read_statement(pages: list[PageWords], plan: LayoutPlan) -> Statement:
    by_page = {page.page_no: page for page in pages}
    rows: list[TxnRow] = []
    warnings: list[str] = []

    for region in plan.regions:
        page = by_page.get(region.page)
        if page is None:
            continue
        x, y, w, h = region.area
        x0, x1 = x * page.width, (x + w) * page.width
        y0, y1 = y * page.height, (y + h) * page.height
        words = [word for word in page.words
                 if x0 <= word.cx <= x1 and y0 <= word.cy <= y1]
        if not words:
            warnings.append(f"第 {region.page + 1} 页：版式区域里没有词")
            continue

        bounds = _bounds(region, page.width)
        heights = sorted(word.bottom - word.top for word in words)
        tolerance = max(2.0, heights[len(heights) // 2] * 0.6)
        lines = group_lines(words, y_tol=tolerance)

        row_no = 0
        for line in lines:
            cells = _assign([token for token in line.words], bounds)
            if _is_header(cells):
                continue
            candidate = _row_from_cells(cells, region.page, row_no + 1)
            if candidate is None:
                # 续行：把文本列接上上一条明细
                if rows and rows[-1].page_no == region.page:
                    tail = _text(cells.get("summary", []))
                    if tail:
                        rows[-1].summary = f"{rows[-1].summary or ''}{tail}".strip() or None
                continue
            row_no += 1
            candidate.row_no = row_no
            if candidate.txn_date is None:
                warnings.append(f"第 {region.page + 1} 页第 {row_no} 行：有金额但没读日期")
            if candidate.amount is None:
                warnings.append(f"第 {region.page + 1} 页第 {row_no} 行：有日期但没读金额")
            rows.append(candidate)

    return Statement(rows=rows, footer_count=None, page_count=plan.page_count, warnings=warnings)
