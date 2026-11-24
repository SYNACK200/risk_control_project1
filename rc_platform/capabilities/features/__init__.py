"""特征衍生包：算子库 + 两种作者形态 + 内置特征。

对外只用三样东西：compute()（算特征）、FeatureDef（写定义）、describe()（看算子目录）。

注意最后那行 library 导入：它负责把全部算子注册进全局表（数值/逻辑/分组/时间窗/过滤/
数学微积分/行级与分布谓词/文本词库）。少了它，只 import expr 的调用方会得到「未知算子」。
"""
from __future__ import annotations

from .defs import BUILTIN_FEATURES, FeatureDef, FeatureDefError, compute
from .operators import Frame, OperatorError, UnknownColumn, UnknownOperator, describe, families

from . import library  # noqa: E402,F401  必须放在最后：library 依赖上面的模块
