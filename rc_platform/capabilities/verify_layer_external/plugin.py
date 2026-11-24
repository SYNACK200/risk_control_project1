"""外部层（可插拔核验层之一）：默认全是占位适配器，只报「未启用」。"""
from __future__ import annotations

from ...compat.native import layer_result, parsed_from_statement
from ...core.paths import ensure_root_on_path
from ...core.registry import capability

ensure_root_on_path()


@capability
class ExternalLayer:
    name = "verify.external_layer"
    version = "1.0"
    provides = "layer_external"
    requires = ("statement",)
    priority = 0

    def run(self, ctx, inputs):
        from algorithm.algo.external_layer import ExternalContext, analyze_external

        transactions = list(parsed_from_statement(inputs["statement"]).transactions)
        native = analyze_external(ExternalContext(transactions=transactions))
        return layer_result(native, "external")
