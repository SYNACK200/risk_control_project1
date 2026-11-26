# parse（解析）

能力名：`parse.algorithm_compat`、`parse.layout_v2`、`parse.unified` · 产出 `statement` · 依赖 `document` + `profile`

`parse.algorithm_compat` 用封存版本的三级保底解析（模板 L1 → 行容差 L1' → 通用 L2）读明细，
把结果搬进契约 `Statement`。M2 起作为**对照实现**保留（priority 10，默认仍走它）。

`parse.layout_v2` 用新版式驱动切行切值，供 `overrides` 指定后做对照。

`parse.unified` 是 AL-101 的统一入口：内部调用 `entry.parse_statement()`，
先用 `layout_v2`；日期覆盖率低于 50%，或整页没有明细（页覆盖不足）时，再用旧解析器兜底。
页覆盖是必需的第二个信号：招行 2 页件实测只出第 1 页，日期仍 100%，只看日期发现不了整页丢失。
Lab 与 CLI 都走它。它默认不参与装配（priority 1），避免存量链路被悄悄换掉。

## 什么时候会被替换

`--parse parse.layout_v2` 或在 `overrides` 里指定 `statement` 时，走新版式驱动的解析。
`overrides={"statement": "parse.unified"}` 时走统一入口。前两条路在 9 份样本上结论完全一致（见 `tools/parity`）。

## 测试

`parse.algorithm_compat` 由 `rc_platform/tests/test_parity_compat.py` 覆盖（与封存版 production 入口逐项比对）。
`parse.unified` 由 `rc_platform/capabilities/parse/tests/test_entry.py` 覆盖（rows/PDF/兜底/失败）。