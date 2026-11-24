# metrics（指标）

能力名：`metrics.algorithm_compat` · 产出 `metrics` · 依赖 `statement`

40 项指标的**当前实现**：直接复用封存版本的 `compute_metrics`，口径与旧系统逐值一致。

## 临时状态

这是过渡实现：M4 下半程要把指标改成「由特征库派生」（一个指标 = 特征 + 权重/阈值），
映射表逐项对照通过之后才允许删掉这里。不合并的代价是同一个概念存在两套实现，
改口径要改两处且没有东西会提醒你漏了。

## 缺输入怎么办

沿用旧口径：返回 `null` 并在 note 写明缺什么，不填 0、不估算。

## 测试

由 `rc_platform/tests/test_parity_compat.py` 与 `tools/parity` 覆盖：40 项指标逐值与封存版比对。