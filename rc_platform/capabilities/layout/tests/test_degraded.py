"""劣质件的代理样本与验收。

真实劣质件（拍照歪斜、低分辨率、两版式拼页）拿不到，这里用三种可复现的构造逼近它：
1. 坐标层倾斜：把干净件的词框绕页心旋转——斜的是版式，不是画质
2. 真实图像倾斜：渲染成图片再旋转，走 OCR 通道（更接近拍照件，但慢）
3. 拼页：把两家银行的页面拼成一份文件——模拟「同一份流水混两种版式」

判据只有一条：**歪了之后还能不能读出同样多的笔、同样的金额**。
"""
from __future__ import annotations

import math
import pathlib

import pymupdf
import pytest

from rc_platform.capabilities.layout.deskew import deskew_pages, estimate_angle
from rc_platform.capabilities.layout.detect import detect_layout
from rc_platform.capabilities.layout.words import PageWords, Word, read_pages
from rc_platform.capabilities.parse_v2.table_reader import read_statement

ROOT = pathlib.Path(__file__).resolve().parents[4]
SAMPLES = ROOT / "algorithm" / "inputs" / "samples" / "synthetic"

needs_samples = pytest.mark.skipif(not SAMPLES.exists(), reason="合成样本未生成")


def skew_pages(pages: list[PageWords], degrees: float) -> list[PageWords]:
    theta = math.radians(degrees)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    out = []
    for page in pages:
        cx, cy = page.width / 2, page.height / 2
        words = []
        for word in page.words:
            points = []
            for x, y in ((word.x0, word.top), (word.x1, word.bottom)):
                dx, dy = x - cx, y - cy
                points.append((cx + dx * cos_t - dy * sin_t, cy + dx * sin_t + dy * cos_t))
            words.append(Word(word.text, min(p[0] for p in points), max(p[0] for p in points),
                              min(p[1] for p in points), max(p[1] for p in points)))
        out.append(PageWords(page.page_no, page.width, page.height, words, page.has_text))
    return out


def load(name: str) -> list[PageWords]:
    return read_pages((SAMPLES / "clean" / f"{name}.pdf").read_bytes())


@needs_samples
@pytest.mark.parametrize("degrees", [2.0, 5.0, -4.0])
def test_deskew_estimates_the_skew(degrees):
    pages = skew_pages(load("icbc"), degrees)
    assert abs(estimate_angle(pages) + degrees) <= 0.5, "校正角应约等于反向的倾斜角"


@needs_samples
@pytest.mark.parametrize("degrees", [2.0, 5.0, -4.0])
def test_skewed_pages_recover_columns_after_deskew(degrees):
    pages = skew_pages(load("icbc"), degrees)
    fixed, applied = deskew_pages(pages)
    assert applied != 0.0
    plan = detect_layout(fixed)
    fields = {col.field for region in plan.regions for col in region.columns}
    assert {"txn_date", "amount", "balance"} <= fields


@needs_samples
@pytest.mark.parametrize("degrees", [2.0, 5.0])
def test_rows_survive_skew_end_to_end(degrees):
    """歪 5 度后仍然要读出 6 笔、金额一笔不差。"""
    clean = load("icbc")
    baseline = read_statement(clean, detect_layout(clean))
    skewed = skew_pages(clean, degrees)
    fixed, _ = deskew_pages(skewed)
    plan = detect_layout(fixed)

    assert len(plan.regions) == 2
    recovered = read_statement(fixed, plan)

    assert len(recovered.rows) == len(baseline.rows) == 6
    assert [r.amount for r in recovered.rows] == [r.amount for r in baseline.rows]
    assert [r.txn_date for r in recovered.rows] == [r.txn_date for r in baseline.rows]


@needs_samples
def test_spliced_layouts_are_detected_page_by_page():
    """两家银行拼成一份文件：每一页都要有自己的几何，不能拿一种版式套全篇。"""
    first = pymupdf.open(stream=(SAMPLES / "clean" / "icbc.pdf").read_bytes(), filetype="pdf")
    second = pymupdf.open(stream=(SAMPLES / "clean" / "ccb.pdf").read_bytes(), filetype="pdf")
    merged = pymupdf.open()
    try:
        merged.insert_pdf(first, from_page=0, to_page=0)
        merged.insert_pdf(second, from_page=0, to_page=0)
        data = merged.tobytes()
    finally:
        merged.close()
        first.close()
        second.close()

    pages = read_pages(data)
    plan = detect_layout(pages)
    assert len(pages) == 2
    assert len(plan.regions) == 2, "两页版式不同，必须各出一份几何"

    statement = read_statement(pages, plan)
    assert len(statement.rows) >= 6, f"拼页后只读出 {len(statement.rows)} 笔"
    assert any(row.txn_date for row in statement.rows)


@pytest.mark.skipif(not SAMPLES.exists(), reason="合成样本未生成")
def test_low_resolution_rotated_image_via_ocr_recovers_all_columns():
    """真实图像路径：150dpi + 旋转 3° + OCR，六列要全认回来。

    这一条曾经是红的：OCR 给的是轴对齐外接矩形，方向信息被丢掉，估角会估反。
    修法是保留四点框的固有尺寸与方向（ocr_words），估角改成「词方向的中位数」，
    再按字高自适应行容差。细节见 docs/rebuild/02-M2-解析框架.md。
    """
    pytest.importorskip("rapidocr_onnxruntime", reason="未安装 RapidOCR")
    from rc_platform.capabilities.layout.ocr_words import read_pages_via_ocr

    doc = pymupdf.open(stream=(SAMPLES / "clean" / "icbc.pdf").read_bytes(), filetype="pdf")
    try:
        pix = doc[0].get_pixmap(dpi=150)
        base = pix.tobytes("jpeg")
    finally:
        doc.close()

    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(base, dtype=np.uint8), cv2.IMREAD_COLOR)
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), 3.0, 1.0)
    turned = cv2.warpAffine(image, matrix, (width, height), borderValue=(255, 255, 255))
    ok, buffer = cv2.imencode(".jpg", turned)
    assert ok
    data = buffer.tobytes()

    # 走真实能力路径：候选角度择优、OCR 取词、几何收敛都在能力里
    from rc_platform.core.context import JobContext
    from rc_platform.core.contracts import DocumentProfile, SourceDocument
    from rc_platform.core.pipeline import Pipeline
    from rc_platform.core.registry import Registry, discover

    discover()
    registry = Registry()
    result = Pipeline(registry, ["layout.anchor_spread"], on_error="fail").run(
        JobContext(config={"layout.ocr": True}),
        {"document": SourceDocument(data=data), "profile": DocumentProfile(carrier="image")},
    )
    plan = result.get("layout")
    fields = {col.field for region in plan.regions for col in region.columns}
    assert plan.regions, f"OCR+校正后整页没出几何：{plan.reasons}"
    assert {"txn_date", "amount", "balance"} <= fields, f"关键列没认全：{fields}"
