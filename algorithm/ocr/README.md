> 这是什么：OCR 与解析抽取实现 · 谁写：算法组 · 何时更新：实现变化时

# 职责

把合规 PDF 变成结构化明细：日期、摘要、对手方、金额、方向、余额、页码、坐标、置信度。

# 接口

```python
def parse(file_bytes: bytes, template: Template | dict | None) -> ParseResult:
    """返回明细列表与自检三项；不判断真伪。

    template 可为解析模板，也可直接传标注导出（template-spec v1 dict）：
    内部先走 convert_annotation()，转换失败只返回带 T 码的 warnings，不产出半份结果。
    """

class ParseResult(BaseModel):
    transactions: list[Transaction]
    field_completeness: float   # 字段完整率
    avg_confidence: float       # 平均置信度
    low_conf_ratio: float       # 低置信行占比
    page_count: int
    warnings: list[str]

```

# 标注导出 → 解析模板（AL-34）

```python
from algorithm.ocr import convert_annotation, parse

result = convert_annotation(export_dict, pdf_bytes)   # 校验 + 转换
if not result.ok:
    raise SystemExit(result.errors)                   # T001–T009，有错不出模板
parsed = parse(pdf_bytes, result.template)            # 等价于 parse(pdf_bytes, export_dict)
```

| 项 | 做法 |
| --- | --- |
| 列 → 字段 | `tables[].columns` 的 x/w 按页面实际宽度换成点，在 `header_y` 附近找表头行，按横向位置取表头文字作别名；表头指纹能命中时优先按指纹定位（实测招行标注页与脱敏件的表头纵向差 47pt） |
| 无样本兜底 | 没有可读 PDF 或列未定位时，列数与 `match_rule.header_fingerprint` 一致则按顺序映射；仍缺失必需列记 T003 |
| 页眉字段 | `meta_boxes` 转成 `Template.meta_boxes`，`parse()` 优先按框取账号/户名/期间，框内取不到再退回文字标签；其余页眉字段保留在标注中不参与解析 |
| 校验 | T001–T009 阻断，W001–W005 只提示；重复字段按“同一表格内重复列 / 同页重复框”判 T005，跨页同字段按 template-spec 第九节允许 |
| 坐标基准 | `Template.page_size` 取导出 `page_size`，缺失时取样本第 1 页尺寸；影像件词坐标是像素，与模板 pt 差数倍，页眉框自动跳过、改走文字标签 |

# 实现要点

| 项 | 做法 |
| --- | --- |
| 文本抽取 | 电子件优先 PyMuPDF（含页面旋转坐标）；解析不到明细时回退 pdfplumber；影像件用 RapidOCR。均保留坐标 |
| 交叉校验 | PyMuPDF 正文日期数与解析笔数比对，差异超过 1/6 时告警；回退时再比对两引擎页数 |
| 表格重建 | 坐标聚类，不依赖固定列宽；OCR 词与电子件词走同一套 |
| 模板优先 | 本行模板库优先于预置模板库 |
| 兜底 | 都不命中走通用解析 |

# 文字层引擎选择

- PyMuPDF 抽 3000 笔（75 页、10.4 万字符）约 0.8 秒；pdfplumber 基于 pdfminer，同量级约 5 秒，是 AL-17 五秒线的主要瓶颈。
- 以 PyMuPDF 为主：按 span 字号过滤水印与缩印重影，用 `rotation_matrix` 把旋转页坐标转正，词边界交给 PyMuPDF，列重建仍走 `table.py`。
- pdfplumber 保留为回退：PyMuPDF 解析不到明细时再走，并输出「回退 pdfplumber」警告。
- 语义差异：覆盖图元样本中，pdfplumber 会把被白底盖住的旧数字与覆盖后的新数字混读（金额读成 `3`，C1 失败）；PyMuPDF 读到覆盖前的 `300.50`，C1/C2 通过，仍由 F3/F7 判「来源可疑」。伪造检测不依赖内容层的偶然读数。

# OCR 引擎（影像件）

`engine.py` 只负责把图片或整份 PDF 识别成带坐标与置信度的词，表格重建仍由 `table.py` 做。

```python
from algorithm.ocr import RapidOCREngine

result = RapidOCREngine().recognize(file_bytes)
for page in result.pages:
    for word in page.words:
        word.text, word.bbox, word.confidence
```

| 项 | 做法 |
| --- | --- |
| 引擎 | RapidOCR 1.4.4（PP-OCRv4 转 ONNX），模型随包，离线可用 |
| PDF | PyMuPDF 按 200 DPI 渲染后逐页识别；有文字层的电子件不走这里 |
| 坐标 | 四点框转 `(x0, y0, x1, y1)` |
| 置信度 | 原样返回；行置信度取该行词的最小值，写入 `Transaction.confidence` |
| 接入状态 | `parse()` 已接入：JPG/PNG 与无文字层 PDF 自动走 OCR；有文字层的电子件走 PyMuPDF，解析不到明细时回退 pdfplumber |

已知限制：OCR 把日期与摘要并成一框时，日期从整行兜底、摘要去掉日期前缀；整行并成一框会漏行，留待 AL-19。

`onnxruntime` 锁 1.20.1（1.31.1 在本机 import 即段错误）。离线部署时 wheel 与模型需一并预置。

# 不做

- 不做图像增强；影像件只做识别与表格重建，像素级取证归 AL-18。
- 不做真假判断，那是 algo 的事。

