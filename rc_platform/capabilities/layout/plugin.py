"""版式能力：从页面自己长出表格结构。

它只回答「表格在哪、有哪几列、每列装什么」，不读值、不判真伪。

取词两条路，收敛逻辑共用：
- 有文本层：直接读 PDF 词（快、准）
- 没有文本层（图片/扫描）：渲染后 OCR 取词（慢，但几何算法一模一样）

倾斜校正只对「明显歪」的件动手（默认 >= 0.75 度）。文本层的角度估计很准，直接用；
OCR 词的角度有时反向（框是轴对齐的包围盒，字被切并时斜率会镜像），
所以对 OCR 采取「+θ / -θ / 不转」三个候选各跑一次几何，取认出列最多的那个——
宁可转错也不许因为一个符号把整页丢掉。
"""
from __future__ import annotations

from ...core.contracts import LayoutPlan
from ...core.registry import capability
from .deskew import estimate_angle, rotate_words
from .detect import detect_layout
from .words import PageWords, read_pages


def _score(plan: LayoutPlan) -> tuple[int, int, float]:
    return (len(plan.regions), sum(len(region.columns) for region in plan.regions), plan.confidence)


def _pick_rotation(pages: list[PageWords], angle: float) -> tuple[list[PageWords], float]:
    best_pages, best_angle, best_score = pages, 0.0, (-1, -1, -1.0)
    for candidate in (0.0, angle, -angle):
        turned = pages if candidate == 0.0 else [rotate_words(page, candidate) for page in pages]
        score = _score(detect_layout(turned))
        if score > best_score:
            best_pages, best_angle, best_score = turned, candidate, score
    return best_pages, best_angle


@capability
class AnchorSpreadLayout:
    """锚点扩散为主、几何聚类兜底、表头位置保底的版式检测。"""

    name = "layout.anchor_spread"
    version = "1.2"
    provides = "layout"
    requires = ("document", "profile")
    priority = 0

    def run(self, ctx, inputs) -> LayoutPlan:
        doc = inputs["document"]
        profile = inputs["profile"]
        pages = read_pages(doc.data)
        used_ocr = False

        if not any(page.has_text for page in pages) and ctx.setting("layout.ocr", False):
            from .ocr_words import read_pages_via_ocr

            pages = read_pages_via_ocr(doc.data, dpi=int(ctx.setting("layout.ocr_dpi", 200)))
            used_ocr = True

        applied = 0.0
        if ctx.setting("layout.deskew", True):
            angle = estimate_angle(pages)
            if abs(angle) >= float(ctx.setting("layout.deskew_min_angle", 0.75)):
                pages, applied = _pick_rotation(pages, angle)

        plan = detect_layout(pages)
        if applied:
            plan.reasons.insert(0, f"已校正倾斜 {applied:+.2f}°")
        if used_ocr:
            plan.reasons.insert(0, "文本层为空，已改用 OCR 取词")
        elif not plan.regions and profile.carrier in ("image", "screenshot"):
            plan.reasons.append("图片件没有文本层：开启 layout.ocr 后可由 OCR 取词")
        ctx.logger.info(
            "版式检测：%s，置信 %.2f，%d 个区域%s%s",
            plan.method, plan.confidence, len(plan.regions),
            "（OCR 取词）" if used_ocr else "",
            f"（校正 {applied:+.2f}°）" if applied else "",
        )
        return plan
