from __future__ import annotations

import io
import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

import fitz
import pdfplumber

from .models import Direction, PageSummary, ParseResult, Template, Transaction
from .table import (
    Line,
    Word,
    build_columns,
    find_header,
    group_lines,
    line_cells,
)

DATE_RE = re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})")
MONEY_RE = re.compile(r"[-+]?[¥￥]?\d[\d,]*(?:\.\d+)?")
FOOTER_RE = re.compile(r"(?:共|合计|总计)\s*(\d+)\s*笔")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")
PAGE_COUNT_RE = re.compile(r"(?<![\d.])(\d+)\s*$")
PAGE_COUNT_LABEL_RE = re.compile(r"本页交易笔数[:：]?\s*(\d+)")
PAGE_IN_RE = re.compile(r"(?:本页)?收入(?:算术)?合计[:：]?\s*([-+]?[¥￥]?[\d,]+\.\d{2})")
PAGE_OUT_RE = re.compile(r"(?:本页)?支出(?:算术)?合计[:：]?\s*([-+]?[¥￥]?[\d,]+\.\d{2})")
TOTAL_LINE_RE = re.compile(r"[-+]?[\d,]+\.\d{2}\s*$")
DECIMAL_MONEY_RE = re.compile(r"[-+]?[¥￥]?\d[\d,]*\.\d{2}")
PAGE_MARK_RE = re.compile(r"(第\s*\d+\s*页|page\s*\d+|共\s*\d+\s*页)", re.IGNORECASE)

REQUIRED_FIELDS = ("txn_date", "amount", "direction")
LOW_CONF = 0.8
MIN_BODY_SIZE = 5.0
MAX_BODY_SIZE = 12.0
WORD_X_TOLERANCE = 4.0
LINE_Y_TOLERANCE = 4.0


class OcrUnavailable(RuntimeError):
    """OCR 引擎不可用或未接入（影像件无法走文字层解析）。"""


