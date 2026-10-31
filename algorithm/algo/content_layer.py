from __future__ import annotations

import re
from decimal import Decimal

from ..ocr.models import HeaderField, PageHeader, PageSummary, ParseResult, Transaction
from ..ocr.parse import LOW_CONF
from .evidence import page_evidence, txn_evidence
from .models import Attribution, CheckResult, ContentLayerResult

MONEY_TOLERANCE = Decimal("0.01")
MAX_EVIDENCE = 20


def _signed_amount(txn: Transaction) -> Decimal | None:
    if txn.amount is None or txn.direction is None:
        return None
    return txn.amount if txn.direction == "in" else -txn.amount


def _attribute(txns: list[Transaction], detail: str) -> Attribution:
    """看失败相关的行：有正常置信度的就判数据断，全低置信才是识别问题。"""
    if txns and all(txn.confidence < LOW_CONF for txn in txns):
        lowest = min(txn.confidence for txn in txns)
        return Attribution(
            cause="recognition",
            action="manual",
            detail=f"{detail}；相关行最低置信度 {lowest:.2f}，先重跑解析，仍低转人工",
        )
    return Attribution(
        cause="data",
        action="stop",
        detail=f"{detail}；相关行置信度正常，判为数据断",
    )


def _check_balance_chain(transactions: list[Transaction]) -> CheckResult:
    code, name = "C1", "余额链"
    failures: list[tuple[Transaction, Decimal]] = []
    low_skips: list[Transaction] = []
    missing = 0
    checked = 0

    for previous, current in zip(transactions, transactions[1:]):
        signed = _signed_amount(current)
        if previous.balance is None or current.balance is None or signed is None:
            if previous.confidence < LOW_CONF or current.confidence < LOW_CONF:
                low_skips.append(current)
            else:
                missing += 1
            continue
        checked += 1
        diff = current.balance - (previous.balance + signed)
        if abs(diff) > MONEY_TOLERANCE:
            failures.append((current, diff))

    if failures:
        first_diff = failures[0][1]
        detail = f"{len(failures)} 处余额不连续（已核对 {checked} 处），首处差额 {first_diff:+.2f} 元"
        return CheckResult(
            code=code,
            name=name,
            status="fail",
            detail=detail,
            evidence=[txn_evidence(txn, code) for txn, _ in failures[:MAX_EVIDENCE]],
            attribution=_attribute([txn for txn, _ in failures], detail),
        )
    if low_skips:
        detail = f"{len(low_skips)} 处因低置信行无法核对"
        return CheckResult(
            code=code,
            name=name,
            status="skipped",
            detail=detail,
            attribution=_attribute(low_skips, detail),
        )
    if checked == 0:
        return CheckResult(code=code, name=name, status="skipped", detail="无可用余额行，未核对")
    if missing:
        return CheckResult(
            code=code,
            name=name,
            status="partial",
            detail=f"已核对 {checked} 处；{missing} 处字段缺失未核对",
        )
    return CheckResult(code=code, name=name, status="pass", detail=f"{checked} 处余额连续")


def _check_page_totals(
    transactions: list[Transaction], summaries: list[PageSummary]
) -> CheckResult:
    code, name = "C2", "每页合计"
    printed = [s for s in summaries if s.printed_in is not None or s.printed_out is not None]
    if not printed:
        return CheckResult(code=code, name=name, status="skipped", detail="未取得每页合计")

    failures: list[tuple[PageSummary, str, list[Transaction]]] = []
    incomplete = 0
    checked = 0
    for summary in printed:
        page_txns = [t for t in transactions if t.page_no == summary.page_no]
        if any(t.amount is None or t.direction is None for t in page_txns):
            incomplete += 1
            continue
        actual_in = sum((t.amount for t in page_txns if t.direction == "in"), Decimal("0"))
        actual_out = sum((t.amount for t in page_txns if t.direction == "out"), Decimal("0"))
        checked += 1
        diffs = []
        if summary.printed_in is not None and abs(actual_in - summary.printed_in) > MONEY_TOLERANCE:
            diffs.append(f"收入 印 {summary.printed_in} 实 {actual_in} 差 {actual_in - summary.printed_in:+.2f}")
        if summary.printed_out is not None and abs(actual_out - summary.printed_out) > MONEY_TOLERANCE:
            diffs.append(f"支出 印 {summary.printed_out} 实 {actual_out} 差 {actual_out - summary.printed_out:+.2f}")
        if diffs:
            failures.append((summary, "；".join(diffs), page_txns))

    if failures:
        summary, first_diffs, _ = failures[0]
        detail = f"第 {summary.page_no} 页合计不符：{first_diffs}"
        involved = [txn for _, _, page_txns in failures for txn in page_txns]
        return CheckResult(
            code=code,
            name=name,
            status="fail",
            detail=detail,
            evidence=[page_evidence(s.page_no, s.footer_bbox, code) for s, _, _ in failures[:MAX_EVIDENCE]],
            attribution=_attribute(involved, detail),
        )
    if checked == 0:
        return CheckResult(code=code, name=name, status="skipped", detail=f"{incomplete} 页字段缺失，未核对")
    if incomplete:
        return CheckResult(
            code=code,
            name=name,
            status="partial",
            detail=f"已核对 {checked} 页；{incomplete} 页字段缺失未核对",
        )
    return CheckResult(code=code, name=name, status="pass", detail=f"{checked} 页合计一致")


