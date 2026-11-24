"""报告能力（兼容实现）：把五态、指标、证据聚合成报告载荷。

M4 起报告拆成可插拔的报告块（结论摘要 / 资金全景 / 四层明细 / 证据 / 导出），
本能力保留为「旧结构对照」。
"""
from __future__ import annotations

import json

from ...compat.native import parsed_from_statement
from ...core.contracts import ReportBundle
from ...core.paths import ensure_root_on_path
from ...core.registry import capability

ensure_root_on_path()


@capability
class AlgorithmReport:
    """兼容层：用封存版本的 build_report 产出报告载荷。"""

    name = "report.algorithm_compat"
    version = "1.0"
    provides = "report"
    requires = ("profile", "statement", "verification", "metrics")
    priority = 0

    def run(self, ctx, inputs):
        from algorithm.algo.report import build_report

        profile = inputs["profile"]
        statement = inputs["statement"]
        verification = inputs["verification"]
        metric_table = inputs["metrics"]
        parsed = parsed_from_statement(statement)
        transactions = list(parsed.transactions)
        payload = json.loads(
            build_report(
                verification.native,
                metric_table.native,
                carrier=profile.carrier,
                transactions=transactions,
                txn_ids=list(range(1, len(transactions) + 1)),
                materials=[],
                version=1,
            ).model_dump_json()
        )
        return ReportBundle(payload=payload, version=1)
