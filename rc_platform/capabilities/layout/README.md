# layout（版式）

能力名：`layout.anchor_spread` · 产出 `layout` · 依赖 `document` + `profile` · 可选：OCR 取词

从页面自己长出表格结构：锚点扩散为主、几何聚类兜底、表头位置保底，每页一份结论，不依赖模板。

## 三档回落

| 档 | 触发 | 置信 |
| --- | --- | --- |
| anchor_spread | 表头认出 >=2 个字段，且顺着 y 能长出 >=3 行 | 0.9+ |
| geometry | 表头不可用，但有「连续多行、含日期与金额」的表格段 | 0.55~0.85 |
| header_only | 数据行不足（短页/末页），只有表头可用 | 0.45~0.65 |

## 配置

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `layout.ocr` | false | 文本层为空时是否渲染后 OCR 取词（单页约 7 秒） |
| `layout.ocr_dpi` | 200 | OCR 渲染分辨率 |
| `layout.deskew` | true | 是否对明显倾斜的件做坐标校正 |
| `layout.deskew_min_angle` | 0.75 | 小于这个角度视作噪声不动 |

## 什么时候会产出空结论

图片件且 `layout.ocr` 关闭；或整页没有任何可用词。空结论不算失败，下游解析会因此跳过并标记降级。

## 测试

`tests/`：版式检测（四种版式关键列）、劣质件（倾斜/拼页/低分辨率 OCR）。
调试用 `python -m rc_platform.capabilities.layout.debug <pdf>`。