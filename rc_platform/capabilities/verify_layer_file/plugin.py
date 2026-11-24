"""载体层（可插拔核验层之一）：文件级取证。"""
from __future__ import annotations

from ...compat.native import layer_result
from ...core.paths import ensure_root_on_path
from ...core.registry import capability

ensure_root_on_path()


@capability
class FileLayer:
    """PDF 结构取证：生成器、增量更新、字体、隐藏文字、覆盖图元…"""

    name = "verify.file_layer"
    version = "1.0"
    provides = "layer_file"
    requires = ("document", "profile")
    priority = 0

    def run(self, ctx, inputs):
        from algorithm.algo.file_layer import analyze_file

        native = analyze_file(inputs["document"].data, carrier=inputs["profile"].carrier)
        return layer_result(native, "file")
