# parse（解析，兼容实现）

能力名：`parse.algorithm_compat` · 产出 `statement` · 依赖 `document` + `profile`

用封存版本的三级保底解析（模板 L1 → 行容差 L1' → 通用 L2）读明细，
把结果搬进契约 `Statement`。M2 起作为**对照实现**保留（priority 10，默认仍走它）。

## 什么时候会被替换

`--parse parse.layout_v2` 或在 `overrides` 里指定 `statement` 时，走新版式驱动的解析。
两条路在 9 份样本上结论完全一致（见 `tools/parity`）。

## 测试

由 `rc_platform/tests/test_parity_compat.py` 覆盖（与封存版 production 入口逐项比对）。