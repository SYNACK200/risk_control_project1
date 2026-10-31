"""真实性校验逐项定义：每个检查点「怎么验」的单一事实源。

编码与各层实现一一对应：F1–F11 载体层、C1–C4 内容层、A1–A7 账务层、
E1–E7 外部层、S0–S7 识别自检。通过情况由各层运行时产出，不在本文件写死。
"""
from __future__ import annotations

_ROWS: tuple[tuple[str, str, str], ...] = (
    ("F1", "file", "读 PDF 元数据的 Producer/Creator/Author，与同版式真件基线比对；缺失记 partial，与基线不符记 fail"),
    ("F2", "file", "比较 CreationDate 与 ModDate 的先后与合理性；缺失记 partial"),
    ("F3", "file", "统计 %%EOF / startxref 出现次数与 /Prev 链，判断是否有增量更新；多次更新记 fail"),
    ("F4", "file", "与同银行同版式的真件基线比对页尺寸、字体族、每页字节数；无基线记 skipped"),
    ("F5", "file", "检查字体是否嵌入或为标准 14 字体；出现非嵌入的非标准字体记 fail"),
    ("F6", "file", "逐页提取文字层字符数，判断能否作为电子件；无文字层记 skipped 并转影像件"),
    ("F7", "file", "检查整页是否位图、位图覆盖比例与 DPI；整页位图说明是扫描件"),
    ("F8", "file", "检查 /Sig 字段、PAdES 签名与 DocTimeStamp；无签名记 skipped"),
    ("F9", "file", "检查页面尺寸、旋转角与页数是否在本版式允许范围内"),
    ("F10", "file", "与基线比较每页字节密度（bytes/page）；无基线记 skipped"),
    ("F11", "file", "检查整页单图覆盖、矢量层是否被栅格化等图像/矢量合理性"),
    ("C1", "content", "逐笔验算 上一笔余额 + 本笔金额 = 本笔余额，断点即 fail"),
    ("C2", "content", "把每页声明的合计与明细求和比对；未取到声明记 skipped"),
    ("C3", "content", "把页脚声明的总笔数与解析笔数比对"),
    ("C4", "content", "把文件声明的期初/期末余额与明细首尾余额比对"),
    ("A1", "ledger", "用挂牌利率与日均余额反算应得利息，与实际利息入账比对"),
    ("A2", "ledger", "检查结息日是否落在规则日（季末 20 日等）"),
    ("A3", "ledger", "检查利息税与利息的比率是否符合当期规则"),
    ("A4", "ledger", "检查账户管理费、短信费等是否为标准金额"),
    ("A5", "ledger", "需交易时分与清算时间表；当前无该输入，恒为不可算"),
    ("A6", "ledger", "把声明的期末余额与最后一笔余额比对"),
    ("A7", "ledger", "检查余额为负是否在允许范围、是否与冻结状态冲突"),
    ("E1", "external", "调用网银或官方回单渠道核验流水真伪；需客户授权"),
    ("E2", "external", "机构间函证，核对对方账户的对账单"),
    ("E3", "external", "征信报告中的贷款与信用卡记录，与流水还款比对"),
    ("E4", "external", "社保/个税申报收入与工资入账比对；需客户授权"),
    ("E5", "external", "本行代发记录与工资入账比对；需本行接口"),
    ("E6", "external", "同一账户其他时段或同一人在他行的流水交叉互证"),
    ("E7", "external", "验证电子签章证书链与有效期"),
    ("S0", "self", "判断是否解析出任何明细；无明细直接 inconsistent"),
    ("S1", "self", "抽取的金额能否在页面文本中定位，占比 ≥99% 记 pass"),
    ("S2", "self", "抽取的日期能否在页面文本中定位，占比 ≥99% 记 pass"),
    ("S3", "self", "抽取的余额能否在页面文本中定位，占比 ≥99% 记 pass"),
    ("S4", "self", "逐笔金额在第二引擎（pdfplumber/OCR）中是否可定位"),
    ("S5", "self", "解析笔数与页脚声明的总笔数是否一致"),
    ("S6", "self", "相邻笔余额链是否无断点"),
    ("S7", "self", "每笔的收/支方向是否齐全"),
    ("S8", "self", "不看模板、只读全文的预读结果与模板解析互证：明细行数容差内、期间不矛盾；任一不符记 limited"),
)

LAYER_LABELS = {
    "file": "载体层",
    "content": "内容层",
    "ledger": "账务层",
    "external": "外部层",
    "self": "识别自检",
}

_INDEX = {row[0]: {"code": row[0], "layer": row[1], "method": row[2]} for row in _ROWS}


def verification_definitions() -> list[dict]:
    """36 个检查点的编码、所属层与检验方法。"""
    return [dict(_INDEX[code]) for code in _INDEX]


def method_of(code: str) -> str:
    return _INDEX.get(code, {}).get("method", "")

