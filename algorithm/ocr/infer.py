"""由少量标注外推整张表的模板。

标注只需要「几条」：可以是表头上的列名，也可以是某一行里的几个单元格。
外推做三件事：聚类出列 → 推断每列语义 → 生成模板并标注来源（标注/推断/派生）。
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from decimal import Decimal

import pdfplumber
import pymupdf

from .models import Template
from .parse import parse

DATE_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$")
NUM_RE = re.compile(r"^[+-]?\d{1,3}(,\d{3})*(\.\d{1,2})?$|^[+-]?\d+(\.\d{1,2})?$")
DIRECTION_WORDS = {"收", "付", "借", "贷", "进", "出", "in", "out", "收入", "支出"}
CURRENCY_WORDS = {"人民币", "CNY", "RMB", "元", "美元", "USD"}

CANONICAL = ["txn_date", "amount", "balance", "direction", "summary", "counterparty_name", "account_no", "currency", "channel", "trade_time", "page_no"]


@dataclass
class Mark:
    """一条标注：字段名 + 页 + 坐标（PDF 显示坐标，左上原点，与标注页一致）。"""
    field: str
    page: int
    x: float
    y: float


@dataclass
class Provenance:
    field: str
    column: int | None
    source: str  # labeled / inferred / derived
    confidence: float
    why: str


@dataclass
class InferResult:
    template: Template | None
    provenance: list[Provenance]
    columns: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # 反验未通过时模板为 None，但推断出的映射仍保留，供人工确认后存草稿
    draft_map: dict = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        """反验通过才产出模板；False 时只有 warnings。"""
        return self.template is not None


def _words(file_bytes: bytes) -> dict[int, list[dict]]:
    """取页面词坐标，统一归一化到「显示坐标系」。

    页面 rotate 90/180/270 时，原始 PDF 坐标与用户在界面上点选的坐标不一致；
    这里乘 rotation_matrix（与 parse.py 一致），让标注点、模板、解析三方同坐标系。
    """
    pages: dict[int, list[dict]] = {}
    with pymupdf.open(stream=file_bytes, filetype="pdf") as doc:
        for idx, page in enumerate(doc):
            matrix = page.rotation_matrix
            ws: list[dict] = []
            for x0, y0, x1, y1, text, *_rest in page.get_text("words"):
                if not text.strip():
                    continue
                rect = pymupdf.Rect(x0, y0, x1, y1) * matrix
                ws.append({"x0": rect.x0, "x1": rect.x1, "top": rect.y0,
                           "bottom": rect.y1, "text": text})
            pages[idx] = ws
    return pages


_HEADER_META = ("卡号", "户名", "起止日期", "申请单", "打印", "第", "共", "页",
                "借记账户历史明细", "电子版", "明细真伪", "扫码", "识别")

def _is_header_meta(text: str) -> bool:
    """页眉/页脚元数据词（卡号、户名、起止日期、页码…），不能当列锚点。"""
    t = text.strip()
    return any(t.startswith(k) or k in t for k in _HEADER_META)


def _nearest(words: list[dict], x: float, y: float, radius: float | None = None) -> dict | None:
    """把标注点吸附到最近的词，容忍框选偏差。

    三级策略（从严到宽）：
    1. 欧氏距离 ≤ 2.5% 页宽 —— 点在词附近；
    2. 同列范围（|Δx| ≤ 6% 页宽）且纵向偏差 ≤ 15% 页高 —— 点在列的上下空白处；
    3. 仅按横向最近（|Δx| ≤ 12% 页宽）—— 点明显偏出列，但仍能吸附到最近的列。
    """
    if not words:
        return None
    # 所有吸附级别都不允许落到页眉/页脚元数据词上
    words = [w for w in words if not _is_header_meta(w["text"])]
    if not words:
        return None
    page_width = max((w["x1"] for w in words), default=595.0) or 595.0
    page_height = max((w["bottom"] for w in words), default=842.0) or 842.0

    def center(w):
        return (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2

    # 1) 距离内最近
    best, best_d = None, radius if radius is not None else max(24.0, page_width * 0.025)
    for w in words:
        cx, cy = center(w)
        d = ((cx - x) ** 2 + (cy - y) ** 2) ** 0.5
        if d <= best_d:
            best, best_d = w, d
    if best is not None:
        return best

    # 2) 同列（横向接近），纵向放宽
    cand = [w for w in words
            if abs(center(w)[0] - x) <= page_width * 0.06
            and abs(center(w)[1] - y) <= page_height * 0.15]
    if cand:
        return min(cand, key=lambda w: (abs(center(w)[0] - x), abs(center(w)[1] - y)))

    # 3) 只按横向最近；排除页眉/页脚元数据词，避免把「卡号/起止日期」当成列
    cand = [w for w in words
            if abs(center(w)[0] - x) <= page_width * 0.12 and not _is_header_meta(w["text"])]
    if cand:
        return min(cand, key=lambda w: (abs(center(w)[0] - x), abs(center(w)[1] - y)))
    return None


def _cluster_columns(anchors: list[dict], pages: dict[int, list[dict]], tol: float | None = None) -> list[dict]:
    """以锚点为种子横向聚类，得到列区间与全部单元。

    tol 默认按页宽自适应（默认 1.2% 页宽，最小 10pt），让同一列内的小幅偏移仍能聚合。
    """
    if tol is None:
        width = max((w["x1"] for ws in pages.values() for w in ws), default=595.0) or 595.0
        tol = max(10.0, width * 0.012)
    cols: list[dict] = []
    for a in anchors:
        cx = (a["x0"] + a["x1"]) / 2
        target = None
        for c in cols:
            if abs(c["center"] - cx) <= tol:
                target = c
                break
        if target is None:
            target = {"center": cx, "words": [], "fields": []}
            cols.append(target)
        target["fields"].append(a["field"])
        for _, ws in pages.items():
            for w in ws:
                if abs((w["x0"] + w["x1"]) / 2 - cx) <= tol:
                    target["words"].append(w)
    for c in cols:
        c["x0"] = min(w["x0"] for w in c["words"])
        c["x1"] = max(w["x1"] for w in c["words"])
        texts = [w["text"] for w in c["words"]]
        c["samples"] = texts[:200]
    cols.sort(key=lambda c: c["center"])
    return cols


def detect_header_row(pages: dict[int, list[dict]]) -> list[dict]:
    """找表头行：词数最多、且多为短中文的一行。返回该行的词（按 x 升序）。"""
    best_row: list[dict] = []
    for ws in pages.values():
        rows: dict[int, list[dict]] = {}
        for w in ws:
            rows.setdefault(int(round(w["top"] / 3)), []).append(w)
        for row in rows.values():
            if len(row) < 3 or len(row) <= len(best_row):
                continue
            short_cn = sum(1 for w in row
                           if 1 <= len(w["text"]) <= 10 and re.search(r"[\u4e00-\u9fff]", w["text"]))
            if short_cn >= len(row) * 0.6:
                best_row = row
    return sorted(best_row, key=lambda w: (w["x0"] + w["x1"]) / 2)


def _augment_columns(cols: list[dict], pages: dict[int, list[dict]]) -> list[dict]:
    """把锚点没覆盖到的列补进来（按表头分段对齐，避免把同一列切碎）。

    思路：先找「表头行」（词数最多且多为短中文的行），以相邻表头词的中点为分界，
    把整页词按 x 分到各个列区间；凡是没有对应锚点列的区间，补一列。
    """
    if not cols:
        return cols

    best_row = detect_header_row(pages)
    if len(best_row) < 2:
        return cols

    anchor_words = best_row
    edges = [((a["x1"] + b["x0"]) / 2) for a, b in zip(anchor_words, anchor_words[1:])]

    import bisect

    def seg(cx: float) -> int:
        return bisect.bisect_left(edges, cx)

    buckets: dict[int, list[dict]] = {}
    for ws in pages.values():
        for w in ws:
            buckets.setdefault(seg((w["x0"] + w["x1"]) / 2), []).append(w)

    existing = [c["center"] for c in cols]
    for words in buckets.values():
        if not words:
            continue
        cx = sum((w["x0"] + w["x1"]) / 2 for w in words) / len(words)
        if any(abs(cx - c) <= 40 for c in existing):
            continue
        cols.append({
            "center": cx, "words": words, "fields": [],
            "x0": min(w["x0"] for w in words), "x1": max(w["x1"] for w in words),
            "samples": [w["text"] for w in words][:200],
        })
        existing.append(cx)

    cols.sort(key=lambda c: c["center"])
    return cols


# 表头文字 → 模板字段名（银行版式常识，比纯数值特征更可靠）
FIELD_BY_HEADER: dict[str, str] = {
    "交易日期": "txn_date", "日期": "txn_date", "记账日期": "txn_date", "交易时间": "txn_date",
    "摘要": "summary", "交易摘要": "summary", "用途": "summary", "备注": "summary",
    "收入/支出金额": "amount", "金额": "amount", "交易金额": "amount", "发生额": "amount",
    "收入金额": "amount", "支出金额": "amount",
    "余额": "balance", "账户余额": "balance", "可用余额": "balance",
    "账号": "account_no", "卡号": "account_no", "账户": "account_no", "本方账号": "account_no",
    "币种": "currency", "货币": "currency",
    "渠道": "channel", "交易渠道": "channel", "交易方式": "channel",
    "对方户名": "counterparty_name", "对方名称": "counterparty_name",
    "对方账户": "counterparty_name", "对手方": "counterparty_name", "收款人": "counterparty_name",
    "借贷标志": "direction", "收支方向": "direction", "收付标志": "direction",
}


def _map_by_header_name(cols: list[dict], aliases: dict[int, str], out: dict) -> None:
    """按表头文字补全字段映射（只补未占用的字段）。"""
    used = {p.field for p in out.values()}
    for idx, alias in aliases.items():
        field = FIELD_BY_HEADER.get(str(alias).strip())
        if not field or field in used:
            continue
        out[idx] = Provenance(field, idx, "header", 0.85, f"表头「{alias}」直接对应字段")
        used.add(field)


def _column_stats(samples: list[str]) -> dict:
    n = max(1, len(samples))
    nums = [s for s in samples if NUM_RE.match(s.replace(" ", ""))]
    dates = [s for s in samples if DATE_RE.match(s)]
    dirs = [s for s in samples if s in DIRECTION_WORDS]
    cur = [s for s in samples if s in CURRENCY_WORDS]
    return {
        "num_ratio": len(nums) / n,
        "date_ratio": len(dates) / n,
        "dir_ratio": len(dirs) / n,
        "cur_ratio": len(cur) / n,
        "avg_len": sum(len(s) for s in samples) / n,
        "distinct": len(set(samples)),
        "signed": any(s.startswith(("+", "-")) for s in nums),
        "count": len(samples),
    }


def _guess_fields(cols: list[dict], labeled: dict[int, str]) -> dict[int, Provenance]:
    """标注优先；其余列按统计特征推断；方向可由金额符号派生。"""
    out: dict[int, Provenance] = {}
    used: set[str] = set()
    for idx, name in labeled.items():
        out[idx] = Provenance(name, idx, "labeled", 0.99, "人工标注的列")
        used.add(name)

    stats = {i: _column_stats(c["samples"]) for i, c in enumerate(cols)}

    def free(name: str) -> bool:
        return name not in used

    for i, st in stats.items():
        if i in out:
            continue
        if free("txn_date") and st["date_ratio"] > 0.5:
            out[i] = Provenance("txn_date", i, "inferred", 0.9, "该列多为日期格式"); used.add("txn_date"); continue
        if free("direction") and st["dir_ratio"] > 0.5:
            out[i] = Provenance("direction", i, "inferred", 0.85, "该列取值为收/付/借/贷"); used.add("direction"); continue
        if free("currency") and st["cur_ratio"] > 0.5:
            out[i] = Provenance("currency", i, "inferred", 0.85, "该列多为币种"); used.add("currency"); continue

    amount_col = next((i for i, n in labeled.items() if n == "amount"), None)
    balance_col = next((i for i, n in labeled.items() if n == "balance"), None)
    # 金额与余额：数值列里，带符号的当金额，最右数值列当余额
    num_cols = [i for i, st in stats.items() if i not in out and st["num_ratio"] > 0.5]
    if amount_col is None and free("amount"):
        pick = next((i for i in num_cols if i not in out and stats[i]["signed"]), None)
        if pick is None:
            pick = next((i for i in num_cols if i not in out), None)
        if pick is not None:
            out[pick] = Provenance("amount", pick, "inferred", 0.8, "数值列（含正负号优先），判定为交易金额")
            used.add("amount")
    if balance_col is None and free("balance"):
        pick = next((i for i in reversed(num_cols) if i not in out), None)
        if pick is not None:
            out[pick] = Provenance("balance", pick, "inferred", 0.8, "最右侧数值列，判定为余额")
            used.add("balance")

    for i, st in stats.items():
        if i in out:
            continue
        if free("summary") and 1.5 <= st["avg_len"] <= 8 and st["distinct"] > 1 and st["num_ratio"] < 0.3:
            out[i] = Provenance("summary", i, "inferred", 0.7, "短文本、有重复，判定为摘要"); used.add("summary"); continue
    for i, st in stats.items():
        if i in out:
            continue
        if free("counterparty_name") and st["avg_len"] >= 3 and st["distinct"] > st["count"] * 0.5:
            out[i] = Provenance("counterparty_name", i, "inferred", 0.6, "长文本、高基数，判定为对手方"); used.add("counterparty_name"); continue
    for i, st in stats.items():
        if i in out:
            continue
        if free("account_no") and st["num_ratio"] < 0.2 and st["avg_len"] >= 12:
            out[i] = Provenance("account_no", i, "inferred", 0.5, "长数字串，判定为账号"); used.add("account_no"); continue

    return out



def _header_aliases(cols: list[dict], pages: dict[int, list[dict]], limit: int = 25) -> dict[int, str]:
    """在表头行里找每一列对应的文字，作为解析模板的别名（比列序号稳）。

    必须用 detect_header_row 的结果：早期版本按"命中列数最多"自选一行，会选到数据行，
    导致 field_map 里存进单元格内容（如 "12,271.62"），模板看似生成成功实则不可用。
    """
    best_row = detect_header_row(pages)
    if not best_row:
        return {}
    aliases: dict[int, str] = {}
    for idx, c in enumerate(cols):
        near = [w for w in best_row if abs((w["x0"] + w["x1"]) / 2 - c["center"]) <= 18]
        if near:
            aliases[idx] = min(near, key=lambda w: abs((w["x0"] + w["x1"]) / 2 - c["center"]))["text"]
    return aliases


def _check_label_consistency(
    cols: list[dict], aliases: dict[int, str], labeled: dict[int, str]
) -> list[str]:
    """人工标注的列，其表头文字必须与该字段语义一致，否则判定为标错列。

    没有这道检查时：把 amount 标到"账户余额"列，模板会存成 balance→"交易金额"，
    而解析时 find_header 又按表头自动识别纠正回来，反验照样通过 —— 标注等于白标。
    """
    problems: list[str] = []

    # 1) 人工标注的列与其表头语义不符 → 标错列
    for idx, field in labeled.items():
        alias = aliases.get(idx)
        if not alias:
            continue
        expect = FIELD_BY_HEADER.get(str(alias).strip())
        if expect and expect != field:
            problems.append(
                f"字段「{field}」标在第 {idx + 1} 列，但该列表头是「{alias}」（应属于 {expect}），疑似标错列"
            )

    # 2) 多个不同字段标到同一列（常见于坐标没换算好、全部落在左上角）
    for idx, c in enumerate(cols):
        fields = [f for f in c.get("fields", []) if f]
        distinct = sorted(set(fields))
        if len(distinct) >= 2:
            problems.append(
                f"第 {idx + 1} 列同时标了 {len(distinct)} 个字段（{'、'.join(distinct)}），请确认每个字段各画一列"
            )

    # 3) 关键字段必须由人工标注给出，不能全靠推测
    need = ["txn_date", "amount", "balance"]
    lack = [f for f in need if f not in labeled.values()]
    if lack:
        problems.append(
            f"标注不足：{('、'.join(lack))} 没有人工标注，解析规则会退化成猜测；请把这三列各自画一列并指定字段"
        )
    return problems


def _validate(file_bytes: bytes, template: Template) -> list[str]:
    """反验：用模板反跑一遍，行数/金额/余额链对不上就不许作废通过。"""
    """用推断出的模板真解析一遍，按行数/余额链反验列语义；返回硬性问题。"""
    parsed = parse(file_bytes, template)
    txns = parsed.transactions
    if not txns:
        return ["推断模板解析不出交易行，列映射不可用"]
    problems: list[str] = []

    if parsed.footer_count is not None and parsed.footer_count != len(txns):
        problems.append(
            f"推断模板解析 {len(txns)} 笔，与页脚声明 {parsed.footer_count} 笔不符"
        )
    no_amount = sum(1 for txn in txns if txn.amount is None)
    if no_amount * 2 > len(txns):
        problems.append(f"{no_amount}/{len(txns)} 笔取不到金额，金额列映射可疑")
    no_direction = sum(1 for txn in txns if txn.amount is not None and txn.direction not in ("in", "out"))
    if no_direction * 2 > len(txns):
        problems.append(f"{no_direction}/{len(txns)} 笔取不到收/支方向，方向列映射可疑")

    checked = broken = 0
    prev: Decimal | None = None
    for txn in txns:
        if txn.balance is None or txn.amount is None or txn.direction not in ("in", "out"):
            prev = None
            continue
        if prev is not None:
            checked += 1
            sign = Decimal("1") if txn.direction == "in" else Decimal("-1")
            if abs(Decimal(txn.balance) - prev - sign * txn.amount) > Decimal("0.01"):
                broken += 1
        prev = Decimal(txn.balance)
    if checked >= 2 and broken == checked:
        problems.append(f"余额链 {checked} 处可核对、全部不符，金额/余额列映射可能颠倒")
    elif checked >= 5 and broken * 5 > checked:
        problems.append(f"余额链 {checked} 处可核对、{broken} 处不符，金额或余额列映射可疑")
    return problems


def infer_template(file_bytes: bytes, marks: list[Mark], bank_code: str = "UNKNOWN", max_pages: int = 3) -> InferResult:
    """少量标注 → 模板。标注可以是表头词，也可以是样例单元格。"""
    pages = _words(file_bytes)
    use_pages = {k: v for k, v in pages.items() if k < max_pages}
    warnings: list[str] = []

    anchors: list[dict] = []
    for m in marks:
        ws = use_pages.get(m.page) or use_pages.get(0) or []
        w = _nearest(ws, m.x, m.y)
        if w is None:
            warnings.append(f"标注 {m.field} 附近没有文字，已跳过")
            continue
        anchors.append({**w, "field": m.field})
    if not anchors:
        raise ValueError("没有任何有效标注，无法外推")

    cols = _cluster_columns(anchors, use_pages)
    cols = _augment_columns(cols, use_pages)
    labeled: dict[int, str] = {}
    extra_fields: dict[int, list[str]] = {}
    for idx, c in enumerate(cols):
        for f in c["fields"]:
            labeled.setdefault(idx, f)
            extra_fields.setdefault(idx, [])
            if f not in extra_fields[idx]:
                extra_fields[idx].append(f)
    prov = _guess_fields(cols, labeled)

    aliases = _header_aliases(cols, use_pages)
    _map_by_header_name(cols, aliases, prov)
    field_map: dict[str, str | int] = {}
    for pr in prov.values():
        if pr.column is None:
            continue
        alias = aliases.get(pr.column)
        field_map[pr.field] = alias if alias else pr.column
    # 同一列可以承载多个属性（例如金额列同时给 direction 用），全部写进 field_map
    for idx, fields in extra_fields.items():
        alias = aliases.get(idx)
        for f in fields:
            if f not in field_map:
                field_map[f] = alias if alias else idx

    missing = [f for f in ("txn_date", "amount", "balance") if f not in field_map]
    if missing:
        warnings.append(f"未能推断出必需字段：{', '.join(missing)}，需补充标注")
        return InferResult(template=None, provenance=_sorted(prov), columns=_columns(cols), warnings=warnings, draft_map=field_map)

    template = Template(bank_code=bank_code.upper(), version=1, field_map=field_map)
    problems = _check_label_consistency(cols, aliases, labeled)
    problems.extend(_validate(file_bytes, template))
    if problems:
        warnings.extend(problems)
        warnings.append("反验未通过，未生成模板；请修正标注后重试")
        return InferResult(template=None, provenance=_sorted(prov), columns=_columns(cols), warnings=warnings, draft_map=field_map)
    return InferResult(
        template=template,
        provenance=_sorted(prov),
        columns=_columns(cols),
        warnings=warnings,
    )


def _sorted(prov: dict[int, Provenance]) -> list[Provenance]:
    return sorted(prov.values(), key=lambda p: (p.column is None, p.column or 99))


def _columns(cols: list[dict]) -> list[dict]:
    return [
        {"index": i, "x0": round(c["x0"], 1), "x1": round(c["x1"], 1), "samples": c["samples"][:3]}
        for i, c in enumerate(cols)
    ]