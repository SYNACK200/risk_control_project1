# verify_layer_ledger（账务层）

能力名：`verify.ledger_layer` · 产出 `layer_ledger` · 依赖 `statement`

借贷平衡、结息反算、结息日规律、利息税、费用规律、到账时延、期末余额、透支冻结。
缺利率表/清算时间表/期末余额时按「跳过」处理，不猜。

## 选项

它是 `verify.compose` 的可选依赖：本行没有账务口径时可以不装这个能力，结论照出、该层 skipped。

## 测试

由 `verify_compose/tests/` 覆盖；判据细节见封存版本的 `test_ledger_layer`。