# preread（预读，兼容实现）

能力名：`preread.algorithm_compat` · 产出 `profile` · 依赖 `document`

判断这份文件是什么：载体（电子/图片/截图）、页数、有无文本层、银行、账期、是不是流水。
当前复用封存版本的 `run_preread`。

## 为什么还留着它

它给出的载体判定决定后面所有层的权重（影像件载体层会降权），所以先用经过验证的实现，
等版式能力能独立判断「像不像流水」之后再替换。替换点在 `layout` 能力就位之后。

## 测试

由 `rc_platform/tests/test_parity_compat.py` 与管线级测试覆盖。