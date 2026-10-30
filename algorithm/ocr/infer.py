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

    @property
    def valid(self) -> bool:
        """反验通过才产出模板；False 时只有 warnings。"""
        return self.template is not None


def _words(file_bytes: bytes) -> dict[int, list[dict]]:
    pages: dict[int, list[dict]] = {}
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for idx, page in enumerate(pdf.pages):
            ws = page.extract_words(use_text_flow=False) or []
            pages[idx] = [
                {"x0": w["x0"], "x1": w["x1"], "top": w["top"], "bottom": w["bottom"], "text": w["text"]}
                for w in ws
            ]
    return pages


def _nearest(words: list[dict], x: float, y: float, radius: float = 40.0) -> dict | None:
    best, best_d = None, radius
    for w in words:
        cx, cy = (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2
        d = ((cx - x) ** 2 + (cy - y) ** 2) ** 0.5
        if d <= best_d:
            best, best_d = w, d
    return best


def _cluster_columns(anchors: list[dict], pages: dict[int, list[dict]], tol: float = 14.0) -> list[dict]:
    """以锚点为种子横向聚类，得到列区间与全部单元。"""
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
        if free("summary") and 1.5 <= st["avg_len"] <= 8 and st["distinct"] > 1:
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
    """在表头行里找每一列对应的文字，作为解析模板的别名（比列序号稳）。"""
    best_row: list[dict] = []
    best_score = -1
    for ws in pages.values():
        rows: dict[int, list[dict]] = {}
        for w in ws:
            rows.setdefault(int(round(w["top"] / 3)), []).append(w)
        for key in sorted(rows)[:limit]:
            row = rows[key]
            score = 0
            for c in cols:
                if any(abs((w["x0"] + w["x1"]) / 2 - c["center"]) <= 18 for w in row):
                    score += 1
            if score > best_score:
                best_score, best_row = score, row
    aliases: dict[int, str] = {}
    for idx, c in enumerate(cols):
        near = [w for w in best_row if abs((w["x0"] + w["x1"]) / 2 - c["center"]) <= 18]
        if near:
            aliases[idx] = min(near, key=lambda w: abs((w["x0"] + w["x1"]) / 2 - c["center"]))["text"]
    return aliases


def _validate(file_bytes: bytes, template: Template) -> list[str]:
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
    labeled: dict[int, str] = {}
    for idx, c in enumerate(cols):
        for f in c["fields"]:
            labeled.setdefault(idx, f)
    prov = _guess_fields(cols, labeled)

    aliases = _header_aliases(cols, use_pages)
    field_map: dict[str, str | int] = {}
    for pr in prov.values():
        if pr.column is None:
            continue
        alias = aliases.get(pr.column)
        field_map[pr.field] = alias if alias else pr.column
    missing = [f for f in ("txn_date", "amount", "balance") if f not in field_map]
    if missing:
        warnings.append(f"未能推断出必需字段：{', '.join(missing)}，需补充标注")
        return InferResult(template=None, provenance=_sorted(prov), columns=_columns(cols), warnings=warnings)

    template = Template(bank_code=bank_code.upper(), version=1, field_map=field_map)
    problems = _validate(file_bytes, template)
    if problems:
        warnings.extend(problems)
        warnings.append("反验未通过，未生成模板；请修正标注后重试")
        return InferResult(template=None, provenance=_sorted(prov), columns=_columns(cols), warnings=warnings)
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

