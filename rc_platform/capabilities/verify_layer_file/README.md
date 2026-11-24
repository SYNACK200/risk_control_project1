# verify_layer_file（载体层）

能力名：`verify.file_layer` · 产出 `layer_file` · 依赖 `document` + `profile`

文件级取证：生成器、创建修改时间、增量更新、结构指纹、字体、隐藏文字、覆盖图元、签名、版面、体量、图像混排。
判据复用封存版本，本能力只负责把它接进可插拔的层结构。

## 什么时候会被跳过

图片件与截图件不做结构取证（没有 PDF 结构可查），该层会给出 `skipped` 并写限制。

## 测试

由 `verify_compose/tests/test_layers.py` 覆盖（四层齐全 / 停用 / 替换）。