def parse_date(text: str) -> str | None:
    match = DATE_RE.search(re.sub(r"\s+", "", text or ""))
    if not match:
        return None
    year, month, day = (int(g) for g in match.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_money(text: str) -> Decimal | None:
    raw = re.sub(r"\s+", "", text or "")
    match = MONEY_RE.search(raw)
    if not match:
        return None
    value = match.group(0).replace("¥", "").replace("￥", "").replace(",", "")
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


_IN = {"收", "收入", "入账", "转入", "存入", "贷", "贷方", "进账"}
_OUT = {"支", "支出", "出账", "转出", "取出", "借", "借方"}


def parse_direction(text: str, amount: Decimal | None) -> Direction | None:
    value = re.sub(r"\s+", "", text or "")
    if "不计" in value:
        return None
    if value in _IN:
        return "in"
    if value in _OUT:
        return "out"
    if "收" in value or "入" in value:
        return "in"
    if "支" in value or "出" in value or "借" in value:
        return "out"
    if amount is not None and amount < 0:
        return "out"
    return None


def _to_words(raw_words: list[dict]) -> list[Word]:
    return [
        Word(
            text=w["text"],
            x0=float(w["x0"]),
            x1=float(w["x1"]),
            top=float(w["top"]),
            bottom=float(w["bottom"]),
        )
        for w in raw_words
    ]


def _cell_text(words: list[Word]) -> str:
    return "".join(w.text for w in words).strip()


def _bbox(words: list[Word]) -> tuple[float, float, float, float] | None:
    if not words:
        return None
    return (
        min(w.x0 for w in words),
        min(w.top for w in words),
        max(w.x1 for w in words),
        max(w.bottom for w in words),
    )


def _is_body_char(obj: dict) -> bool:
    if obj["object_type"] != "char":
        return True
    size = float(obj.get("size", 0))
    return MIN_BODY_SIZE <= size <= MAX_BODY_SIZE


def _fitz_page_words(page: fitz.Page) -> tuple[list[Word], list[str], bool]:
    """按字号过滤水印/缩印重影，返回 (词, 正文字符串, 页面是否有任何文本)。"""
    layout = page.get_text("dict")
    body_lines: dict[tuple[int, int], list[tuple[float, float, float, float]]] = {}
    body_texts: list[str] = []
    has_text = False
    for block_index, block in enumerate(layout["blocks"]):
        block_no = block.get("number", block_index)
        for line_index, line in enumerate(block.get("lines", [])):
            rects: list[tuple[float, float, float, float]] = []
            for span in line.get("spans", []):
                text = span.get("text", "")
                if text.strip():
                    has_text = True
                if MIN_BODY_SIZE <= float(span.get("size", 0)) <= MAX_BODY_SIZE:
                    rects.append(tuple(span["bbox"]))
                    body_texts.append(text)
            if rects:
                body_lines[(block_no, line_index)] = rects

    matrix = page.rotation_matrix
    words: list[Word] = []
    for x0, y0, x1, y1, text, block_no, line_no, _ in page.get_text("words"):
        rects = body_lines.get((block_no, line_no))
        if not rects or not text.strip():
            continue
        if not any(x0 < r[2] and x1 > r[0] and y0 < r[3] and y1 > r[1] for r in rects):
            continue
        rect = fitz.Rect(x0, y0, x1, y1) * matrix
        words.append(Word(text=text, x0=rect.x0, x1=rect.x1, top=rect.y0, bottom=rect.y1))
    return words, body_texts, has_text


def _fitz_extract(
    file_bytes: bytes,
) -> tuple[list[tuple[int, list[Word]]] | None, int, int, bool, bool]:
    """返回 (逐页词, 页数, 正文日期数, 是否有文本, 是否加密)。

    PyMuPDF 抽取 3000 笔约 1 秒；pdfplumber 基于 pdfminer，同量级需约 5 秒，
    因此电子件以 PyMuPDF 为主，解析不到明细时再回退 pdfplumber。
    """
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        if doc.needs_pass:
            return None, 0, 0, False, True
        pages: list[tuple[int, list[Word]]] = []
        body_texts: list[str] = []
        has_text = False
        for page_no, page in enumerate(doc, start=1):
            words, texts, page_has_text = _fitz_page_words(page)
            pages.append((page_no, words))
            body_texts.extend(texts)
            has_text = has_text or page_has_text
        return pages, doc.page_count, len(DATE_RE.findall("\n".join(body_texts))), has_text, False
    finally:
        doc.close()


def _assign_money(txn: Transaction, cells: dict[str, list[Word]]) -> None:
    """从单元格补全金额/方向/余额；正数带 '+' 视为收入。"""
    if txn.amount is None:
        raw = _cell_text(cells.get("amount", []))
        amount = parse_money(raw)
        positive = "+" in raw
        if amount is None:
            amount_in = parse_money(_cell_text(cells.get("amount_in", [])))
            amount_out = parse_money(_cell_text(cells.get("amount_out", [])))
            if amount_in is not None:
                amount, positive = amount_in, True
                txn.direction = txn.direction or "in"
            elif amount_out is not None:
                amount, positive = amount_out, False
                txn.direction = txn.direction or "out"
        if amount is not None:
            if amount < 0:
                txn.amount = -amount
                txn.direction = txn.direction or "out"
            else:
                txn.amount = amount
                if positive:
                    txn.direction = txn.direction or "in"
    if txn.balance is None:
        txn.balance = parse_money(_cell_text(cells.get("balance", [])))


def _parse_pdf_pages(
    pdf: pdfplumber.PDF,
    template: Template | None,
    warnings: list[str],
) -> tuple[list[Transaction], int | None, list[PageSummary]]:
    def pages() -> Iterable[tuple[int, list[Word]]]:
        for page_no, page in enumerate(pdf.pages, start=1):
            body = page.filter(_is_body_char)
            raw = body.extract_words(x_tolerance=WORD_X_TOLERANCE, y_tolerance=2.5, keep_blank_chars=False)
            yield page_no, _to_words(raw)

    return _transactions_from_pages(pages(), template, warnings)


def _line_confidence(line: Line) -> float:
    return min((word.confidence for word in line.words), default=1.0)


def _transactions_from_pages(
    pages: Iterable[tuple[int, list[Word]]],
    template: Template | None,
    warnings: list[str],
    allow_date_in_line: bool = False,
    strip_date_from_summary: bool = False,
) -> tuple[list[Transaction], int | None, list[PageSummary]]:
    transactions: list[Transaction] = []
    columns = None
    footer_count: int | None = None
    page_footer_total = 0
    summaries: list[PageSummary] = []

    for page_no, words in pages:
        page_footer: int | None = None
        page_summary = PageSummary(page_no=page_no)
        summaries.append(page_summary)
        lines = group_lines(words, y_tol=LINE_Y_TOLERANCE)
        if not lines:
            continue

        header = find_header(lines, template.field_map if template else None)
        if header is not None:
            header_line, tokens, mapping = header
            columns = build_columns(tokens, mapping)
            header_top = header_line.top
        elif columns is None:
            warnings.append(f"第 {page_no} 页未识别到表头，跳过该页")
            continue
        else:
            header_top = -1.0

        current: Transaction | None = None
        for line in lines:
            if line.top <= header_top:
                continue
            text = line.text.strip()
            if not text:
                continue

            printed_in = PAGE_IN_RE.search(text)
            printed_out = PAGE_OUT_RE.search(text)
            if printed_in or printed_out:
                page_summary.printed_in = parse_money(printed_in.group(1)) if printed_in else None
                page_summary.printed_out = parse_money(printed_out.group(1)) if printed_out else None
                page_summary.footer_bbox = page_summary.footer_bbox or _bbox(line.words)
                continue

            count_label = PAGE_COUNT_LABEL_RE.search(text)
            if count_label:
                page_footer = int(count_label.group(1))
                page_summary.printed_count = page_footer
                page_summary.footer_bbox = _bbox(line.words)
                break

            footer = FOOTER_RE.search(text)
            if footer:
                footer_count = int(footer.group(1))
                page_summary.printed_count = footer_count
                page_summary.footer_bbox = _bbox(line.words)
                break

            cells = line_cells(line, columns)
            date_text = _cell_text(cells.get("txn_date", []))
            txn_date = parse_date(date_text)
            if txn_date is None and allow_date_in_line and DECIMAL_MONEY_RE.search(text):
                txn_date = parse_date(text)

            if txn_date is None:
                if PAGE_COUNT_RE.search(date_text) and not TIME_RE.match(date_text):
                    page_footer = int(PAGE_COUNT_RE.search(date_text).group(1))
                    page_summary.printed_count = page_footer
                    page_summary.footer_bbox = page_summary.footer_bbox or _bbox(line.words)
                    break
                if TOTAL_LINE_RE.search(date_text):
                    continue
            if PAGE_MARK_RE.search(text) and not DATE_RE.search(text):
                continue

            if txn_date is None:
                if current is None:
                    continue
                extra = _cell_text(cells.get("summary", []))
                if extra and extra not in (current.summary or ""):
                    current.summary = f"{current.summary or ''}{extra}"
                extra_cp = _cell_text(cells.get("counterparty", []))
                if extra_cp and extra_cp not in (current.counterparty_name or ""):
                    current.counterparty_name = f"{current.counterparty_name or ''}{extra_cp}"
                _assign_money(current, cells)
                current.confidence = min(current.confidence, _line_confidence(line))
                continue

            summary = _cell_text(cells.get("summary", []))
            if strip_date_from_summary:
                if not summary:
                    summary = date_text
                summary = DATE_RE.sub("", summary).strip()
            direction_text = _cell_text(cells.get("direction", []))
            current = Transaction(
                page_no=page_no,
                row_no=len(transactions) + 1,
                txn_date=txn_date,
                summary=summary or None,
                counterparty_name=_cell_text(cells.get("counterparty", [])) or None,
                direction=parse_direction(direction_text, None),
                confidence=_line_confidence(line),
                bbox=_bbox(line.words),
            )
            _assign_money(current, cells)
            transactions.append(current)

        if page_footer is not None:
            page_footer_total += page_footer

    if footer_count is None and page_footer_total:
        footer_count = page_footer_total
    return transactions, footer_count, summaries


def _ocr_to_words(page) -> list[Word]:
    return [
        Word(
            text=word.text,
            x0=word.bbox[0],
            x1=word.bbox[2],
            top=word.bbox[1],
            bottom=word.bbox[3],
            confidence=word.confidence,
        )
        for word in page.words
    ]


def _parse_ocr(file_bytes: bytes, template: Template | None) -> ParseResult:
    from .engine import get_default_engine

    ocr = get_default_engine().recognize(file_bytes)
    warnings = [f"经 OCR 识别（{ocr.engine}），结果需人工核对"]
    if not ocr.pages:
        warnings.append("OCR 未返回页面")
        return _build_result([], None, 0, warnings)

    pages = [(page.page_no, _ocr_to_words(page)) for page in ocr.pages]
    transactions, footer_count, summaries = _transactions_from_pages(
        pages,
        template,
        warnings,
        allow_date_in_line=True,
        strip_date_from_summary=True,
    )
    if not transactions:
        warnings.append("未解析到交易明细")
    if footer_count is not None and footer_count != len(transactions):
        warnings.append(f"页脚笔数 {footer_count} 与解析笔数 {len(transactions)} 不一致")
    return _build_result(transactions, footer_count, len(ocr.pages), warnings, summaries)


def _parse_with_plumber(
    file_bytes: bytes,
    template: Template | None,
    warnings: list[str],
) -> tuple[list[Transaction], int | None, int, list[PageSummary]] | None:
    try:
        pdf = pdfplumber.open(io.BytesIO(file_bytes))
    except Exception as exc:  # 加密或结构损坏
        warnings.append(f"pdfplumber 回退失败：{exc}")
        return None
    with pdf:
        if not pdf.pages:
            warnings.append("PDF 无页面")
            return None
        transactions, footer_count, summaries = _parse_pdf_pages(pdf, template, warnings)
        return transactions, footer_count, len(pdf.pages), summaries


def _build_result(
    transactions: list[Transaction],
    footer_count: int | None,
    page_count: int,
    warnings: list[str],
    page_summaries: list[PageSummary] | None = None,
) -> ParseResult:
    total = len(transactions)
    if total:
        missing = sum(1 for t in transactions for f in REQUIRED_FIELDS if getattr(t, f) is None)
        completeness = 1 - missing / (total * len(REQUIRED_FIELDS))
        avg_conf = sum(t.confidence for t in transactions) / total
        low_ratio = sum(1 for t in transactions if t.confidence < LOW_CONF) / total
    else:
        completeness = avg_conf = low_ratio = 0.0

    return ParseResult(
        transactions=transactions,
        field_completeness=round(completeness, 4),
        avg_confidence=round(avg_conf, 4),
        low_conf_ratio=round(low_ratio, 4),
        page_count=page_count,
        footer_count=footer_count,
        page_summaries=page_summaries or [],
        warnings=warnings,
    )


def parse(file_bytes: bytes, template: Template | None = None) -> ParseResult:
    """解析电子件 PDF 与影像件；影像件走本机 OCR 引擎（RapidOCR）。"""
    if not file_bytes:
        return ParseResult(warnings=["空文件"])
    if file_bytes.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")):
        return _parse_ocr(file_bytes, template)
    if not file_bytes.startswith(b"%PDF"):
        return ParseResult(warnings=["不支持的文件格式"])

    warnings: list[str] = []
    try:
        pages, page_count, body_dates, has_text, encrypted = _fitz_extract(file_bytes)
    except Exception as exc:
        message = (
            "PDF 已加密，无法解析（应由入口检查返回 E_ENCRYPT）"
            if "password" in str(exc).lower()
            else f"PyMuPDF 抽取失败：{exc}，改走 pdfplumber"
        )
        if "password" in str(exc).lower():
            return ParseResult(warnings=[message])
        warnings.append(message)
        pages = None
        page_count = body_dates = 0
        has_text = True

    if encrypted:
        return ParseResult(warnings=["PDF 已加密，无法解析（应由入口检查返回 E_ENCRYPT）"])
    if pages is not None and page_count == 0:
        return ParseResult(warnings=["PDF 无页面"])
    if not has_text:
        return _parse_ocr(file_bytes, template)

    if pages is not None:
        transactions, footer_count, page_summaries = _transactions_from_pages(
            iter(pages), template, warnings
        )
    else:
        transactions, footer_count, page_summaries = [], None, []

    if not transactions:
        warnings.append("PyMuPDF 未解析到明细，回退 pdfplumber")
        fallback = _parse_with_plumber(file_bytes, template, warnings)
        if fallback is not None:
            transactions, footer_count, fallback_pages, page_summaries = fallback
            if page_count and fallback_pages != page_count:
                warnings.append(
                    f"引擎页数不一致：PyMuPDF {page_count} vs pdfplumber {fallback_pages}"
                )
            page_count = fallback_pages or page_count

    if not transactions:
        warnings.append("未解析到交易明细")
    if footer_count is not None and footer_count != len(transactions):
        warnings.append(f"页脚笔数 {footer_count} 与解析笔数 {len(transactions)} 不一致")
    if transactions and body_dates and abs(body_dates - len(transactions)) > max(2, len(transactions) // 6):
        warnings.append(
            f"正文日期数与解析笔数差异较大：{body_dates} vs {len(transactions)}，需人工核对"
        )

    if not transactions:
        transactions, footer_count, page_summaries, page_count = _generic_rescue(
            file_bytes, page_count, page_summaries, warnings
        )
    return _build_result(transactions, footer_count, page_count, warnings, page_summaries)


def _generic_rescue(file_bytes, page_count, page_summaries, warnings):
    # 第三层兜底：表头驱动的通用解析（未知银行/未知版式，等价于默认模板）
    warnings.append("两套引擎均未解析到明细，回退表头驱动的通用解析")
    try:
        from .generic_parse import parse_generic

        result, generic_warnings = parse_generic(file_bytes)
        warnings.extend(generic_warnings)
        if result.transactions:
            return (
                result.transactions,
                result.footer_count,
                result.page_summaries,
                result.page_count or page_count,
            )
    except Exception as exc:
        warnings.append("通用解析执行失败：" + str(exc))
    return [], None, page_summaries, page_count
