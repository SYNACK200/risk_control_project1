"""模板「框选反向查看」：把当时的标注点换算成页面上的方框，并渲染成可看的图片。

模板本身只存 field_map（字段→列），看不到当时选的是哪块。这里做两件事：
1. build_layout(): 把用户标注点 + 推断出的列 x 范围 + 表头文字位置，合成 {page,x0,y0,x1,y1} 方框；
2. render_page_png(): 在原页面上画出方框和字段名，输出 PNG（工作人员直接看图，不用看坐标）。
"""
from __future__ import annotations

import pymupdf

# 每个字段一种颜色，图例与方框同色
PALETTE = [
    (0.90, 0.29, 0.24),  # 红
    (0.16, 0.47, 0.85),  # 蓝
    (0.13, 0.62, 0.36),  # 绿
    (0.85, 0.55, 0.10),  # 橙
    (0.55, 0.30, 0.80),  # 紫
    (0.10, 0.60, 0.65),  # 青
    (0.75, 0.25, 0.55),  # 洋红
    (0.45, 0.45, 0.15),  # 橄榄
]


def _color(index: int) -> tuple[float, float, float]:
    return PALETTE[index % len(PALETTE)]


def build_layout(pdf_bytes: bytes, marks: list[dict], columns: list[dict], field_map: dict) -> dict:
    """把标注点变成方框：x 取推断出的列范围，y 取表头文字位置（找不到就用标注点附近）。"""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    by_alias = {}
    for col in columns or []:
        alias = col.get("alias") or col.get("name")
        if alias:
            by_alias[str(alias)] = col

    boxes: list[dict] = []
    pages: dict[int, dict] = {}
    for mark in marks:
        field = str(mark.get("field") or "")
        page_no = int(mark.get("page") or 0)
        if page_no >= doc.page_count:
            page_no = 0
        page = doc[page_no]
        pages[page_no] = {"width": round(page.rect.width, 1), "height": round(page.rect.height, 1)}
        target = field_map.get(field)
        column = by_alias.get(str(target)) if target is not None else None
        x0 = float(column["x0"]) if column and column.get("x0") is not None else float(mark.get("x", 0)) - 40
        x1 = float(column["x1"]) if column and column.get("x1") is not None else float(mark.get("x", 0)) + 40
        y0 = float(mark.get("y", 0)) - 12
        y1 = float(mark.get("y", 0)) + 12
        if target is not None and str(target):
            # search_for 返回的是「未旋转」坐标，必须乘 rotation_matrix 才能和列坐标（显示坐标）对齐
            matrix = page.rotation_matrix
            for found in page.search_for(str(target))[:1]:
                rect = found * matrix
                y0 = max(0.0, rect.y0 - 6)
                y1 = max(rect.y1 + 6, page.rect.height - 24)
        boxes.append({
            "field": field,
            "column": str(target) if target is not None else "",
            "page": page_no,
            "x0": round(x0, 1), "y0": round(y0, 1),
            "x1": round(x1, 1), "y1": round(y1, 1),
        })
    doc.close()
    return {"pages": pages, "page_count": len(pages) or 1, "boxes": boxes}


def render_page_png(pdf_bytes: bytes, layout: dict, page_no: int, dpi: int = 140) -> bytes:
    """在指定页上画出标注框与字段名，返回 PNG 字节。"""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    if page_no >= doc.page_count:
        page_no = 0
    page = doc[page_no]
    for index, box in enumerate(layout.get("boxes") or []):
        if int(box.get("page", 0)) != page_no:
            continue
        color = _color(index)
        rect = pymupdf.Rect(float(box["x0"]), float(box["y0"]), float(box["x1"]), float(box["y1"]))
        page.draw_rect(rect, color=color, width=1.6)
        label = str(box.get("field") or "") + (("←" + str(box["column"])) if box.get("column") else "")
        page.insert_text((rect.x0, max(8.0, rect.y0 - 3)), label, fontsize=7.5, color=color)
    pix = page.get_pixmap(dpi=dpi)
    data = pix.tobytes("png")
    doc.close()
    return data
