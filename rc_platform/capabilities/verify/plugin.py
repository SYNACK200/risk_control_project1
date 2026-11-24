"""核验能力（兼容实现）：四层核验 + 五态合成。

四层各留原判据不动：C1/C2/C3 一票否决的成因区分（data vs recognition）是业务资产，
迁移只换容器不换判据。核验失败一律走 degrade：不可算 != 通过。
"""
from __future__ import annotations

from ...compat.native import parsed_from_statement
from ...core.contracts import LayerOutcome, Verification
from ...core.paths import ensure_root_on_path
from ...core.registry import capability

ensure_root_on_path()


@capability
class AlgorithmVerifier:
    """兼容层：用封存版本的四层核验与五态合成出结论。"""

    name = "verify.algorithm_compat"
    version = "1.0"
    provides = "verification"
    requires = ("document", "profile", "statement")
    priority = 0   # M4 起默认走 verify.compose（四层可插拔），这个保留作对照

    def run(self, ctx, inputs):
        from algorithm.algo.content_layer import analyze_content
        from algorithm.algo.external_layer import ExternalContext, analyze_external
        from algorithm.algo.file_layer import analyze_file
        from algorithm.algo.ledger_layer import analyze_ledger
        from algorithm.algo.verdict import conclude

        doc = inputs["document"]
        profile = inputs["profile"]
        statement = inputs["statement"]
        parsed = parsed_from_statement(statement)

        file_layer = analyze_file(doc.data, carrier=profile.carrier)
        content_layer = analyze_content(parsed)
        ledger = analyze_ledger(parsed.transactions)
        external = analyze_external(ExternalContext(transactions=parsed.transactions))
        verdict = conclude(
            content_layer,
            carrier=profile.carrier,
            file_layer=file_layer,
            ledger=ledger,
            external=external,
        )

        return Verification(
            verdict=verdict.verdict,
            verdict_reason=verdict.verdict_reason,
            layers=[
                LayerOutcome(
                    layer=layer.layer,
                    status=layer.status,
                    detail=layer.detail,
                    checks=[c.model_dump() for c in layer.checks],
                )
                for layer in verdict.layers
            ],
            trust=verdict.trust.model_dump() if verdict.trust else {},
            evidence=[e.model_dump() for e in verdict.evidence],
            limitations=list(verdict.limitations),
            native=verdict,
        )
