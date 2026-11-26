"""全项目唯一的解析入口。

为什么要有这一层：模板解析（algorithm.ocr.parse）与版式解析（parse.layout_v2）
长期各走各的，Lab 里还单独写了一份「日期覆盖率低于 50% 就换解析器」的兜底。
结果是同一份流水从 Lab、业务后端、CLI 进来会得到不同结果，而且兜底逻辑复制三份。

这里收口成一条路径：

    data（PDF/图片） -> layout_v2 -> 日期覆盖率 < 50% 时用旧解析器兜底
    rows（已解析明细） -> 直接转 Statement

选择结果写进 Statement.meta，复盘时能回答「这次为什么用了兜底」。
金额只走 Decimal，算不出返回 None，不在这一层填 0。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from ...core.context import JobContext
from ...core.contracts import DocumentProfile, SourceDocument, Statement, TxnRow
from ...core.pipeline import Pipeline
from ...core.registry import default_registry

# 日期覆盖率低于这个值，说明 layout_v2 只切出了行、没认出日期列。
# 时间类特征（夜间/月度/休眠/近 N 天）全依赖日期，这种件必须换旧解析器补。
FALLBACK_DATED_RATIO = 0.5
LAYOUT_PARSER = "parse.layout_v2"


class ParseFailed(RuntimeError):
    """统一入口的失败。带上各条路径的降级原因，调用方不必自己猜。"""

    def __init__(self, message: str, *, degradation: list[str] | None = None) -> None:
        super().__init__(message)
        self.degradation = list(degradation or [])


def dated_ratio(statement: Statement) -> float:
    """有日期的行数占比；空结果按 0 计，避免除零。"""
    rows = list(statement.rows or [])
    if not rows:
        return 0.0
    return sum(1 for row in rows if row.txn_date) / len(rows)


def page_coverage(statement: Statement) -> float:
    """有明细的页数占声明页数的比例。

    layout_v2 偶发只吐出第一页（实测招行 2 页件只出第 1 页、17 笔 vs 旧解析 30 笔），
    日期覆盖率仍是 100%，只看日期发现不了整页丢失。页覆盖是第二个兜底信号。
    """
    if statement.page_count <= 1:
        return 1.0
    covered = {row.page_no for row in statement.rows if row.page_no is not None}
    return len(covered) / statement.page_count


def _decimal(value: Any, *, field: str, index: int) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ParseFailed(f"第 {index + 1} 行 {field} 不是合法金额：{value!r}") from exc


def _statement_from_rows(rows: list[dict[str, Any]] | list[TxnRow]) -> Statement:
    out: list[TxnRow] = []
    for index, raw in enumerate(rows):
        if isinstance(raw, TxnRow):
            out.append(raw)
            continue
        if not isinstance(raw, dict):
            raise ParseFailed(f"第 {index + 1} 行不是对象：{type(raw).__name__}")
        out.append(
            TxnRow(
                txn_date=raw.get("txn_date"),
                trade_time=raw.get("trade_time"),
                reference_no=raw.get("reference_no"),
                direction=raw.get("direction"),
                amount=_decimal(raw.get("amount"), field="amount", index=index),
                balance=_decimal(raw.get("balance"), field="balance", index=index),
                summary=raw.get("summary"),
                counterparty_name=raw.get("counterparty_name") or raw.get("counterparty"),
                page_no=int(raw.get("page_no") or 0),
                row_no=int(raw.get("row_no") or index + 1),
                confidence=float(raw.get("confidence") or 1.0),
                extra=raw.get("extra"),
            )
        )
    page_count = max((row.page_no for row in out), default=-1) + 1
    return Statement(rows=out, page_count=max(page_count, 0))


def _document_profile(raw: dict[str, Any] | None, data: bytes | None) -> DocumentProfile:
    raw = dict(raw or {})
    carrier = raw.get("carrier")
    if not carrier:
        carrier = "electronic" if data and data[:4] == b"%PDF" else "image"
    allowed = (
        "carrier", "pages", "has_text_layer", "encrypted", "bank_code",
        "bank_name", "period_start", "period_end", "is_statement", "reasons",
    )
    fields = {key: raw[key] for key in allowed if key in raw}
    fields["carrier"] = carrier
    return DocumentProfile(**fields)


def _run_layout(data: bytes, profile: DocumentProfile) -> Statement:
    registry = default_registry()
    plan = registry.plan("statement", overrides={"statement": LAYOUT_PARSER})
    result = Pipeline(registry, plan, on_error="degrade").run(
        JobContext(job_id="parse_statement"),
        {
            "document": SourceDocument(data=data),
            "profile": profile,
        },
    )
    statement = result.get("statement")
    if statement is None:
        detail = "；".join(result.degradation) or "layout_v2 未产出 Statement"
        raise ParseFailed(detail, degradation=list(result.degradation))
    return statement


def _run_legacy(data: bytes) -> Statement | None:
    """旧解析器兜底。失败返回 None，由调用方决定是否算整单失败。"""
    try:
        from ...compat.native import statement_from_parsed

        from algorithm.ocr.parse import parse as parse_legacy
    except Exception:  # noqa: BLE001 - 旧解析器不可用不是入口层能修的事
        return None
    try:
        parsed = parse_legacy(data, None)
    except Exception:  # noqa: BLE001 - 兜底失败不覆盖主路径的错误
        return None
    if not parsed.transactions:
        return None
    statement = statement_from_parsed(parsed)
    statement.warnings = list(statement.warnings)
    statement.warnings.append("layout_v2 不可用，改由旧解析器兜底")
    return statement


def _observe(
    statement: Statement,
    parser_used: str,
    *,
    layout_ratio: float | None = None,
    legacy_ratio: float | None = None,
    layout_pages: float | None = None,
    legacy_pages: float | None = None,
    fallback_reason: str | None = None,
) -> Statement:
    """把「用了哪条路、日期/页覆盖多少、多少行」写进 meta。"""
    ratio = round(dated_ratio(statement), 4)
    statement.meta.update(
        {
            "parser_used": parser_used,
            "dated_ratio": ratio,
            "page_coverage": round(page_coverage(statement), 4),
            "row_count": len(statement.rows),
        }
    )
    if layout_ratio is not None:
        statement.meta["layout_dated_ratio"] = round(layout_ratio, 4)
    if legacy_ratio is not None:
        statement.meta["legacy_dated_ratio"] = round(legacy_ratio, 4)
    if layout_pages is not None:
        statement.meta["layout_page_coverage"] = round(layout_pages, 4)
    if legacy_pages is not None:
        statement.meta["legacy_page_coverage"] = round(legacy_pages, 4)
    if fallback_reason:
        statement.meta["fallback_reason"] = fallback_reason
    return statement


def parse_statement(
    *,
    data: bytes | None = None,
    rows: list[dict[str, Any]] | list[TxnRow] | None = None,
    profile: dict[str, Any] | None = None,
) -> Statement:
    """全项目唯一的解析入口：PDF 字节或已解析 rows，都从这里出 Statement。

    - 有 rows 直接转（调用方已经解析过，不再重复读文件）
    - 有 data 先 layout_v2；日期覆盖率 < 50% 或整页没有明细时，用旧解析器兜底
    - 两条都失败时抛 ParseFailed，不返回半份结果
    """
    if data is None and rows is None:
        raise ParseFailed("data 与 rows 至少给一个")
    if rows is not None:
        return _observe(_statement_from_rows(rows), "rows")
    assert data is not None  # 上面的分支已经排除 data is None

    profile_obj = _document_profile(profile, data)
    layout_error: str | None = None
    layout_stmt: Statement | None = None
    try:
        layout_stmt = _run_layout(data, profile_obj)
    except Exception as exc:  # noqa: BLE001 - 入口层统一解释失败
        layout_error = str(exc)

    layout_ratio = dated_ratio(layout_stmt) if layout_stmt is not None else 0.0
    layout_pages = page_coverage(layout_stmt) if layout_stmt is not None else 0.0
    page_gap = layout_stmt is not None and layout_pages < 1.0
    if layout_stmt is not None and layout_ratio >= FALLBACK_DATED_RATIO and not page_gap:
        return _observe(layout_stmt, "layout_v2", layout_ratio=layout_ratio,
                        layout_pages=layout_pages)

    legacy_stmt = _run_legacy(data)
    legacy_ratio = dated_ratio(legacy_stmt) if legacy_stmt is not None else 0.0
    legacy_pages = page_coverage(legacy_stmt) if legacy_stmt is not None else 0.0
    # 页有缺口时，「笔数更多」是比日期覆盖率更强的信号：整页丢了，日期比例仍可能 100%。
    better = legacy_ratio > layout_ratio or (
        page_gap and legacy_stmt is not None and len(legacy_stmt.rows) > len(layout_stmt.rows)
    )
    if legacy_stmt is not None and (layout_stmt is None or better):
        reason = layout_error or (
            f"layout_v2 只覆盖 {layout_pages:.0%} 的页" if page_gap
            else f"layout_v2 日期覆盖率 {layout_ratio:.0%} < {FALLBACK_DATED_RATIO:.0%}"
        )
        return _observe(
            legacy_stmt,
            "legacy_fallback",
            layout_ratio=layout_ratio,
            legacy_ratio=legacy_ratio,
            layout_pages=layout_pages,
            legacy_pages=legacy_pages,
            fallback_reason=reason,
        )

    if layout_stmt is not None:
        # 兜底没有改善，保留主路径结果，但把「日期/页覆盖不足」写进告警，别让它悄悄过去。
        problems = []
        if layout_ratio < FALLBACK_DATED_RATIO:
            problems.append(f"日期覆盖率仅 {layout_ratio:.0%}")
        if page_gap:
            problems.append(f"只覆盖 {layout_pages:.0%} 的页")
        detail = "、".join(problems) or "日期/页覆盖不足"
        layout_stmt.warnings = list(layout_stmt.warnings)
        layout_stmt.warnings.append(f"{detail}，旧解析器兜底未改善")
        return _observe(
            layout_stmt,
            "layout_v2",
            layout_ratio=layout_ratio,
            legacy_ratio=legacy_ratio,
            layout_pages=layout_pages,
            legacy_pages=legacy_pages,
            fallback_reason=f"layout_v2 {detail}，兜底未改善",
        )

    reasons = [item for item in (layout_error,) if item]
    raise ParseFailed(
        "解析失败：layout_v2 与旧解析器都未产出明细"
        + (f"（{ '；'.join(reasons) }）" if reasons else ""),
        degradation=reasons,
    )