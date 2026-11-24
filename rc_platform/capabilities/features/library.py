"""特征 Lab 的目录：算子清单 + 内置特征清单。

调用方（API 与前端）只认这里的两个函数，不直接读算子表与 defs，
这样「有哪些算子、有哪些内置特征」只有一处答案。
"""
from __future__ import annotations

from . import operators as ops
from . import math_ops  # noqa: F401  注册数学与微积分算子
from . import predicates  # noqa: F401  注册行级/分布级比较（mask）算子
from . import text_ops  # noqa: F401  注册文本比较（contains/matches/词库）算子
from .defs import BUILTIN_FEATURES, FeatureDef, builtin_features
from ..metrics import ops_metrics  # noqa: F401  注册指标口径算子（覆盖月、日终余额、分组二次聚合）


def operator_catalog() -> list[dict]:
    out = []
    for key, spec in sorted(ops.operators().items()):
        out.append({
            "key": key,
            "family": spec.family,
            "kind": spec.kind,
            "unit": spec.unit,
            "detail": spec.detail,
            "params": spec.params,
        })
    return out


def feature_catalog() -> list[dict]:
    return [item.describe() for item in builtin_features()]


def lexicon_catalog() -> list[dict]:
    from . import lexicon

    return lexicon.catalog()


def find_feature(code: str) -> FeatureDef | None:
    for item in BUILTIN_FEATURES:
        if item.code == code:
            return item
    return None
