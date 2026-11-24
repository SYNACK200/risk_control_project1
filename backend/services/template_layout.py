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

    # 输出新格式（tables + columns）。
    # 之前这里返回的是旧的 boxes 结构，而解析（table.build_columns）和前端画布
    # 都按 tables[].columns[] 读——结果新模板的 layout 永远被当成空的，
    # 「按框解析」和「改框画范围能看到框」都失效。
    tables_out: list[dict] = []
    for page_no, _meta in pages.items():
        page_boxes = [b for b in boxes if b["page"] == page_no]
        if not page_boxes:
            continue
        page = None
        doc2 = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        try:
            if page_no < doc2.page_count:
                page = doc2[page_no]
        except Exception:  # noqa: BLE001
            page = None
        W = float(page.rect.width) if page is not None else 1.0
        H = float(page.rect.height) if page is not None else 1.0
        try:
            if page is not None:
                doc2.close()
        except Exception:  # noqa: BLE001
            pass

        xs0 = [b["x0"] for b in page_boxes]
        xs1 = [b["x1"] for b in page_boxes]
        ys = [b["y0"] for b in page_boxes]
        area_x = max(0.0, min(xs0) / W - 0.01)
        area_x1 = min(1.0, max(xs1) / W + 0.01)
        area_y = max(0.0, min(ys) / H - 0.01)
        cols = []
        for b in page_boxes:
            if not b.get("column"):
                continue
            cx = max(0.0, b["x0"] / W)
            cw = max(0.004, (b["x1"] - b["x0"]) / W)
            cols.append({"field": b["field"], "fields": [b["field"]] if b["field"] else [],
                         "x": round(cx, 4), "w": round(min(1.0 - cx, cw), 4)})
        cols.sort(key=lambda c: c["x"])
        tables_out.append({
            "page": page_no,
            "slot": "first" if page_no == 0 else "middle",
            "area": {"x": round(area_x, 4), "y": round(area_y, 4),
                     "w": round(max(0.01, area_x1 - area_x), 4),
                     "h": round(max(0.05, 0.98 - area_y), 4)},
            "headerY": round(area_y + 0.01, 4),
            "columns": cols,
        })

    page_size = None
    if pages:
        first = pages[sorted(pages)[0]]
        page_size = {"w": first["width"], "h": first["height"]}

    return {"page_size": page_size, "page_count": len(pages) or 1,
            "tables": tables_out,
            # 保留旧字段，避免老代码读不到
            "pages": pages, "boxes": boxes}


def _open_as_pdf(data: bytes) -> pymupdf.Document:
    if b"%PDF-" in data[:1024]:
        return pymupdf.open(stream=data, filetype="pdf")
    # 图片样本（PNG/JPG）封装为单页 PDF，统一复用画框与 PNG 导出逻辑
    pix = pymupdf.Pixmap(data)
    doc = pymupdf.open()
    page = doc.new_page(width=float(pix.width), height=float(pix.height))
    page.insert_image(page.rect, stream=data)
    return doc


def _draw_label(page: pymupdf.Page, x: float, y: float, text: str, color: tuple[float, float, float]) -> None:
    if not text:
        return
    try:
        page.insert_text((x, y), text, fontsize=7.5, color=color, fontname="china-ss")
    except Exception:  # noqa: BLE001
        page.insert_text((x, y), text, fontsize=7.5, color=color)


def render_page_png(pdf_bytes: bytes, layout: dict, page_no: int, dpi: int = 140) -> bytes:
    """在指定页上画出标注框与字段名（兼容新版 tables/meta_boxes 与旧版 boxes），返回 PNG 字节。"""
    doc = _open_as_pdf(pdf_bytes)
    try:
        if page_no < 0 or page_no >= doc.page_count:
            page_no = 0
        page = doc[page_no]
        W, H = float(page.rect.width), float(page.rect.height)
        tables = list(layout.get("tables") or [])
        meta_boxes = list(layout.get("meta_boxes") or [])
        drew_modern = False

        # 新版结构：表格区（紫色）+ 表头线（琥珀）+ 列带（多色）
        page_tables = [t for t in tables if int(t.get("page", 0)) == page_no]
        if not page_tables and page_no == 0 and tables:
            # 只有按 slot 建的模板但页码未严格匹配时，首页至少展示 first/首个表格定义
            page_tables = [t for t in tables if t.get("slot") in ("first", "auto", None)] or [tables[0]]
        for t in page_tables:
            drew_modern = True
            area = t.get("area") or {}
            ax = float(area.get("x", 0.02)) * W
            ay = float(area.get("y", 0.15)) * H
            aw = float(area.get("w", 0.96)) * W
            ah = float(area.get("h", 0.75)) * H
            area_rect = pymupdf.Rect(ax, ay, min(W, ax + aw), min(H, ay + ah))
            page.draw_rect(area_rect, color=(0.49, 0.23, 0.93), width=1.4, dashes="[4 3]")
            _draw_label(page, area_rect.x0 + 2, max(10.0, area_rect.y0 - 3), "表格区", (0.49, 0.23, 0.93))

            hy = t.get("headerY")
            if hy is not None:
                y_line = float(hy) * H
                page.draw_line((area_rect.x0, y_line), (area_rect.x1, y_line), color=(0.85, 0.55, 0.10), width=1.4)

            for index, col in enumerate(t.get("columns") or []):
                color = _color(index)
                cx = float(col.get("x", 0)) * W
                cw = float(col.get("w", 0.05)) * W
                col_rect = pymupdf.Rect(cx, area_rect.y0, min(W, cx + cw), area_rect.y1)
                page.draw_rect(col_rect, color=color, width=1.6)
                field_name = col.get("field") or ",".join(col.get("fields") or [])
                _draw_label(page, col_rect.x0 + 2, max(12.0, col_rect.y0 + 10), str(field_name), color)

        mb_one_based = (
            layout.get("page_base") == 1
            or (bool(meta_boxes) and not tables and min(int(m.get("page", 0)) for m in meta_boxes) >= 1)
        )
        for index, mb in enumerate(meta_boxes):
            mb_page = int(mb.get("page", 0)) - (1 if mb_one_based else 0)
            if mb_page != page_no:
                continue
            drew_modern = True
            mx = float(mb.get("x", 0)) * W
            my = float(mb.get("y", 0)) * H
            mw = float(mb.get("w", 0.1)) * W
            mh = float(mb.get("h", 0.03)) * H
            mrect = pymupdf.Rect(mx, my, min(W, mx + mw), min(H, my + mh))
            page.draw_rect(mrect, color=(0.06, 0.58, 0.52), width=1.5, dashes="[3 2]")
            _draw_label(page, mrect.x0, max(10.0, mrect.y0 - 2), str(mb.get("label") or mb.get("field") or ""), (0.06, 0.58, 0.52))

        if not drew_modern:
            for index, box in enumerate(layout.get("boxes") or []):
                if int(box.get("page", 0)) != page_no:
                    continue
                color = _color(index)
                rect = pymupdf.Rect(float(box["x0"]), float(box["y0"]), float(box["x1"]), float(box["y1"]))
                page.draw_rect(rect, color=color, width=1.6)
                label = str(box.get("field") or "") + (("←" + str(box["column"])) if box.get("column") else "")
                _draw_label(page, rect.x0, max(8.0, rect.y0 - 3), label, color)

        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    finally:
        doc.close()