def _check_counts(
    transactions: list[Transaction],
    summaries: list[PageSummary],
    footer_count: int | None,
) -> CheckResult:
    code, name = "C3", "笔数"
    printed = [s for s in summaries if s.printed_count is not None]
    if footer_count is None and not printed:
        return CheckResult(code=code, name=name, status="skipped", detail="无页脚笔数")

    for summary in printed:
        page_txns = [t for t in transactions if t.page_no == summary.page_no]
        if len(page_txns) != summary.printed_count:
            detail = f"第 {summary.page_no} 页印 {summary.printed_count} 笔、解析 {len(page_txns)} 笔"
            return CheckResult(
                code=code,
                name=name,
                status="fail",
                detail=detail,
                evidence=[page_evidence(summary.page_no, summary.footer_bbox, code)],
                attribution=_attribute(page_txns, detail),
            )

    if footer_count is not None and footer_count != len(transactions):
        detail = f"页脚共 {footer_count} 笔、解析 {len(transactions)} 笔"
        evidence = [page_evidence(printed[-1].page_no, printed[-1].footer_bbox, code)] if printed else []
        return CheckResult(
            code=code,
            name=name,
            status="fail",
            detail=detail,
            evidence=evidence,
            attribution=_attribute(transactions, detail),
        )

    if not printed:
        return CheckResult(
            code=code,
            name=name,
            status="pass",
            detail=f"解析 {len(transactions)} 笔，与页脚总数 {footer_count} 一致",
        )
    return CheckResult(code=code, name=name, status="pass", detail=f"{len(printed)} 页笔数一致")


def _check_opening_closing(
    transactions: list[Transaction],
    opening_balance: Decimal | None,
    closing_balance: Decimal | None,
) -> CheckResult:
    code, name = "C4", "期初期末"
    if opening_balance is None or closing_balance is None:
        return CheckResult(
            code=code,
            name=name,
            status="skipped",
            detail="文件未标注期初/期末余额，未核对",
        )
    if any(_signed_amount(t) is None for t in transactions):
        return CheckResult(
            code=code,
            name=name,
            status="skipped",
            detail="存在方向/金额缺失，无法复算",
        )

    total_in = sum((t.amount for t in transactions if t.direction == "in"), Decimal("0"))
    total_out = sum((t.amount for t in transactions if t.direction == "out"), Decimal("0"))
    expected = opening_balance + total_in - total_out
    diff = closing_balance - expected
    if abs(diff) > MONEY_TOLERANCE:
        detail = (
            f"期初 {opening_balance} + 收入 {total_in} - 支出 {total_out} = {expected}，"
            f"与期末 {closing_balance} 差 {diff:+.2f}"
        )
        evidence = [txn_evidence(transactions[-1], code)] if transactions else []
        return CheckResult(
            code=code,
            name=name,
            status="fail",
            detail=detail,
            evidence=evidence,
            attribution=_attribute(transactions, detail),
        )
    return CheckResult(code=code, name=name, status="pass", detail="期初、收支与期末闭合")


HEADER_LABELS = {"account_no": "账号", "account_name": "户名"}


def _normalize_header(field: str, value: str) -> str:
    compact = "".join(value.split())
    if field == "account_no":
        compact = re.sub(r"[xX×＊]", "*", compact).replace("-", "")
    else:
        compact = compact.replace("＊", "*")
    return compact


