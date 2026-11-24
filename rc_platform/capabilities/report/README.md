# report（报告，兼容实现）

能力名：`report.algorithm_compat` · 产出 `report` · 依赖 `profile` + `statement` + `verification` + `metrics`

把五态、四层、指标、趋势、证据、材料聚合成报告载荷。当前复用封存版本的 `build_report`。

## 为什么还是一次调用

M4 还没把报告拆成可插拔块（结论摘要 / 资金全景 / 四层明细 / 证据 / 导出）。
拆开之后银行侧才能按角色裁剪内容；不拆的话每加一个视图都要动同一个函数。

## 测试

由 `tools/parity` 与 `rc_platform/tests/test_parity_compat.py` 覆盖（结论与指标逐值比对）。