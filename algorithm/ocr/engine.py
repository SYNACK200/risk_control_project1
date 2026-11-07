from __future__ import annotations

from collections.abc import Iterator
from threading import Lock
from typing import Protocol

import fitz
import numpy as np
from pydantic import BaseModel, Field

from .parse import OcrUnavailable

DEFAULT_DPI = 200
_default_engine: RapidOCREngine | None = None
_default_lock = Lock()


class OcrWord(BaseModel):
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float


class OcrPage(BaseModel):
    page_no: int
    width: int
    height: int
    words: list[OcrWord] = Field(default_factory=list)


class OcrResult(BaseModel):
    engine: str
    pages: list[OcrPage] = Field(default_factory=list)


class OcrEngine(Protocol):
    name: str

    def recognize(self, file_bytes: bytes, dpi: int = DEFAULT_DPI) -> OcrResult:
        """图片或整份 PDF 逐页识别为带坐标与置信度的词。有文字层的电子件不要走这里。"""


def _decode_image(data: bytes) -> np.ndarray:
    import cv2

    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise OcrUnavailable("图片解码失败，无法识别")
    return image


def _render_pdf(data: bytes, dpi: int) -> Iterator[tuple[int, np.ndarray]]:
    import cv2

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise OcrUnavailable("PDF 打开失败，无法渲染识别") from exc
    try:
        if doc.needs_pass:
            raise OcrUnavailable("PDF 已加密，无法渲染识别")
        for page_no, page in enumerate(doc, start=1):
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            )
            yield page_no, cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    finally:
        doc.close()


def _iter_images(data: bytes, dpi: int) -> Iterator[tuple[int, np.ndarray]]:
    if data[:5] == b"%PDF-":
        yield from _render_pdf(data, dpi)
        return
    yield 1, _decode_image(data)


class RapidOCREngine:
    name = "rapidocr"

    def __init__(self, dpi: int = DEFAULT_DPI):
        self.dpi = dpi
        self._backend = None

    def _load_backend(self):
        if self._backend is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except Exception as exc:
                raise OcrUnavailable(
                    "RapidOCR 未安装或无法加载，执行 pip install -r algorithm/requirements.txt"
                ) from exc
            self._backend = RapidOCR()
        return self._backend

    def recognize(self, file_bytes: bytes, dpi: int | None = None) -> OcrResult:
        if not file_bytes:
            raise OcrUnavailable("文件为空，无法识别")
        backend = self._load_backend()
        pages = [
            self._recognize_page(backend, page_no, image)
            for page_no, image in _iter_images(file_bytes, dpi or self.dpi)
        ]
        return OcrResult(engine=self.name, pages=pages)

    def _recognize_page(self, backend, page_no: int, image: np.ndarray) -> OcrPage:
        raw, _ = backend(image)
        words = []
        for box, text, score in raw or []:
            text = (text or "").strip()
            if not text:
                continue
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
            words.append(
                OcrWord(
                    text=text,
                    bbox=(min(xs), min(ys), max(xs), max(ys)),
                    confidence=float(score),
                )
            )
        words.sort(key=lambda word: (round(word.bbox[1], 1), word.bbox[0]))
        height, width = image.shape[:2]
        return OcrPage(
            page_no=page_no, width=int(width), height=int(height), words=words
        )


class PaddleApiEngine:
    """云端 PaddleOCR（AI Studio）引擎：多张图并发提交。

    为什么单独做成一个引擎而不是塞进 RapidOCR：两者的成本模型完全不同——
    本地是 CPU（受 GIL 限制，并发无用），云端是 HTTP I/O（并发有效）。
    路由交给 services/ocr_routing，按图片张数决定。
    """

    name = "paddle-api"

    def __init__(self, workers: int = 2, model: str = "PP-OCRv6") -> None:
        self.workers = workers
        self.model = model

    def recognize(self, file_bytes: bytes, dpi: int | None = None) -> OcrResult:
        from services import ocr_api  # noqa: PLC0415

        # PDF 直接整份提交（服务端自己分页）；图片单张提交
        name = "document.pdf" if file_bytes[:4] == b"%PDF" else "page.jpg"
        lines = ocr_api.ocr_one(file_bytes, name=name, model=self.model)
        page = OcrPage(
            page_no=0,
            words=[OcrWord(text=str(x.get("text", "")), confidence=float(x.get("confidence") or 0.0),
                           bbox=(0.0, 0.0, 0.0, 0.0))
                   for x in lines if str(x.get("text", "")).strip()],
        )
        return OcrResult(engine="paddle-api", pages=[page] if page.words else [])

    def recognize_many(self, images: list[bytes]) -> OcrResult:
        """多张图并发——这才是用云端 API 的理由。"""
        from services import ocr_api  # noqa: PLC0415

        items = [("page-%d.jpg" % (i + 1), b) for i, b in enumerate(images)]
        results = ocr_api.ocr_many(items, model=self.model, workers=self.workers)
        pages = []
        for idx, lines in enumerate(results):
            words = [OcrWord(text=str(x.get("text", "")), confidence=float(x.get("confidence") or 0.0),
                             bbox=(0.0, 0.0, 0.0, 0.0))
                     for x in lines if str(x.get("text", "")).strip()]
            if words:
                pages.append(OcrPage(page_no=idx, words=words))
        return OcrResult(engine="paddle-api", pages=pages)


def get_default_engine() -> RapidOCREngine:
    """模型加载一次复用；多线程首次调用只初始化一份。"""
    global _default_engine
    if _default_engine is None:
        with _default_lock:
            if _default_engine is None:
                _default_engine = RapidOCREngine()
    return _default_engine