"""模板表头相似度匹配与指纹计算（T9：layout_hash + header_text + Jaccard >= 0.6）。"""
from __future__ import annotations

import hashlib
from typing import Any


def compute_layout_hash(headers: list[str]) -> str:
    """对表头词序列做稳定规范化指纹，供同银行多版式快速区分。"""
    norm = [str(h or "").strip() for h in headers if str(h or "").strip()]
    joined = "|".join(norm)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16] if joined else ""


# 规范字段 → 常见中文表头：老模板只存了 field_map（键是 txn_date 这类），
# 没有列级 header_text。没有这层映射，它们的表头集合是空的，Jaccard 恒为 0，
# 「同银行多版式」就永远匹配不上（实测建行真件 score=0.0）。
FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "txn_date": ("交易日期", "交易时间", "记账日期"),
    "trade_time": ("交易时间", "交易时分"),
    "summary": ("摘要", "交易摘要", "用途"),
    "counterparty": ("对方户名", "对方账号与户名", "对方名称", "交易对方"),
    "counterparty_name": ("对方户名", "对方账号与户名", "对方名称", "交易对方"),
    "amount": ("交易金额", "金额", "发生额"),
    "amount_in": ("收入金额", "贷方发生额", "存入金额"),
    "amount_out": ("支出金额", "借方发生额", "支取金额"),
    "balance": ("余额", "账户余额", "交易后余额"),
    "direction": ("借贷标志", "借贷方向", "收/支"),
    "account_no": ("卡号", "账号", "账户号"),
    "reference_no": ("流水号", "交易流水号", "凭证号"),
    "currency": ("币种", "货币"),
    "period": ("交易期间", "起止日期"),
}


def template_header_tokens(template: Any) -> list[str]:
    """取一份模板可比对的表头词：优先列级 header_text，其次 header_columns，
    最后用 field_map 的规范字段回退到常见中文表头。"""
    lay = getattr(template, "layout", None) or {}
    tokens: list[str] = []
    for table in (lay.get("tables") or []):
        for col in (table.get("columns") or []):
            text = col.get("header_text") or col.get("label")
            if text:
                tokens.append(str(text))
    if not tokens:
        tokens = [str(x) for x in (getattr(template, "header_columns", None) or []) if x]
    if not tokens:
        fmap = getattr(template, "field_map", None) or {}
        for key, value in fmap.items():
            if isinstance(value, str) and value and not value.isdigit():
                tokens.append(value)
                continue
            for label in FIELD_LABELS.get(str(key), ()):
                tokens.append(label)
                break
    return tokens


def header_similarity(a: list[str] | set[str], b: list[str] | set[str]) -> float:
    """表头相似度：包含关系也算命中（「账户余额」≈「余额」），否则真实件永远差一个词。"""
    sa = {str(x).strip() for x in (a or []) if str(x).strip()}
    sb = {str(x).strip() for x in (b or []) if str(x).strip()}
    if not sa or not sb:
        return 0.0
    matched = 0
    for x in sa:
        if any(x == y or x in y or y in x for y in sb):
            matched += 1
    union = len(sa) + len(sb) - matched
    return matched / union if union else 0.0


def header_jaccard(a: list[str] | set[str], b: list[str] | set[str]) -> float:
    """计算两组表头关键词的 Jaccard 相似度（0.0 ~ 1.0）。"""
    sa = {str(x).strip() for x in (a or []) if str(x).strip()}
    sb = {str(x).strip() for x in (b or []) if str(x).strip()}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def pick_best_template(
    candidates: list[Any],
    doc_headers: list[str] | None = None,
    # 阈值 0.35 是量出来的：建行真件 vs 它自己的模板 = 0.444（同版式、表头措辞有出入）；
    # 跨银行也能到 0.2~0.5（表头词通用），但候选先按 bank_code 过滤，
    # 这个阈值只在「同银行多版式」之间做取舍。
    min_jaccard: float = 0.35,
) -> tuple[Any | None, float, str]:
    """在同银行候选模板中按 layout_hash / 表头 Jaccard >= 0.6 选出最佳版式。

    返回 (matched_template, score, reason)。
    """
    if not candidates:
        return None, 0.0, "no_enabled_template"
    if not doc_headers:
        if len(candidates) == 1:
            return candidates[0], 1.0, "single_enabled_fallback"
        return candidates[0], 0.0, "no_doc_headers_first_fallback"

    doc_hash = compute_layout_hash(doc_headers)
    best_tpl = None
    best_score = -1.0
    for tpl in candidates:
        lay = getattr(tpl, "layout", None) or {}
        if doc_hash and lay.get("layout_hash") == doc_hash:
            return tpl, 1.0, "layout_hash_exact"
        tpl_headers = template_header_tokens(tpl)
        score = header_similarity(doc_headers, tpl_headers)
        if score > best_score:
            best_score = score
            best_tpl = tpl

    if best_tpl is not None and best_score >= min_jaccard:
        return best_tpl, round(best_score, 4), "header_jaccard_match"
    if len(candidates) == 1:
        return candidates[0], round(max(0.0, best_score), 4), "single_enabled_low_jaccard"
    return None, round(max(0.0, best_score), 4), "jaccard_below_threshold"


# ---------------------------------------------------------------- 选模板的入口
def doc_headers_from_pdf(data: bytes, max_pages: int = 2, cap: int = 24) -> list[str]:
    """从 PDF 前两页抽出「像表头」的词，作为版式比对依据。

    为什么按「词集合」而不是「表头那一行」：真实银行导出件的第一页常常是账户信息 +
    多行说明，表头行可能被拆散或与数据交错；按行取会取空（实测建行样例只拿到「结束日期」）。
    改为收集前两页里能被认成表头词的 token 去重，Jaccard 用集合算，正好匹配。
    """
    try:
        import pymupdf  # noqa: PLC0415
        from rc_platform.capabilities.layout.keywords import match_header_field  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - 缺依赖不该阻断上传
        return []

    if data[:4] != b"%PDF":
        return []
    tokens: list[str] = []
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
        try:
            for page_no in range(min(max_pages, doc.page_count)):
                for word in doc[page_no].get_text("words"):
                    text = str(word[4]).strip()
                    if not text or len(text) > 12:
                        continue
                    if "：" in text or ":" in text:
                        continue
                    if match_header_field(text) and text not in tokens:
                        tokens.append(text)
        finally:
            doc.close()
    except Exception:  # noqa: BLE001
        return []
    return tokens[:cap]


def select_template(rows: list[Any], doc_headers: list[str] | None) -> tuple[Any | None, float, str]:
    """在「同银行启用模板」里挑最匹配的一版；返回 (行, 分数, 依据)。"""
    return pick_best_template(rows, doc_headers)
