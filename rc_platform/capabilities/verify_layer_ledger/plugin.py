"""账务层（可插拔核验层之一）：借贷平衡、结息反算、期末余额。"""
from __future__ import annotations

from ...compat.native import layer_result, parsed_from_statement
from ...core.paths import ensure_root_on_path
from ...core.registry import capability

ensure_root_on_path()


@capability
class LedgerLayer:
    name = "verify.ledger_layer"
    version = "1.0"
    provides = "layer_ledger"
    requires = ("statement",)
    priority = 0

    def run(self, ctx, inputs):
        from algorithm.algo.ledger_layer import analyze_ledger

        native = analyze_ledger(parsed_from_statement(inputs["statement"]).transactions)
        return layer_result(native, "ledger")
