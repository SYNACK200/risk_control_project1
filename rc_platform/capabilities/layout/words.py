"""把 PDF 变成带坐标的词；没有文本层就明确说没有（图片件走 OCR 通道）。"""
from __future__ import annotations

from dataclasses import dataclass, field

import pymupdf


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    size: float = 0.0
    confidence: float = 1.0
    # 文字基线方向（度，屏幕坐标 y 向下）与「沿基线/垂直基线」的固有尺寸。
    # 文本层没有这两个概念，只有 OCR 的四点框才有。
    # 有了固有尺寸，旋转时才能保持词框本来的大小——直接旋转外接矩形的四个角会让框越转越大。
    angle: float | None = None
    oriented: tuple[float, float] | None = None

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def width(self) -> float:
        return self.x1 - self.x0


@dataclass
class Line:
    words: list[Word] = field(default_factory=list)
    top: float = 0.0
    bottom: float = 0.0

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def x0(self) -> float:
        return min((w.x0 for w in self.words), default=0.0)

    @property
    def x1(self) -> float:
        return max((w.x1 for w in self.words), default=0.0)


@dataclass
class PageWords:
    page_no: int
    width: float
    height: float
    words: list[Word] = field(default_factory=list)
    has_text: bool = False


def group_lines(words_: list[Word], y_tol: float = 3.0) -> list[Line]:
    lines: list[Line] = []
    for word in sorted(words_, key=lambda w: (w.cy, w.x0)):
        if lines and abs(word.cy - lines[-1].cy) <= y_tol:
            line = lines[-1]
            line.words.append(word)
            line.top = min(line.top, word.top)
            line.bottom = max(line.bottom, word.bottom)
        else:
            lines.append(Line(words=[word], top=word.top, bottom=word.bottom))
    for line in lines:
        line.words.sort(key=lambda w: w.x0)
    return lines


def adaptive_group_lines(words_: list[Word]) -> list[Line]:
    """按词高自适应行容差分组，兼容 PDF 文本层与 OCR 像素坐标。"""
    if not words_:
        return []
    heights = sorted(max(0.0, word.bottom - word.top) for word in words_)
    median_h = heights[len(heights) // 2]
    tolerance = max(2.0, median_h * 0.6)
    return group_lines(words_, y_tol=tolerance)


def merge_tokens(line: Line, gap: float = 2.0) -> list[Word]:
    """把同一行里紧邻的词并成一个 token（PDF 常把一个表头词拆成多个 word）。"""
    tokens: list[Word] = []
    for word in line.words:
        if tokens and word.x0 - tokens[-1].x1 <= gap:
            prev = tokens[-1]
            tokens[-1] = Word(
                text=prev.text + word.text,
                x0=prev.x0, x1=max(prev.x1, word.x1),
                top=min(prev.top, word.top), bottom=max(prev.bottom, word.bottom),
                size=max(prev.size, word.size),
            )
        else:
            tokens.append(word)
    return tokens


def _is_pdf_bytes(data: bytes) -> bool:
    return b"%PDF-" in data[:1024]


def _read_image_stub(data: bytes) -> list[PageWords]:
    """图片输入没有 PDF 文本层：读出真实宽高，交给上层决定是否走 OCR。"""
    pix = pymupdf.Pixmap(data)
    return [PageWords(page_no=0, width=float(pix.width), height=float(pix.height),
                      words=[], has_text=False)]


def read_pages(data: bytes, password: str | None = None) -> list[PageWords]:
    """读 PDF 每页的词。没有文本层时 words 为空、has_text=False。

    加密件必须带口令：pymupdf 在没认证时读页会抛「No password given」，
    这个字符串会一路冒到界面上，用户看不懂，所以在入口就转成可读的错误。
    """
    if not _is_pdf_bytes(data):
        return _read_image_stub(data)

    pages: list[PageWords] = []
    doc = pymupdf.open(stream=data, filetype="pdf")
    if doc.needs_pass:
        if not password:
            doc.close()
            raise ValueError("PDF 设有打开口令，请输入口令后再分析")
        if doc.authenticate(password) <= 0:
            doc.close()
            raise ValueError("口令不正确，请重新输入")
    try:
        for page_no in range(doc.page_count):
            page = doc[page_no]
            rect = page.rect
            matrix = page.rotation_matrix
            raw = page.get_text("words") or []
            items: list[Word] = []
            for r in raw:
                text = str(r[4]).strip()
                if not text:
                    continue
                # PyMuPDF 的 words 坐标按未旋转 MediaBox 给出，旋转页必须乘 rotation_matrix
                # 才能与 page.rect 及前端画布坐标对齐。
                box = pymupdf.Rect(float(r[0]), float(r[1]), float(r[2]), float(r[3])) * matrix
                x0 = max(0.0, min(float(rect.width), float(box.x0)))
                x1 = max(x0, min(float(rect.width), float(box.x1)))
                top = max(0.0, min(float(rect.height), float(box.y0)))
                bottom = max(top, min(float(rect.height), float(box.y1)))
                items.append(Word(text=text, x0=x0, x1=x1, top=top, bottom=bottom))
            pages.append(PageWords(page_no=page_no, width=float(rect.width), height=float(rect.height),
                                   words=items, has_text=bool(items)))
    finally:
        doc.close()
    return pages
