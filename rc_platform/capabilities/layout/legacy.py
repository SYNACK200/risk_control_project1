"""把新版 LayoutPlan 转成旧版模板 layout 结构。

为什么需要它：M2 阶段还没写自己的表格解析器，先用旧解析器的 L1 通道验证
「新长出来的几何到底对不对」。等新解析器就位，这个转换就可以删。
"""
from __future__ import annotations

from ...core.contracts import LayoutPlan


def to_legacy_layout(plan: LayoutPlan) -> dict | None:
    if not plan.regions or not plan.page_size:
        return None
    tables = []
    for region in plan.regions:
        x, y, w, h = region.area
        tables.append({
            "page": region.page,
            "slot": "first" if region.page == 0 else "middle",
            "area": {"x": x, "y": y, "w": w, "h": h},
            "headerY": region.header_y,
            "columns": [
                {"field": col.field, "fields": [col.field], "x": col.x, "w": col.w}
                for col in region.columns
            ],
        })
    return {
        "page_size": {"w": plan.page_size[0], "h": plan.page_size[1]},
        "page_count": plan.page_count,
        "tables": tables,
    }