def _masked_equal(left: str, right: str) -> bool | None:
    """掩码位跳过，只比两边都未掩码的位；没有可比位返回 None。"""
    if "*" not in left and "*" not in right:
        return left == right
    if len(left) != len(right):
        return None
    compared = 0
    for a, b in zip(left, right):
        if a == "*" or b == "*":
            continue
        if a != b:
            return False
        compared += 1
    return True if compared else None


def _period_value(header: PageHeader) -> tuple[str, str] | None:
    if header.period_start is None or header.period_end is None:
        return None
    return header.period_start.value, header.period_end.value


def _check_page_headers(headers: list[PageHeader], page_count: int) -> CheckResult:
    code, name = "C5", "表头跨页一致"
    if page_count < 2:
        return CheckResult(code=code, name=name, status="skipped", detail="单页无可比项")

    by_page = {header.page_no: header for header in headers}
    missing = [
        page_no
        for page_no in range(1, page_count + 1)
        if (header := by_page.get(page_no)) is None or header.is_empty
    ]
    if missing:
        shown = "、".join(str(page_no) for page_no in missing[:5])
        shown += " 等页" if len(missing) > 5 else " 页"
        return CheckResult(
            code=code,
            name=name,
            status="skipped",
            detail=f"第 {shown}抬头未识别，未核对",
        )

    checked: list[str] = []
    uncomparable: list[str] = []
    mismatches: list[tuple[str, list[tuple[int, HeaderField]]]] = []

    for field, label in HEADER_LABELS.items():
        present = [
            (header.page_no, value)
            for header in headers
            if (value := getattr(header, field)) is not None
        ]
        if len(present) < 2:
            uncomparable.append(f"{label}仅 {len(present)} 页识别到")
            continue
        low = [str(page_no) for page_no, value in present if value.confidence < LOW_CONF]
        if low:
            uncomparable.append(f"{label}第 {'、'.join(low)} 页低置信")
            continue
        base_page, base = present[0]
        base_value = _normalize_header(field, base.value)
        bad: list[tuple[int, HeaderField]] = []
        incomparable = False
        for page_no, value in present[1:]:
            same = _masked_equal(base_value, _normalize_header(field, value.value))
            if same is None:
                incomparable = True
            elif not same:
                bad.append((page_no, value))
        if bad:
            mismatches.append((label, [(base_page, base), *bad]))
        elif incomparable:
            uncomparable.append(f"{label}掩码不可比")
        else:
            checked.append(label)

    period_pages = [header for header in headers if _period_value(header) is not None]
    if not period_pages:
        uncomparable.append("期间未标注")
    elif len(period_pages) < 2:
        uncomparable.append(f"期间仅 {len(period_pages)} 页识别到")
    elif any(
        header.period_start.confidence < LOW_CONF
        or header.period_end.confidence < LOW_CONF
        for header in period_pages
    ):
        uncomparable.append("期间低置信")
    else:
        base = period_pages[0]
        base_value = _period_value(base)
        bad = [header for header in period_pages[1:] if _period_value(header) != base_value]
        if bad:
            items = [(base.page_no, base.period_start)] + [
                (header.page_no, header.period_start) for header in bad
            ]
            mismatches.append(("期间", items))
        else:
            checked.append("期间")

    if mismatches:
        label, items = mismatches[0]
        first_page, first_value = items[0]
        second_page, second_value = items[1]
        detail = (
            f"页眉{label}跨页不一致：第 {first_page} 页「{first_value.value}」，"
            f"第 {second_page} 页「{second_value.value}」"
        )
        if len(mismatches) > 1:
            detail += f"；另有 {len(mismatches) - 1} 项字段不一致"
        return CheckResult(
            code=code,
            name=name,
            status="fail",
            detail=detail,
            evidence=[
                page_evidence(page_no, value.bbox, code)
                for page_no, value in items[:MAX_EVIDENCE]
            ],
            attribution=Attribution(
                cause="data", action="stop", detail="页眉跨页不一致，判为换页拼装"
            ),
        )
    if not checked:
        return CheckResult(
            code=code,
            name=name,
            status="skipped",
            detail=f"页眉字段均不可比：{'；'.join(uncomparable)}",
        )
    if uncomparable:
        return CheckResult(
            code=code,
            name=name,
            status="partial",
            detail=f"已核对{'、'.join(checked)}一致；{'；'.join(uncomparable)}",
        )
    return CheckResult(
        code=code, name=name, status="pass", detail=f"{'、'.join(checked)}跨页一致"
    )


