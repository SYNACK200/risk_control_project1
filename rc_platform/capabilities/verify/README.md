# verify（核验，整包兼容实现）

能力名：`verify.algorithm_compat` · 产出 `verification` · 依赖 `document` + `profile` + `statement`

一次性跑完四层再合成五态。M4 起**不再默认使用**——默认走 `verify.compose` + 四个层能力，
本能力保留作对照（`overrides={"verification": "verify.algorithm_compat"}`）。

## 什么时候用它

只想「一把梭」验证旧结论时；或者排查「四层拆分是否改变了结果」时。
两者在 9 份样本上结论完全一致（`tools/parity`）。

## 测试

由 `tools/parity` 覆盖；层拆分的行为由 `verify_compose/tests/` 覆盖。