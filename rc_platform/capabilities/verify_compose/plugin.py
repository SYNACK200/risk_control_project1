"""五态合成（可插拔核验层的组装点）。

它只做两件事：把四层结果交给五态规则、把结果转成契约。
判据一行都不抄：抄一遍就等于又开一套口径。

某层缺 native 时直接报错而不是硬凑——内容层的成因区分要靠原生检查对象，
凑出来的结论会把「字没认准」误判成「流水造假」，这是最不能错的一条。
"""
from __future__ import annotations

from ...compat.native import verification_from_verdict
from ...core.paths import ensure_root_on_path
from ...core.registry import capability

ensure_root_on_path()


@capability
class VerifyCompose:
    """四层 -> 五态。层可以单独停用（缺契约时编排会跳过它）。"""

    name = "verify.compose"
    version = "1.0"
    provides = "verification"
    requires = ("document", "profile", "statement", "layer_file", "layer_content")
    # 账务层与外部层可能是「本行没接入」：没有实现时按未执行处理，不该让整单失败
    optional_requires = ("layer_ledger", "layer_external")
    priority = 10

    def run(self, ctx, inputs):
        from algorithm.algo.verdict import conclude

        content = inputs["layer_content"].native
        if content is None:
            raise RuntimeError("内容层没有原生检查对象，无法保住成因区分")

        ledger = inputs.get("layer_ledger")
        external = inputs.get("layer_external")
        native = conclude(
            content,
            carrier=inputs["profile"].carrier,
            file_layer=inputs["layer_file"].native,
            ledger=ledger.native if ledger else None,
            external=external.native if external else None,
        )
        return verification_from_verdict(native)
