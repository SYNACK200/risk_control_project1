"""图片件 / 扫描件取词：走 OCR，产出与文本层同一种 PageWords。

为什么要自己调 RapidOCR 而不是用封存版的 engine：
engine 把四点框压成了外接矩形，把「文字方向」这个信息丢了。
斜图里外接矩形的中心还是对的，但方向丢了之后，倾斜校正只能靠词对斜率去猜，
一遇到字被切并就会估反（实测 +3° 估成 -2.66°，转过去更歪）。
这里保留四点框，于是每个词自己带着方向，估角变成「取中位数」这么简单。

坐标单位是图片像素，下游一律按 width/height 归一化，所以不需要换算。
"""
from __future__ import annotations

import math

import cv2
import numpy as np
import pymupdf

from .words import PageWords, Word

_BACKEND = None


def _backend():
    global _BACKEND
    if _BACKEND is None:
        from rapidocr_onnxruntime import RapidOCR

        _BACKEND = RapidOCR()
    return _BACKEND


def _iter_images(data: bytes, dpi: int, password: str | None = None,
                 page_indices: list[int] | None = None):
    if b"%PDF-" in data[:1024]:
        doc = pymupdf.open(stream=data, filetype="pdf")
        if doc.needs_pass:
            if not password:
                doc.close()
                raise ValueError("PDF 设有打开口令，请输入口令后再分析")
            if doc.authenticate(password) <= 0:
                doc.close()
                raise ValueError("口令不正确，请重新输入")
        try:
            targets = (
                [i for i in page_indices if 0 <= i < doc.page_count]
                if page_indices is not None
                else list(range(doc.page_count))
            )
            for page_no in targets:
                pix = doc[page_no].get_pixmap(dpi=dpi, alpha=False)
                image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                yield page_no, cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        finally:
            doc.close()
        return
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("图片解码失败，无法识别")
    yield 0, image


def _word_from_box(text: str, box, confidence: float) -> Word:
    """四点框 -> 词。

    存的是「固有尺寸 + 中心 + 方向」，而不是外接矩形：
    斜着的外接矩形比字本身大一圈，旋转回去时框会越转越大，行就被抹在一起了。
    """
    points = [(float(point[0]), float(point[1])) for point in box]
    centre_x = sum(point[0] for point in points) / len(points)
    centre_y = sum(point[1] for point in points) / len(points)
    length = math.dist(points[0], points[1])
    thickness = math.dist(points[1], points[2]) if len(points) > 2 else length * 0.4
    angle = math.degrees(math.atan2(points[1][1] - points[0][1], points[1][0] - points[0][0]))
    return Word(
        text=text,
        x0=centre_x - length / 2, x1=centre_x + length / 2,
        top=centre_y - thickness / 2, bottom=centre_y + thickness / 2,
        confidence=float(confidence or 1.0),
        angle=angle,
        oriented=(length, thickness),
    )


def read_pages_via_ocr(data: bytes, dpi: int = 200, password: str | None = None,
                       page_indices: list[int] | None = None) -> list[PageWords]:
    backend = _backend()
    pages: list[PageWords] = []
    for page_no, image in _iter_images(data, dpi, password=password, page_indices=page_indices):
        raw, _ = backend(image)
        height, width = image.shape[:2]
        words: list[Word] = []
        for item in raw or []:
            box, text, confidence = item[0], (item[1] or "").strip(), item[2]
            if not text:
                continue
            words.append(_word_from_box(text, box, confidence))
        pages.append(PageWords(page_no=page_no, width=float(width), height=float(height),
                               words=words, has_text=bool(words)))
    return pages