REFERENCE_MIN_ROWS = 3


def _reference_rows(transactions: list[Transaction]) -> list[tuple[Transaction, str]]:
    """有参考号且不是纯掩码的行；掩码值无法比对，按缺失处理。"""
    rows: list[tuple[Transaction, str]] = []
    for txn in transactions:
        value = _compact_text(txn.reference_no)
        if not value or _is_mask_only(value):
            continue
        rows.append((txn, value))
    return rows


def _reference_usable(rows: list[tuple[Transaction, str]]) -> bool:
    """一笔一号的前提：至少 3 个参考号，且去重后不止一个值。"""
    return len(rows) >= REFERENCE_MIN_ROWS and len({value for _, value in rows}) > 1


def _check_reference_continuity(transactions: list[Transaction]) -> CheckResult:
    """C6：同号出现两笔完整明细是客观事实，判 fail；跳号/格式不一致只提示。"""
    code, name = "C6", "参考号连续性"
    if not transactions:
        return CheckResult(code=code, name=name, status="skipped", detail="无交易明细")

    rows = _reference_rows(transactions)
    if not rows:
        return CheckResult(
            code=code,
            name=name,
            status="skipped",
            detail="未识别到参考号（版式无参考号列或整列为空），未核对",
        )
    if len(rows) < REFERENCE_MIN_ROWS:
        return CheckResult(
            code=code,
            name=name,
            status="skipped",
            detail=f"参考号仅 {len(rows)} 笔，不足 {REFERENCE_MIN_ROWS} 笔，无法确认一笔一号",
        )
    distinct = {value for _, value in rows}
    if len(distinct) <= 1:
        return CheckResult(
            code=code,
            name=name,
            status="skipped",
            detail=f"参考号去重后仅 {len(distinct)} 个值，疑似非一笔一号，未据此判重",
        )

    order = {id(txn): index for index, txn in enumerate(transactions)}
    by_reference: dict[str, list[tuple[int, Transaction]]] = {}
    for txn, value in rows:
        by_reference.setdefault(value, []).append((order[id(txn)], txn))

    duplicate_groups: list[tuple[str, list[Transaction]]] = []
    continuation_groups: list[tuple[str, list[Transaction]]] = []
    ambiguous_groups: list[tuple[str, list[Transaction]]] = []
    for value, items in by_reference.items():
        if len(items) < 2:
            continue
        complete = [
            txn
            for _, txn in items
            if txn.txn_date is not None and txn.amount is not None
        ]
        if len(complete) >= 2:
            duplicate_groups.append((value, complete))
            continue
        indices = [index for index, _ in items]
        adjacent = all(b - a == 1 for a, b in zip(indices, indices[1:]))
        txns = [txn for _, txn in items]
        if adjacent:
            continuation_groups.append((value, txns))
        else:
            ambiguous_groups.append((value, txns))

    if duplicate_groups:
        value, txns = duplicate_groups[0]
        detail = (
            f"参考号「{value}」出现在 {len(txns)} 笔完整明细："
            + "、".join(_row_label(txn) for txn in txns[:5])
        )
        if len(duplicate_groups) > 1:
            detail += f"；另有 {len(duplicate_groups) - 1} 个参考号重复"
        return CheckResult(
            code=code,
            name=name,
            status="fail",
            detail=detail,
            evidence=[txn_evidence(txn, code) for _, group in duplicate_groups for txn in group][
                :MAX_EVIDENCE
            ],
            attribution=_attribute(
                [txn for _, group in duplicate_groups for txn in group],
                "同一参考号出现在两笔不同明细",
            ),
        )

    notes: list[str] = []
    evidence: list = []
    for value, txns in continuation_groups:
        notes.append(
            f"参考号「{value}」相邻同号但字段缺失，疑似续行未合并（"
            + "、".join(_row_label(txn) for txn in txns[:3])
            + "）"
        )
        evidence.extend(txn_evidence(txn, code) for txn in txns)
    if ambiguous_groups:
        value, txns = ambiguous_groups[0]
        notes.append(
            f"参考号「{value}」重复但有行缺日期/金额且不相邻，需人工核对（"
            + "、".join(_row_label(txn) for txn in txns[:3])
            + "）"
        )
        evidence.extend(txn_evidence(txn, code) for txn in txns)

    shapes: dict[str, list[str]] = {}
    for value in distinct:
        shape = f"{len(value)} 位" + ("数字" if value.isdigit() else "含字母/符号")
        shapes.setdefault(shape, []).append(value)
    if len(shapes) > 1:
        example = "；".join(
            f"{shape} {len(values)} 个（如 {values[0]}）"
            for shape, values in list(shapes.items())[:4]
        )
        notes.append(f"参考号格式不一致：{example}")

    if len(shapes) == 1 and all(value.isdigit() for value in distinct):
        numbers = sorted(int(value) for value in distinct)
        gaps = [(a, b) for a, b in zip(numbers, numbers[1:]) if b - a > 1]
        if gaps:
            example = "、".join(f"{a}→{b}" for a, b in gaps[:3])
            notes.append(f"参考号跳号 {len(gaps)} 处（{example}）")

    missing = len(transactions) - len(rows)
    missing_note = f"另有 {missing} 笔缺参考号未参与" if missing else ""
    if notes:
        detail = "；".join(notes)
        if missing_note:
            detail += f"；{missing_note}"
        return CheckResult(
            code=code,
            name=name,
            status="hint",
            detail=detail,
            evidence=evidence[:MAX_EVIDENCE],
        )
    if missing:
        return CheckResult(
            code=code,
            name=name,
            status="partial",
            detail=f"已核对 {len(rows)} 笔参考号；{missing_note}",
        )
    return CheckResult(
        code=code,
        name=name,
        status="pass",
        detail=f"{len(rows)} 笔参考号无重复",
    )


