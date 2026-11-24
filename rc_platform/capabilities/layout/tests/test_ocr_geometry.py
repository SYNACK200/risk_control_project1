"""图片件的几何验证：把电子件渲染成图片，再只用 OCR 词重建版式。

这是「质量差」场景的真实代理——真实劣质件拿不到，但一条渲染-识别-重建的链路
能回答同一个问题：几何算法是否只依赖「词 + 坐标」，而不依赖文本层。
"""
from __future__ import annotations

import pathlib

import pymupdf
import pytest

from rc_platform.capabilities.layout.detect import detect_layout
from rc_platform.capabilities.layout.ocr_words import read_pages_via_ocr

pytest.importorskip("rapidocr_onnxruntime", reason="未安装 RapidOCR，跳过 OCR 几何验证")

ROOT = pathlib.Path(__file__).resolve().parents[4]
SAMPLE = ROOT / "algorithm" / "inputs" / "samples" / "synthetic" / "clean" / "icbc.pdf"


def _rasterize(data: bytes, dpi: int = 150) -> bytes:
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        return doc[0].get_pixmap(dpi=dpi).tobytes("jpeg")
    finally:
        doc.close()


@pytest.mark.skipif(not SAMPLE.exists(), reason="合成样本未生成")
def test_geometry_recovered_from_ocr_words_only():
    image = _rasterize(SAMPLE.read_bytes())
    pages = read_pages_via_ocr(image, dpi=200)
    assert pages and pages[0].words, "OCR 没取到词"

    plan = detect_layout(pages)
    fields = {col.field for region in plan.regions for col in region.columns}
    assert {"txn_date", "amount", "balance"} <= fields
    assert plan.confidence >= 0.6
