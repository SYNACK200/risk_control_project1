"""标注页坐标框（template-spec v1）→ 解析模板。

标注导出给的是相对页面比例的框与表头基线，parse() 只认 field_map。
本模块把 tables[].columns 的 x/w 按页面实际宽度换算成点，在 header_y 附近找表头行，
按列框与表头词的横向位置落成字段别名；meta_boxes 转成 Template.meta_boxes 供页眉抽取。
T001–T009 为阻断错误（有错不出模板），W001–W005 为提示。
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import fitz

from .models import MetaBox, Template
from .table import Word, group_lines, merge_tokens

CORE_FIELDS: dict[str, str] = {
    "account_no": "账号",
    "account_name": "户名",
    "bank_name": "开户行",
    "period": "交易期间",
    "opening_balance": "期初余额",
    "closing_balance": "期末余额",
    "total_in": "收入合计",
    "total_out": "支出合计",
    "txn_date": "交易日期",
    "summary": "摘要",
    "counterparty": "对方户名",
    "direction": "借贷方向",
    "amount": "发生额",
    "balance": "余额",
    "currency": "币种",
    "remark": "备注",
    "branch": "开户网点",
}

REQUIRED_FIELDS = ("account_no", "period", "txn_date", "summary", "amount", "balance")
TABLE_REQUIRED = ("txn_date", "summary", "amount", "balance")
TABLE_FIELDS = {
    "txn_date",
    "reference_no",
    "summary",
    "counterparty",
    "direction",
    "amount",
    "amount_in",
    "amount_out",
    "balance",
    "currency",
}
META_FIELDS = {"account_no", "account_name", "period"}

CUSTOM_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
EPS = 1e-6
MIN_BOX = 0.002
HEADER_GAP = 18.0
LINE_Y_TOLERANCE = 4.0


@dataclass(frozen=True)
class _Column:
    field: str
    x: float
    w: float
    index: int


@dataclass
class _Table:
    page: int
    header_y: float | None
    area: dict[str, Any] | None
    columns: list[_Column]


@dataclass
class ConversionResult:
    """转换结果；template 为 None 时只看 errors，不产出半成品模板。"""

    template: Template | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.template is not None


def convert_annotation(export: dict[str, Any], file_bytes: bytes | None = None) -> ConversionResult:
    """把标注导出转成 parse() 可用的模板；file_bytes 用于按页定位表头。"""
    if not isinstance(export, dict):
        raise TypeError("标注导出应为 JSON 对象")
    if export.get("field_map"):
        # 旧版解析模板（工行等），没有坐标框可转换，直接采用
        return ConversionResult(
            Template(
                bank_code=str(export.get("bank_code") or "UNKNOWN"),
                version=_version(export),
                field_map=dict(export["field_map"]),
            )
        )

    contexts, page_count = _page_contexts(file_bytes)
    errors, warnings = _validate(export, page_count)
    if errors:
        return ConversionResult(None, errors, warnings)

    notes: list[str] = []
    tables = _tables(export)
    field_map = _field_map(tables, export, contexts, notes)
    missing = [name for name in TABLE_REQUIRED if name not in field_map]
    if missing:
        errors.append(
            "T003 缺少必填字段：" + "、".join(f"{CORE_FIELDS[name]}（列未能定位表头）" for name in missing)
        )
        return ConversionResult(None, errors, warnings, notes)

    return ConversionResult(
        Template(
            bank_code=str(export.get("bank_code")).strip(),
            version=_version(export),
            field_map=field_map,
            meta_boxes=_meta_boxes(export, notes),
            page_size=_page_size(export, contexts, notes),
        ),
        errors,
        warnings,
        notes,
    )


def _version(export: dict[str, Any]) -> int:
    try:
        return int(export.get("version", 1))
    except (TypeError, ValueError):
        return 1


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _page_no(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1


def _column_ok(column: dict[str, Any]) -> bool:
    x, w = _num(column.get("x")), _num(column.get("w"))
    if x is None or w is None:
        return False
    return w > MIN_BOX and -EPS <= x <= 1 + EPS and x + w <= 1 + EPS


def _rect_ok(rect: dict[str, Any]) -> bool:
    x, y = _num(rect.get("x")), _num(rect.get("y"))
    w, h = _num(rect.get("w")), _num(rect.get("h"))
    if None in (x, y, w, h):
        return False
    return (
        w > MIN_BOX
        and h > MIN_BOX
        and -EPS <= x <= 1 + EPS
        and -EPS <= y <= 1 + EPS
        and x + w <= 1 + EPS
        and y + h <= 1 + EPS
    )


def _intersect(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ax, ay, aw, ah = (_num(a.get(k)) for k in ("x", "y", "w", "h"))
    bx, by, bw, bh = (_num(b.get(k)) for k in ("x", "y", "w", "h"))
    if None in (ax, ay, aw, ah, bx, by, bw, bh):
        return False
    return min(ax + aw, bx + bw) > max(ax, bx) and min(ay + ah, by + bh) > max(ay, by)


def _validate(export: dict[str, Any], page_count: int) -> tuple[list[str], list[str]]:
    """按 template-spec 第七节校验；同一表格内的重复列记 T005，跨页同字段按第九节允许。"""
    errors: list[str] = []
    warnings: list[str] = []
    if not str(export.get("bank_code") or "").strip():
        errors.append("T001 请先选择版式所属银行")

    meta = [box for box in export.get("meta_boxes") or [] if isinstance(box, dict)]
    tables = [table for table in export.get("tables") or [] if isinstance(table, dict)]
    if not meta and not tables:
        return ["T002 至少标注一个字段框或一个表格区"], warnings

    annotated = [str(box.get("field") or "") for box in meta]
    annotated += [
        str(column.get("field") or "")
        for table in tables
        for column in table.get("columns") or []
        if isinstance(column, dict)
    ]
    annotated = [name for name in annotated if name]
    missing = [name for name in REQUIRED_FIELDS if name not in annotated]
    if missing:
        errors.append("T003 缺少必填字段：" + "、".join(CORE_FIELDS[name] for name in missing))

    for table in tables:
        columns = [c for c in table.get("columns") or [] if isinstance(c, dict)]
        if not columns:
            errors.append("T004 表格区需要至少一列，否则无法切分明细")
            break
        seen: set[str] = set()
        for column in columns:
            name = str(column.get("field") or "")
            if name and name in seen:
                errors.append(f"T005 字段「{CORE_FIELDS.get(name, name)}」被标注了 2 次，请保留一处")
                break
            seen.add(name)

    seen_meta: set[tuple[str, Any]] = set()
    for box in meta:
        key = (str(box.get("field") or ""), box.get("page"))
        if key[0] and key in seen_meta:
            errors.append(f"T005 字段「{CORE_FIELDS.get(key[0], key[0])}」在同页被标注了 2 次，请保留一处")
            break
        seen_meta.add(key)

    for box in meta:
        if not _rect_ok(box.get("rect") or {}):
            errors.append("T006 有框超出页面范围或尺寸过小")
            break
    if not any(message.startswith("T006") for message in errors):
        for table in tables:
            area = table.get("area")
            if area is not None and not _rect_ok(area):
                errors.append("T006 表格区超出页面范围或尺寸过小")
                break
            header_y = table.get("header_y")
            if header_y is not None:
                value = _num(header_y)
                if value is None or not -EPS <= value <= 1 + EPS:
                    errors.append("T006 表头基线超出页面范围")
                    break
            if any(not _column_ok(column) for column in table.get("columns") or [] if isinstance(column, dict)):
                errors.append("T006 列框超出页面范围或尺寸过小")
                break

    for custom in export.get("custom_fields") or []:
        code = str((custom or {}).get("code") or "") if isinstance(custom, dict) else ""
        if not CUSTOM_CODE_RE.fullmatch(code) or code in CORE_FIELDS:
            errors.append("T007 字段编码只能用小写字母、数字、下划线，且不能与内置字段重名")
            break

    for table in tables:
        area = table.get("area")
        if not isinstance(area, dict):
            continue
        ax, aw = _num(area.get("x")), _num(area.get("w"))
        columns = [c for c in table.get("columns") or [] if isinstance(c, dict)]
        if ax is None or aw is None:
            continue
        if any(
            (cx := _num(column.get("x"))) is not None
            and (cw := _num(column.get("w"))) is not None
            and (cx < ax - EPS or cx + cw > ax + aw + EPS)
            for column in columns
        ):
            errors.append("T008 列区间超出表格区")
            break

    fingerprint = (export.get("match_rule") or {}).get("header_fingerprint") or []
    if not fingerprint:
        errors.append("T009 请至少填写一个表头关键词，否则无法自动命中")

    for box in meta:
        rect = box.get("rect") or {}
        if any(
            table.get("page") == box.get("page")
            and isinstance(table.get("area"), dict)
            and _intersect(rect, table["area"])
            for table in tables
        ):
            warnings.append("W001 该框在明细区域内，可能是重复标注")
            break

    for table in tables:
        columns = sorted(
            (c for c in table.get("columns") or [] if isinstance(c, dict) and _num(c.get("x")) is not None),
            key=lambda c: _num(c.get("x")),
        )
        overlap = next(
            (
                (left, right)
                for left, right in zip(columns, columns[1:])
                if (_num(left.get("x")) or 0) + (_num(left.get("w")) or 0) > (_num(right.get("x")) or 0) + EPS
            ),
            None,
        )
        if overlap:
            left = CORE_FIELDS.get(str(overlap[0].get("field")), str(overlap[0].get("field")))
            right = CORE_FIELDS.get(str(overlap[1].get("field")), str(overlap[1].get("field")))
            warnings.append(f"W002 列「{left}」与「{right}」有重叠，抽取可能串列")
            break

    if not tables:
        warnings.append("W003 没有表格区，只能取到账户信息，无法解析明细")

    size = export.get("page_size") or {}
    if not (_num(size.get("w")) and _num(size.get("h"))):
        warnings.append("W004 未记录基准页面尺寸，排查问题时不便")

    pages = {table.get("page") for table in tables if table.get("page") is not None}
    if len(pages) == 1 and page_count > 1:
        warnings.append(
            f"W005 仅第 {next(iter(pages))} 页标注了表格，样本共 {page_count} 页；续页版式不同时建议补标"
        )

    return errors, warnings


def _tables(export: dict[str, Any]) -> list[_Table]:
    tables: list[_Table] = []
    for table in export.get("tables") or []:
        if not isinstance(table, dict):
            continue
        columns: list[_Column] = []
        for index, column in enumerate(table.get("columns") or []):
            if not isinstance(column, dict):
                continue
            x, w = _num(column.get("x")), _num(column.get("w"))
            name = str(column.get("field") or "")
            if x is None or w is None or not name:
                continue
            columns.append(_Column(field=name, x=x, w=w, index=index))
        tables.append(
            _Table(
                page=_page_no(table.get("page")),
                header_y=_num(table.get("header_y")),
                area=table.get("area") if isinstance(table.get("area"), dict) else None,
                columns=columns,
            )
        )
    return tables


def _page_contexts(file_bytes: bytes | None) -> tuple[dict[int, tuple[list[Word], float, float]], int]:
    """逐页取与 parse() 同一套几何过滤后的词与页面尺寸；取不到就退回表头指纹顺序。"""
    if not file_bytes:
        return {}, 0
    try:
        from .parse import _fitz_page_words

        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception:
        return {}, 0
    try:
        if doc.needs_pass:
            return {}, 0
        contexts: dict[int, tuple[list[Word], float, float]] = {}
        for page_no, page in enumerate(doc, start=1):
            words, _, _ = _fitz_page_words(page)
            contexts[page_no] = (words, page.rect.width, page.rect.height)
        return contexts, doc.page_count
    finally:
        doc.close()


def _plain(text: str) -> str:
    table = str.maketrans({"（": "(", "）": ")", "／": "/", "：": ":", "　": " "})
    return "".join(text.translate(table).split())


def _fingerprint_hits(tokens: list[Word], fingerprint: list[str]) -> int:
    texts = [_plain(token.text) for token in tokens]
    return sum(
        1
        for item in fingerprint
        if _plain(item) and any(_plain(item) in text for text in texts)
    )


def _header_tokens(
    words: list[Word],
    header_pt: float,
    page_h: float,
    fingerprint: list[str],
) -> tuple[list[Word], float] | None:
    """在 header_y 附近找表头行；表头指纹能命中时以指纹为准（标注页与实际版面纵向有漂移）。"""
    lines = group_lines(words, y_tol=LINE_Y_TOLERANCE)
    candidates: list[tuple[float, list[Word]]] = []
    for line in lines:
        gap = (
            0.0
            if line.top <= header_pt <= line.bottom
            else min(abs(line.top - header_pt), abs(line.bottom - header_pt))
        )
        candidates.append((gap, merge_tokens(line)))
    if not candidates:
        return None

    if fingerprint:
        threshold = max(2, (len(fingerprint) + 1) // 2)
        scored = [
            (hits, gap, tokens)
            for gap, tokens in candidates
            if (hits := _fingerprint_hits(tokens, fingerprint)) >= threshold
        ]
        if scored:
            scored.sort(key=lambda item: (-item[0], item[1]))
            return scored[0][2], scored[0][1]

    gap, tokens = min(candidates, key=lambda item: item[0])
    if gap > max(HEADER_GAP, page_h * 0.02):
        return None
    return tokens, gap


def _token_for(tokens: list[Word], x0: float, x1: float) -> Word | None:
    best: tuple[float, Word] | None = None
    for token in tokens:
        overlap = min(x1, token.x1) - max(x0, token.x0)
        if overlap > 0 and (best is None or overlap > best[0]):
            best = (overlap, token)
    if best is not None:
        return best[1]
    center = (x0 + x1) / 2
    if not tokens:
        return None
    near = min(tokens, key=lambda token: abs(token.cx - center))
    tolerance = min(36.0, max(12.0, (x1 - x0) / 4))
    return near if abs(near.cx - center) <= tolerance else None


def _field_map(
    tables: list[_Table],
    export: dict[str, Any],
    contexts: dict[int, tuple[list[Word], float, float]],
    notes: list[str],
) -> dict[str, str | int]:
    fingerprint = [str(item) for item in (export.get("match_rule") or {}).get("header_fingerprint") or []]
    if not contexts:
        notes.append("未提供可读样本 PDF，列按表头指纹顺序映射")

    resolved: dict[str, tuple[Word, int]] = {}
    placed: dict[tuple[int, int, int], str] = {}
    for table_index, table in enumerate(tables):
        tokens = None
        if table.page in contexts:
            words, width, height = contexts[table.page]
            header_y = table.header_y
            if header_y is None and table.area and _num(table.area.get("y")) is not None:
                header_y = (_num(table.area.get("y")) or 0) + 0.01
                notes.append(f"第 {table.page} 页未标表头基线，按明细区顶部下移 1% 找表头")
            if header_y is not None:
                found = _header_tokens(words, header_y * height, height, fingerprint)
                if found is not None:
                    tokens, gap = found
                    if gap > HEADER_GAP:
                        notes.append(
                            f"第 {table.page} 页 header_y 与表头行相差 {gap:.0f}pt，按表头指纹定位"
                        )

        for column in table.columns:
            if column.field not in TABLE_FIELDS:
                notes.append(f"列字段 {column.field} 解析层不消费，已忽略")
                continue
            token = None
            if tokens is not None and table.page in contexts:
                _, width, _ = contexts[table.page]
                token = _token_for(tokens, column.x * width, (column.x + column.w) * width)
            if token is not None and token.text.strip():
                index = tokens.index(token)
                slot = (table_index, table.page, index)
                owner = placed.get(slot)
                if owner is not None:
                    notes.append(f"列「{CORE_FIELDS.get(column.field, column.field)}」与「{CORE_FIELDS.get(owner, owner)}」落到同一表头词，已跳过")
                    continue
                placed[slot] = column.field
                text = token.text.strip()
                previous = resolved.get(column.field)
                if previous is not None and previous[0].text.strip() != text:
                    notes.append(
                        f"字段 {column.field} 在第 {table.page} 页表头为「{text}」，与先前「{previous[0].text.strip()}」不一致，沿用前者"
                    )
                    continue
                resolved.setdefault(column.field, (token, index))

    field_map: dict[str, str | int] = {}
    counts = Counter(token.text.strip() for token, _ in resolved.values())
    for name, (token, index) in resolved.items():
        text = token.text.strip()
        field_map[name] = index if counts[text] > 1 else text

    missing = [
        (table, column)
        for table in tables
        for column in table.columns
        if column.field in TABLE_FIELDS and column.field not in field_map
    ]
    for table, column in missing:
        if len(fingerprint) == len(table.columns) and fingerprint[column.index]:
            field_map[column.field] = fingerprint[column.index]
            notes.append(
                f"字段 {column.field} 未在表头定位，按表头指纹顺序映射为「{fingerprint[column.index]}」"
            )
        else:
            notes.append(f"字段 {column.field} 未在表头定位，已跳过")
    return field_map


def _meta_boxes(export: dict[str, Any], notes: list[str]) -> list[MetaBox]:
    boxes: list[MetaBox] = []
    for box in export.get("meta_boxes") or []:
        if not isinstance(box, dict):
            continue
        name = str(box.get("field") or "")
        rect = box.get("rect") or {}
        if name not in META_FIELDS:
            notes.append(f"页眉字段 {name} 暂不参与解析，保留在标注中")
            continue
        boxes.append(
            MetaBox(
                field=name,
                page=_page_no(box.get("page")),
                x=_num(rect.get("x")) or 0.0,
                y=_num(rect.get("y")) or 0.0,
                w=_num(rect.get("w")) or 0.0,
                h=_num(rect.get("h")) or 0.0,
            )
        )
    return boxes


def _page_size(
    export: dict[str, Any],
    contexts: dict[int, tuple[list[Word], float, float]],
    notes: list[str],
) -> tuple[float, float] | None:
    size = export.get("page_size") or {}
    width, height = _num(size.get("w")), _num(size.get("h"))
    if width and height:
        return (width, height)
    if contexts:
        first = contexts.get(1) or next(iter(contexts.values()))
        notes.append(f"标注未记基准页面尺寸，以样本第 1 页 {first[1]:.1f}×{first[2]:.1f} pt 为准")
        return (first[1], first[2])
    return None
