"""指标能力（兼容实现）：40 项指标。

M3 起指标改由特征库派生（指标 = 若干特征的组合），届时本能力降为「旧口径对照」。
"""
from __future__ import annotations

from ...compat.native import parsed_from_statement
from ...core.contracts import MetricItem, MetricTable
from ...core.paths import ensure_root_on_path
from ...core.registry import capability

ensure_root_on_path()


@capability
class AlgorithmMetrics:
    """兼容层：用封存版本的 compute_metrics 算 40 项指标。"""

    name = "metrics.algorithm_compat"
    version = "1.0"
    provides = "metrics"
    requires = ("statement",)
    priority = 0

    def run(self, ctx, inputs):
        from algorithm.algo.metrics import compute_metrics

        parsed = parsed_from_statement(inputs["statement"])
        result = compute_metrics(parsed.transactions)
        return MetricTable(
            items=[
                MetricItem(
                    code=m.code,
                    name=m.name,
                    value=m.value,
                    unit=m.unit,
                    note=m.note,
                    caliber_version=getattr(m, "caliber_version", 1),
                )
                for m in result.metrics
            ],
            set_version=getattr(result, "metric_set_version", 1),
            native=result,
        )