MASK_ONLY_CHARS = set("*＊#＃xX×")


def _compact_text(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "")


def _is_mask_only(value: str) -> bool:
    return bool(value) and all(char in MASK_ONLY_CHARS for char in value)


def _row_label(txn: Transaction) -> str:
    return f"第 {txn.page_no} 页第 {txn.row_no} 行"


def _exclusion_text(reasons: dict[str, int]) -> str:
    return "；".join(f"{reason} {count} 笔" for reason, count in reasons.items())


def _check_duplicates(transactions: list[Transaction]) -> CheckResult:
    """C10：全字段相同的重复只提示；同组参考号也相同且有效才判 fail。"""
    code, name = "C10", "重复记录"
    if not transactions:
        return CheckResult(code=code, name=name, status="skipped", detail="无交易明细")

    groups: dict[tuple, list[Transaction]] = {}
    reasons: dict[str, int] = {}
    for txn in transactions:
        if txn.txn_date is None or txn.amount is None or txn.direction is None:
            reasons["日期/金额/方向缺失"] = reasons.get("日期/金额/方向缺失", 0) + 1
            continue
        summary = _compact_text(txn.summary)
        if not summary:
            reasons["摘要缺失"] = reasons.get("摘要缺失", 0) + 1
            continue
        counterparty = _compact_text(txn.counterparty_name)
        if not counterparty:
            reasons["对手方缺失"] = reasons.get("对手方缺失", 0) + 1
            continue
        if _is_mask_only(counterparty):
            reasons["对手方为纯掩码"] = reasons.get("对手方为纯掩码", 0) + 1
            continue
        key = (txn.txn_date, txn.amount, txn.direction, summary, counterparty)
        groups.setdefault(key, []).append(txn)

    excluded = sum(reasons.values())
    if not groups:
        detail = f"{len(transactions)} 笔均无法参与比对"
        if reasons:
            detail += f"：{_exclusion_text(reasons)}"
        return CheckResult(code=code, name=name, status="skipped", detail=detail)

    compared = sum(len(rows) for rows in groups.values())
    tail = ""
    if excluded:
        tail = f"；另有 {excluded} 笔未参与比对（{_exclusion_text(reasons)}）"
    duplicates = [rows for rows in groups.values() if len(rows) >= 2]
    if duplicates:
        references = _reference_rows(transactions)
        if _reference_usable(references):
            same_reference = [
                rows
                for rows in duplicates
                if len({_compact_text(row.reference_no) for row in rows}) == 1
                and all(
                    _compact_text(row.reference_no)
                    and not _is_mask_only(_compact_text(row.reference_no))
                    for row in rows
                )
            ]
            if same_reference:
                rows = same_reference[0]
                detail = (
                    f"同一参考号「{_compact_text(rows[0].reference_no)}」出现在 "
                    f"{len(rows)} 笔全字段相同的明细："
                    + "、".join(_row_label(row) for row in rows[:5])
                )
                if len(same_reference) > 1:
                    detail += f"；另有 {len(same_reference) - 1} 组同号"
                involved = [row for group in same_reference for row in group]
                return CheckResult(
                    code=code,
                    name=name,
                    status="fail",
                    detail=detail,
                    evidence=[txn_evidence(row, code) for row in involved][:MAX_EVIDENCE],
                    attribution=Attribution(
                        cause="data", action="stop", detail="同一张单子出现两次，判为重复记账"
                    ),
                )
        shown: list[str] = []
        for rows in duplicates[:5]:
            first = rows[0]
            label = (
                f"{first.txn_date} {first.amount} "
                f"{'收入' if first.direction == 'in' else '支出'}"
                f"「{first.summary}」/{first.counterparty_name}："
                + "、".join(_row_label(row) for row in rows)
            )
            shown.append(label)
        if len(duplicates) > 5:
            shown.append(f"等 {len(duplicates)} 组")
        return CheckResult(
            code=code,
            name=name,
            status="hint",
            detail=(
                f"{len(duplicates)} 组重复记录：" + "；".join(shown)
                + "；参考号未抽取或不足以确认，仅提示不判 fail" + tail
            ),
            evidence=[
                txn_evidence(txn, code) for rows in duplicates for txn in rows
            ][:MAX_EVIDENCE],
        )
    if excluded:
        return CheckResult(
            code=code,
            name=name,
            status="partial",
            detail=f"已比对 {compared} 笔，无重复记录{tail}",
        )
    return CheckResult(
        code=code, name=name, status="pass", detail=f"{compared} 笔已比对，无重复记录"
    )


