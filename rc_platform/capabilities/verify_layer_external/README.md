# verify_layer_external（外部层）

能力名：`verify.external_layer` · 产出 `layer_external` · 依赖 `statement`

回单验真、跨行调证、征信交叉、社保个税、行内代发、多份互证、签章 CA。
默认全是占位适配器，只返回「未启用」，不编造外部数据。

## 选项

它是 `verify.compose` 的可选依赖，也是「本行没接入」最常见的状态：
不装它，结论照出、该层 skipped、限制里写「外部层未执行」。

## 测试

由 `verify_compose/tests/` 覆盖（停用外部层仍出结论）。