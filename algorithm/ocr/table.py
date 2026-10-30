from __future__ import annotations

from dataclasses import dataclass, field

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "txn_date": ("交易时间", "交易日期", "记账日期", "交易发生日期", "交易发生时间", "交易日", "日期"),
    "summary": ("摘要", "交易摘要", "交易类型", "商品", "用途", "交易说明", "附言", "备注"),
    "counterparty": ("交易对方", "对方户名", "对方名称", "对方账户名", "对手方", "商户名称", "收款方"),
    "direction": ("收/支", "收支", "借贷标志", "借贷方向", "收付标志", "借/贷", "方向"),
    "amount": ("收入/支出金额", "金额(元)", "交易金额", "发生额", "交易额", "金额"),
    "amount_in": ("收入金额", "贷方发生额", "贷方金额"),
    "amount_out": ("支出金额", "借方发生额", "借方金额"),
    "balance": ("账户余额", "交易后余额", "当前余额", "余额"),
}

_MULTI_FIELD = {"amount_in", "amount_out"}


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    confidence: float = 1.0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class Line:
    words: list[Word] = field(default_factory=list)
    top: float = 0.0
    bottom: float = 0.0

    @property
    def center(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass(frozen=True)
class Column:
    field: str
    left: float
    right: float


def group_lines(words: list[Word], y_tol: float = 3.0) -> list[Line]:
    lines: list[Line] = []
    for word in sorted(words, key=lambda w: ((w.top + w.bottom) / 2, w.x0)):
        cy = (word.top + word.bottom) / 2
        if lines and abs(cy - lines[-1].center) <= y_tol:
            lines[-1].words.append(word)
            line = lines[-1]
            line.top = min(line.top, word.top)
            line.bottom = max(line.bottom, word.bottom)
        else:
            lines.append(Line(words=[word], top=word.top, bottom=word.bottom))
    for line in lines:
        line.words.sort(key=lambda w: w.x0)
    return lines


def _norm(text: str) -> str:
    table = str.maketrans({"（": "(", "）": ")", "／": "/", "：": ":", "　": " "})
    return "".join(text.translate(table).split())


def match_field(text: str) -> tuple[str, int] | None:
    """返回 (规范字段, 匹配长度)；精确匹配优先，其次取最长的包含匹配。"""
    value = _norm(text)
    if not value:
        return None
    best: tuple[str, int] | None = None
    for canonical, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            key = _norm(alias)
            if value == key:
                return canonical, len(key)
            if key in value and len(key) >= 2:
                if best is None or len(key) > best[1]:
                    best = (canonical, len(key))
    return best


def merge_tokens(line: Line, gap: float = 2.0) -> list[Word]:
    tokens: list[Word] = []
    for word in line.words:
        if tokens and word.x0 - tokens[-1].x1 <= gap:
            prev = tokens[-1]
            tokens[-1] = Word(
                text=prev.text + word.text,
                x0=prev.x0,
                x1=max(prev.x1, word.x1),
                top=min(prev.top, word.top),
                bottom=max(prev.bottom, word.bottom),
            )
        else:
            tokens.append(word)
    return tokens


def find_header(
    lines: list[Line],
    field_map: dict[str, str | int] | None = None,
    limit: int = 20,
) -> tuple[Line, list[Word], dict[int, str]] | None:
    best: tuple[int, Line, list[Word], dict[int, str]] | None = None
    for line in lines[:limit]:
        tokens = merge_tokens(line)
        mapping: dict[int, str] = {}
        for idx, token in enumerate(tokens):
            hit = match_field(token.text)
            if hit:
                mapping[idx] = hit[0]
        if field_map:
            mapping = apply_template(tokens, mapping, field_map)
        score = len({v for v in mapping.values()})
        if score >= 3 and (best is None or score > best[0]):
            best = (score, line, tokens, mapping)
    if best is None:
        return None
    return best[1], best[2], best[3]


def apply_template(tokens: list[Word], mapping: dict[int, str], field_map: dict[str, str | int]) -> dict[int, str]:
    """模板显式映射优先：同一字段只保留模板指定的那一列，去掉表头自动识别的重名列。"""
    merged = dict(mapping)
    claimed: dict[str, int] = {}
    for canonical, target in field_map.items():
        idx: int | None = None
        if isinstance(target, int):
            if 0 <= target < len(tokens):
                idx = target
        else:
            want = _norm(target)
            for i, token in enumerate(tokens):
                if _norm(token.text) == want:
                    idx = i
                    break
        if idx is None:
            continue
        merged[idx] = canonical
        claimed[canonical] = idx
    for idx, canonical in list(merged.items()):
        if canonical in claimed and claimed[canonical] != idx:
            del merged[idx]
    return merged


def build_columns(tokens: list[Word], mapping: dict[int, str]) -> list[Column]:
    centers = [t.cx for t in tokens]
    bounds = [-1e9]
    for left, right in zip(centers, centers[1:]):
        bounds.append((left + right) / 2)
    bounds.append(1e9)
    columns: list[Column] = []
    for idx, canonical in mapping.items():
        columns.append(Column(field=canonical, left=bounds[idx], right=bounds[idx + 1]))
    return columns


def line_cells(line: Line, columns: list[Column]) -> dict[str, list[Word]]:
    cells: dict[str, list[Word]] = {}
    for word in line.words:
        for col in columns:
            if col.left <= word.cx < col.right:
                cells.setdefault(col.field, []).append(word)
                break
    return cells