TIME_FORMAT_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d$")
NIGHT_START_HOUR = 22
NIGHT_END_HOUR = 6


def _labels(txns: list[Transaction], limit: int = 5) -> str:
    shown = "、".join(_row_label(txn) for txn in txns[:limit])
    return shown + (f" 等 {len(txns)} 笔" if len(txns) > limit else "")


def _check_time_distribution(transactions: list[Transaction]) -> CheckResult:
    """C7：夜间与同日同秒只提示；时间本身不可用则按识别问题跳过。"""
    code, name = "C7", "时间分布"
    if not transactions:
        return CheckResult(code=code, name=name, status="skipped", detail="无交易明细")

    with_time = [txn for txn in transactions if txn.trade_time]
    if not with_time:
        return CheckResult(
            code=code, name=name, status="skipped", detail="无交易时间，未核对"
        )

    invalid = [
        txn for txn in with_time if not TIME_FORMAT_RE.match(txn.trade_time or "")
    ]
    no_date = [txn for txn in with_time if txn.txn_date is None]
    if invalid or no_date:
        reasons: list[str] = []
        if invalid:
            reasons.append(f"{len(invalid)} 笔时间格式非 HH:MM:SS")
        if no_date:
            reasons.append(f"{len(no_date)} 笔有时间但日期缺失")
        detail = "；".join(reasons) + "，无法归集时段，先重跑解析，仍异常转人工"
        return CheckResult(
            code=code,
            name=name,
            status="skipped",
            detail=detail,
            evidence=[txn_evidence(txn, code) for txn in (invalid + no_date)[:MAX_EVIDENCE]],
            attribution=Attribution(cause="recognition", action="manual", detail=detail),
        )

    night = [
        txn
        for txn in with_time
        if int(txn.trade_time[:2]) >= NIGHT_START_HOUR
        or int(txn.trade_time[:2]) < NIGHT_END_HOUR
    ]
    by_second: dict[tuple[str, str], list[Transaction]] = {}
    for txn in with_time:
        if txn.txn_date is not None:
            by_second.setdefault((txn.txn_date, txn.trade_time or ""), []).append(txn)
    bursts = [rows for rows in by_second.values() if len(rows) >= 2]

    notes: list[str] = []
    evidence: list = []
    if night:
        notes.append(f"夜间（22:00–06:00）{len(night)} 笔：{_labels(night)}")
        evidence.extend(txn_evidence(txn, code) for txn in night)
    if bursts:
        groups = [
            f"{date} {clock} 共 {len(rows)} 笔（{_labels(rows, 3)}）"
            for (date, clock), rows in by_second.items()
            if len(rows) >= 2
        ]
        notes.append(f"同日同秒 {len(bursts)} 组：" + "；".join(groups[:5]))
        evidence.extend(txn_evidence(txn, code) for rows in bursts for txn in rows)

    missing = len(transactions) - len(with_time)
    if notes:
        detail = "；".join(notes)
        if missing:
            detail += f"；另有 {missing} 笔无交易时间未参与"
        return CheckResult(
            code=code,
            name=name,
            status="hint",
            detail=detail,
            evidence=evidence[:MAX_EVIDENCE],
        )
    if missing:
        return CheckResult(
            code=code,
            name=name,
            status="partial",
            detail=f"已核对 {len(with_time)} 笔时间；另有 {missing} 笔无交易时间未参与",
        )
    return CheckResult(
        code=code,
        name=name,
        status="pass",
        detail=f"{len(with_time)} 笔未见夜间或同日同秒集中",
    )


