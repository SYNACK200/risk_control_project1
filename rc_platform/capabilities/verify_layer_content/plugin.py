"""内容层（可插拔核验层之一）：C1–C10 与一票否决。

这一层的成因区分（数据断 vs 识别不准）是业务资产，换实现时必须保住。
"""
from __future__ import annotations

from ...compat.native import layer_result, parsed_from_statement
from ...core.paths import ensure_root_on_path
from ...core.registry import capability

ensure_root_on_path()


@capability
class ContentLayer:
    """余额链、页合计、笔数、期初期末、表头一致…"""

    name = "verify.content_layer"
    version = "1.0"
    provides = "layer_content"
    requires = ("statement",)
    priority = 0

    def run(self, ctx, inputs):
        from algorithm.algo.content_layer import analyze_content

        native = analyze_content(parsed_from_statement(inputs["statement"]))
        return layer_result(native, "content")
