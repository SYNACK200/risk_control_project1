"""预读能力（兼容实现）：识别载体、页数、银行与是否加密。

M1 阶段直接复用封存版本的 algorithm.algo.preread；
M2 起由 layout 能力接替，预读只保留「这份文件像不像流水」的判断。
"""
from __future__ import annotations

from ...core.contracts import DocumentProfile
from ...core.paths import ensure_root_on_path
from ...core.registry import capability

ensure_root_on_path()


@capability
class AlgorithmPreread:
    """兼容层：用封存版本的预读识别载体、页数与银行。"""

    name = "preread.algorithm_compat"
    version = "1.0"
    provides = "profile"
    requires = ("document",)
    priority = 0

    def run(self, ctx, inputs):
        from algorithm.algo.preread import run_preread

        doc = inputs["document"]
        result = run_preread(doc.data, password=doc.password)
        return DocumentProfile(
            carrier="electronic" if result.has_text_layer else "image",
            pages=result.pages,
            has_text_layer=result.has_text_layer,
            encrypted=bool(doc.password is not None),
            bank_code=result.bank_code,
            bank_name=result.bank_name,
            period_start=result.period_start,
            period_end=result.period_end,
            is_statement=result.is_statement,
            reasons=list(result.reasons),
            native=result,
        )