def _check_amount_shape(transactions: list[Transaction]) -> CheckResult:
    """C8：只出统计，不设阈值；样本或字段不足时写明，不判 fail。"""
    code, name = "C8", "金额形态"
    rows = [txn for txn in transactions if txn.amount is not None]
    if not rows:
        return CheckResult(
            code=code,
            name=name,
            status="skipped",
            detail="无交易金额（版式缺金额列或整列为空），未统计",
        )

    values = [abs(txn.amount) for txn in rows]
    integers = sum(1 for value in values if value == value.to_integral_value())
    ratio = integers / len(values)
    by_amount: dict[Decimal, list[Transaction]] = {}
    for txn in rows:
        by_amount.setdefault(abs(txn.amount), []).append(txn)
    repeats = sorted(
        (group for group in by_amount.values() if len(group) >= 2),
        key=lambda group: (-abs(group[0].amount), -len(group)),
    )[:3]
    tails = [0] * 10
    for value in values:
        tails[int(value * 100) % 10] += 1

    parts = [
        f"样本 {len(rows)} 笔" + ("（样本少于 10 笔，仅供参考）" if len(rows) < 10 else ""),
        f"整数金额 {integers} 笔（{ratio:.1%}）",
    ]
    if repeats:
        parts.append(
            "同额重复 "
            + str(len(repeats))
            + " 组（"
            + "、".join(
                f"{group[0].amount} ×{len(group)}" for group in repeats
            )
            + "）"
        )
    else:
        parts.append("无同额重复")
    parts.append("分位尾数 0–9：" + "/".join(str(count) for count in tails))
    missing = len(transactions) - len(rows)
    if missing:
        parts.append(f"另有 {missing} 笔无金额未参与")

    evidence = [txn_evidence(txn, code) for group in repeats for txn in group][:MAX_EVIDENCE]
    return CheckResult(
        code=code,
        name=name,
        status="hint",
        detail="；".join(parts),
        evidence=evidence,
    )


SEMANTIC_RULES = (
    (1, "摘要含「利息/结息」且方向为支出", ("利息", "结息"), "out", ("贷款利息", "罚息", "透支利息")),
    (2, "摘要含「工资/代发/薪资」且方向为支出", ("工资", "代发", "薪资"), "out", ()),
    (3, "摘要含「退款/退货/冲正」且方向为支出", ("退款", "退货", "冲正"), "out", ()),
    (
        4,
        "摘要含「手续费/年费/短信费/账户管理费」且方向为收入",
        ("手续费", "年费", "短信费", "账户管理费"),
        "in",
        (),
    ),
    (5, "摘要含「还款」且方向为收入", ("还款",), "in", ()),
    (6, "摘要含「贷款发放/放款」且方向为支出", ("贷款发放", "放款"), "out", ()),
    (8, "摘要含「消费/购物」且方向为收入", ("消费", "购物"), "in", ()),
)

ORG_WORDS = (
    "公司", "有限", "集团", "银行", "中心", "商行", "超市", "商店", "酒店", "宾馆",
    "医院", "学校", "大学", "政府", "委员会", "事务所", "工厂", "企业", "贸易",
    "科技", "投资", "实业", "控股", "股份", "合伙", "平台", "服务", "管理", "营业部",
    "合作社", "协会", "基金会", "研究院", "车站", "机场", "商场", "市场", "支行",
    "分行", "总行", "店", "厂", "社", "会", "所", "院", "局", "部", "委", "办",
    "行", "处", "科", "室", "站", "场", "园", "馆", "队", "团", "司",
)
PERSON_NAME_RE = re.compile(r"^[\u4e00-\u9fff]{2,4}$")


