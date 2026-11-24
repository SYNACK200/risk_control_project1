"""特征衍生能力：把 Statement 算成 FeatureSet。

为什么它只有十几行：能力层是装配用的插头，口径全在 operators/expr/defs 里。
换一套特征不用动能力，换一个能力也不用改口径——两边各自可以单独验收。
"""
from __future__ import annotations

from ...core.contracts import FeatureSet
from ...core.registry import capability
from .defs import BUILTIN_FEATURES, FeatureDef, FeatureDefError, compute


@capability
class FeatureDerivation:
    """特征衍生：内置特征 + 配置追加的自定义特征，逐条给出值或缺失原因。"""

    name = "features.derivation"
    version = "1.0"
    provides = "features"
    requires = ("statement",)
    priority = 0

    def run(self, ctx, inputs) -> FeatureSet:
        defs = self._defs(ctx)
        result = compute(defs, inputs["statement"], version=self.version)
        filled = sum(1 for record in result.records if record["value"] is not None)
        ctx.logger.info("特征衍生：%d/%d 条有值", filled, len(result.records))
        return result

    def _defs(self, ctx) -> tuple[FeatureDef, ...]:
        """配置可以追加定义（features.defs），也可以只跑一部分（features.only），都不改代码。"""
        defs = list(BUILTIN_FEATURES)
        for index, item in enumerate(ctx.setting("features.defs") or (), 1):
            try:
                defs.append(FeatureDef(**item))
            except (TypeError, FeatureDefError) as exc:
                raise FeatureDefError(f"配置 features.defs 第 {index} 条定义有误：{exc}") from None
        only = ctx.setting("features.only")
        if only:
            wanted = set(only)
            return tuple(definition for definition in defs if definition.code in wanted)
        return tuple(defs)
