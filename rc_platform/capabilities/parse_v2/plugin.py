"""解析能力（M2 自有实现）：按新版式切行切值。

与 M2 上半程的对照实现（借旧解析器 L1）相比，这一版自己完成切行与取值：
列边界来自锚点扩散长出的包络，切值用的就是同一份几何，不再出现「边界一套、取值另一套」。
"""
from __future__ import annotations

from ...core.contracts import LayoutPlan, Statement
from ...core.registry import capability
from ..layout.words import read_pages
from .table_reader import read_statement


@capability
class LayoutDrivenParser:
    """按新版式切行切值。"""

    name = "parse.layout_v2"
    version = "2.0"
    provides = "statement"
    requires = ("document", "layout")
    priority = 5

    def run(self, ctx, inputs) -> Statement:
        layout: LayoutPlan = inputs["layout"]
        if not layout.regions:
            raise RuntimeError("版式为空，无法切行切值")
        pages = read_pages(inputs["document"].data)
        statement = read_statement(pages, layout)
        if not statement.rows:
            raise RuntimeError("版式有区域但一行都没切出来")
        ctx.logger.info("切行切值：%d 笔，%d 条告警", len(statement.rows), len(statement.warnings))
        return statement