def _looks_personal(name: str | None) -> bool:
    compact = _compact_text(name)
    if not PERSON_NAME_RE.match(compact):
        return False
    return not any(word in compact for word in ORG_WORDS)


def _check_semantics(transactions: list[Transaction]) -> CheckResult:
    """C9：只做明确矛盾，全部提示；规则跑不了就写明原因，不写通过。"""
    code, name = "C9", "语义匹配"
    if not transactions:
        return CheckResult(code=code, name=name, status="skipped", detail="无交易明细")

    hits: list[tuple[int, str, list[Transaction]]] = []
    executable: list[int] = []
    blocked: list[str] = []

    for rule_no, label, keywords, direction, exclusions in SEMANTIC_RULES:
        rows = [
            txn
            for txn in transactions
            if _compact_text(txn.summary) and txn.direction is not None
        ]
        if not rows:
            blocked.append(f"规则{rule_no}（摘要或方向缺失）")
            continue
        executable.append(rule_no)
        matched = []
        for txn in rows:
            summary = _compact_text(txn.summary)
            if txn.direction != direction:
                continue
            if any(word in summary for word in exclusions):
                continue
            if any(word in summary for word in keywords):
                matched.append(txn)
        if matched:
            hits.append((rule_no, label, matched))

    personal_rows = [
        txn
        for txn in transactions
        if _compact_text(txn.summary) and _compact_text(txn.counterparty_name)
    ]
    if not personal_rows:
        blocked.append("规则7（摘要或对手方缺失）")
    else:
        executable.append(7)
        matched = [
            txn
            for txn in personal_rows
            if any(word in _compact_text(txn.summary) for word in ("工资", "代发"))
            and _looks_personal(txn.counterparty_name)
        ]
        if matched:
            hits.append((7, "摘要含「工资/代发」且对手方像个人", matched))

    if not executable:
        detail = "无规则可执行：" + "；".join(blocked)
        return CheckResult(code=code, name=name, status="skipped", detail=detail)

    if hits:
        detail = "；".join(
            f"规则{rule_no} {label}：{_labels(rows, 3)}" for rule_no, label, rows in hits[:5]
        )
        if len(hits) > 5:
            detail += f"；等 {len(hits)} 条规则"
        return CheckResult(
            code=code,
            name=name,
            status="hint",
            detail=detail,
            evidence=[
                txn_evidence(txn, code) for _, _, rows in hits for txn in rows
            ][:MAX_EVIDENCE],
        )
    if blocked:
        return CheckResult(
            code=code,
            name=name,
            status="partial",
            detail=f"已执行 {len(executable)} 条规则未命中；跳过：{'；'.join(blocked)}",
        )
    return CheckResult(
        code=code,
        name=name,
        status="pass",
        detail=f"{len(executable)} 条规则未命中明确矛盾",
    )


def analyze_content(
    result: ParseResult,
    *,
    opening_balance: Decimal | None = None,
    closing_balance: Decimal | None = None,
) -> ContentLayerResult:
    """C1–C10 内容层；不含账务层与载体层。"""
    checks = [
        _check_balance_chain(result.transactions),
        _check_page_totals(result.transactions, result.page_summaries),
        _check_counts(result.transactions, result.page_summaries, result.footer_count),
        _check_opening_closing(result.transactions, opening_balance, closing_balance),
        _check_page_headers(result.headers, result.page_count),
        _check_reference_continuity(result.transactions),
        _check_time_distribution(result.transactions),
        _check_amount_shape(result.transactions),
        _check_semantics(result.transactions),
        _check_duplicates(result.transactions),
    ]
    limitations: list[str] = []
    for check in checks:
        if check.status in ("skipped", "partial"):
            limitations.append(f"{check.code} {check.name}：{check.detail}")
        elif check.status == "hint":
            limitations.append(
                f"提示（不影响结论）：{check.code} {check.name}：{check.detail}"
            )

    if not result.transactions:
        return ContentLayerResult(
            status="undetermined",
            checks=checks,
            limitations=limitations + ["未解析到交易明细，无法核对"],
        )
    if any(check.status == "fail" and check.attribution and check.attribution.cause == "data" for check in checks):
        status = "inconsistent"
    elif any(check.status == "fail" for check in checks):
        status = "undetermined"
    elif any(check.status in ("skipped", "partial") for check in checks):
        status = "limited"
    else:
        status = "pass"
    return ContentLayerResult(status=status, checks=checks, limitations=limitations)
