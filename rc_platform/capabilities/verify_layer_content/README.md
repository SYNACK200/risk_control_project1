# verify_layer_content（内容层）

能力名：`verify.content_layer` · 产出 `layer_content` · 依赖 `statement`

C1 余额链、C2 每页合计、C3 笔数、C4 期初期末、C5 表头跨页一致、C6 参考号、C7 时间分布、
C8 金额形态、C9 语义匹配、C10 重复记录。

## 最不能动的一条

C1/C2/C3 是**一票否决项**，且必须保留成因区分：
数据自身矛盾（`cause=data`）→ 直接 inconsistent；字没认准（`cause=recognition`）→ 只判 undetermined。
把两者合并会把「字没认准」误判成「流水造假」。有两条测试守着这条口径。

## 测试

由 `verify_compose/tests/` 与封存版本的 `test_content_layer` 系列共同覆盖（判据未改）。