"""上传后预读取：不看模板，只读全文，判断「是不是流水」并抓基础信息。

为什么单独一层：模板提取依赖字段映射，模板不完善或版式变异时会错；
预读取只用全文关键词与行模式，因此可作为「模板抽取是否可信」的对照。
输出只含脱敏字段，不落库完整账号与姓名。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf

BANK_ALIASES: tuple[tuple[str, str], ...] = (
    ("中国工商银行", "ICBC"), ("工商银行", "ICBC"),
    ("中国建设银行", "CCB"), ("建设银行", "CCB"),
    ("中国农业银行", "ABC"), ("农业银行", "ABC"),
    ("中国银行", "BOC"), ("中国交通银行", "BOCOM"), ("交通银行", "BOCOM"),
    ("招商银行", "CMB"), ("中国邮政储蓄银行", "PSBC"), ("邮储银行", "PSBC"),
    ("浦发银行", "SPDB"), ("中信银行", "CITIC"), ("民生银行", "CMBC"),
    ("兴业银行", "CIB"), ("光大银行", "CEB"), ("平安银行", "PAB"),
)

STATEMENT_TOKENS = (
    "交易明细", "对账单", "账户明细", "历史明细", "流水",
    "交易日期", "记账日期", "交易日", "摘要", "余额", "借方", "贷方",
    "收入金额", "支出金额", "交易金额", "发生额",
)

IRRELEVANT_TOKENS = (
    "身份证", "营业执照", "劳动合同", "租房合同", "借款合同", "发票",
    "成绩单", "简历", "学位证", "毕业证", "保单", "授权书", "申请表",
)

DATE_RE = re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})")
AMOUNT_RE = re.compile(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|[-+]?\d+\.\d{2}")
ACCOUNT_RE = re.compile(r"(?:账号|账户|卡号|户号)\s*[:：]?\s*([\d ]{8,32})")
HOLDER_RE = re.compile(r"(?:户名|姓名|账户名称|客户名称)\s*[:：]?\s*([^\s：:，,]{2,16})")
PERIOD_RE = re.compile(
    r"(?:对账|查询|交易|统计)期间\s*[:：]?\s*"
    r"(20\d{2}[-/年.]\d{1,2}[-/月.]\d{1,2})\s*(?:至|~|-|—|到)\s*"
    r"(20\d{2}[-/年.]\d{1,2}[-/月.]\d{1,2})"
)


@dataclass
class PrereadResult:
    verdict: str  # accept / review / reject
    is_statement: bool
    confidence: float
    bank_name: str | None = None
    bank_code: str | None = None
    account_masked: str | None = None
    holder_masked: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    pages: int = 0
    has_text_layer: bool = False
    text_chars: int = 0
    keyword_hits: list[str] = field(default_factory=list)
    irrelevant_hits: list[str] = field(default_factory=list)
    txn_like_rows: int = 0
    amounts_found: int = 0
    date_hits: int = 0
    sample_rows: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "is_statement": self.is_statement,
            "confidence": round(self.confidence, 3),
            "bank_name": self.bank_name,
            "bank_code": self.bank_code,
            "account_masked": self.account_masked,
            "holder_masked": self.holder_masked,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "pages": self.pages,
            "has_text_layer": self.has_text_layer,
            "text_chars": self.text_chars,
            "keyword_hits": self.keyword_hits,
            "irrelevant_hits": self.irrelevant_hits,
            "txn_like_rows": self.txn_like_rows,
            "amounts_found": self.amounts_found,
            "date_hits": self.date_hits,
            "sample_rows": self.sample_rows,
            "reasons": self.reasons,
        }


def _norm_date(text: str) -> str:
    m = DATE_RE.search(text)
    if not m:
        return ""
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def _mask_account(raw: str) -> str:
    digits = re.sub(r"\s", "", raw)
    if len(digits) <= 4:
        return "*" * len(digits)
    return "*" * (len(digits) - 4) + digits[-4:]


def _mask_name(name: str) -> str:
    name = name.strip()
    if not name:
        return ""
    if len(name) == 1:
        return "*"
    return name[0] + "*" * (len(name) - 1)


def run_preread(raw: bytes, password: str | None = None) -> PrereadResult:
    """全文预读；不解密以外的任何猜测都写进 reasons，不静默。"""
    try:
        doc = pymupdf.open(stream=raw, filetype="pdf")
    except Exception as exc:
        return PrereadResult(verdict="reject", is_statement=False, confidence=0.0,
                             reasons=[f"文件无法作为 PDF 打开：{exc}"])
    if doc.needs_pass:
        if not password or not doc.authenticate(password):
            doc.close()
            return PrereadResult(verdict="review", is_statement=False, confidence=0.0,
                                 reasons=["文件已加密且未提供有效口令，预读未执行"])
    pages = doc.page_count
    texts = [page.get_text() or "" for page in doc]
    # 版面重组：按 y 坐标聚行，避免每个单元格被拆成独立一行
    rebuilt: list[str] = []
    for page in doc:
        words = page.get_text("words") or []
        buckets: dict[int, list[tuple[float, str]]] = {}
        for x0, y0, _x1, _y1, word, *_rest in words:
            if not word.strip():
                continue
            key = int(round(y0 / 4.0))
            buckets.setdefault(key, []).append((x0, word))
        for key in sorted(buckets):
            line = " ".join(w for _x, w in sorted(buckets[key], key=lambda item: item[0]))
            if line.strip():
                rebuilt.append(line)
    doc.close()
    joined = "\n".join(texts)
    layout_text = "\n".join(rebuilt) if rebuilt else joined
    chars = len(joined.strip())
    has_text = chars > 50

    keyword_hits = [t for t in STATEMENT_TOKENS if t in joined]
    irrelevant_hits = [t for t in IRRELEVANT_TOKENS if t in joined]

    rows = 0
    amounts = 0
    date_hits = len(DATE_RE.findall(joined))
    sample_rows: list[str] = []
    dates: list[str] = []
    for line in layout_text.splitlines():
        line = line.strip()
        if not line:
            continue
        day = _norm_date(line)
        if not day:
            continue
        dates.append(day)
        found = AMOUNT_RE.findall(line)
        if found:
            rows += 1
            amounts += len(found)
            if len(sample_rows) < 3:
                sample_rows.append(line[:60])

    bank_name = bank_code = None
    for alias, code in BANK_ALIASES:
        if alias in joined:
            bank_name, bank_code = alias, code
            break

    account = ACCOUNT_RE.search(joined)
    holder = HOLDER_RE.search(joined)
    period = PERIOD_RE.search(joined)
    if period:
        p_start, p_end = _norm_date(period.group(1)), _norm_date(period.group(2))
    elif dates:
        p_start, p_end = min(dates), max(dates)
    else:
        p_start = p_end = None

    reasons: list[str] = []
    is_statement = (len(keyword_hits) >= 3) or (rows >= 10 and ("余额" in joined or "金额" in joined))
    if not has_text:
        reasons.append("无文字层，预读只能依据文件名与页数，需 OCR 后才能判断")
    if not is_statement:
        reasons.append(f"未命中流水特征（关键词 {len(keyword_hits)} 个、疑似明细行 {rows} 行）")
    if irrelevant_hits:
        reasons.append("命中无关文件特征：" + "、".join(irrelevant_hits[:4]))

    confidence = min(1.0, 0.25 * len(keyword_hits) + 0.4 * min(1.0, rows / 20))
    if not has_text:
        confidence = min(confidence, 0.3)

    if not has_text:
        verdict = "review"
    elif is_statement and not irrelevant_hits and rows >= 5:
        verdict = "accept"
    elif is_statement:
        verdict = "review"
    else:
        verdict = "reject"

    return PrereadResult(
        verdict=verdict,
        is_statement=is_statement,
        confidence=confidence,
        bank_name=bank_name,
        bank_code=bank_code,
        account_masked=_mask_account(account.group(1)) if account else None,
        holder_masked=_mask_name(holder.group(1)) if holder else None,
        period_start=p_start,
        period_end=p_end,
        pages=pages,
        has_text_layer=has_text,
        text_chars=chars,
        keyword_hits=keyword_hits,
        irrelevant_hits=irrelevant_hits,
        txn_like_rows=rows,
        amounts_found=amounts,
        date_hits=date_hits,
        sample_rows=sample_rows,
        reasons=reasons,
    )

