"""与封存版本对象之间的适配。

为什么单独一个包：两个能力都用同一段映射（旧 ParseResult -> 新 Statement），
但能力之间不许互相 import。适配层不是能力，放在顶层 compat/ 下，谁都可以用。
M4 之后新解析器自己产出 Statement，这里只留「对照旧版」一个用途。
"""
from __future__ import annotations

from ..core.contracts import LayerOutcome, LayerResult, Statement, TxnRow, Verification


def txn_row(txn) -> TxnRow:
    return TxnRow(
        txn_date=txn.txn_date,
        trade_time=getattr(txn, "trade_time", None),
        reference_no=getattr(txn, "reference_no", None),
        direction=txn.direction,
        amount=txn.amount,
        balance=txn.balance,
        summary=txn.summary,
        counterparty_name=txn.counterparty_name,
        page_no=txn.page_no,
        row_no=txn.row_no,
        confidence=float(txn.confidence or 1.0),
        extra=getattr(txn, "extra", None),
    )


def parsed_from_statement(statement: "Statement"):
    """把新契约还原成旧算法对象。

    为什么需要它：核验/指标/报告这些兼容能力还绑在旧对象上（M4 才换成自己的实现）。
    新解析器产出的是契约，没有 native；这里把 rows 还原成旧 ParseResult，
    于是「新解析 + 旧核验」能组合起来跑，也就能逐项对照。
    """
    if statement.native is not None:
        return statement.native
    from algorithm.ocr.models import ParseResult, Transaction

    transactions = [
        Transaction(
            page_no=row.page_no,
            row_no=row.row_no,
            txn_date=row.txn_date,
            trade_time=row.trade_time,
            reference_no=row.reference_no,
            summary=row.summary,
            counterparty_name=row.counterparty_name,
            direction=row.direction,
            amount=row.amount,
            balance=row.balance,
            confidence=row.confidence,
            extra=row.extra,
        )
        for row in statement.rows
    ]
    return ParseResult(
        transactions=transactions,
        page_count=statement.page_count,
        footer_count=statement.footer_count,
        warnings=list(statement.warnings),
    )


def layer_result(native, layer: str) -> LayerResult:
    """旧层对象 -> 契约层结果。native 一起带过去，compose 还要用它保住成因区分。"""
    from algorithm.algo.models import ContentLayerResult

    if isinstance(native, ContentLayerResult):
        return LayerResult(
            layer=layer,
            status=native.status,
            detail="；".join(f"{c.code} {c.name}{c.status}" for c in native.checks),
            checks=[c.model_dump() for c in native.checks],
            limitations=list(native.limitations),
            evidence=[e.model_dump() for c in native.checks for e in c.evidence],
            native=native,
        )
    return LayerResult(
        layer=layer,
        status=native.status,
        detail=native.detail,
        outcome=native.outcome,
        checks=[c.model_dump() for c in native.checks],
        limitations=list(native.limitations),
        evidence=[e.model_dump() for e in native.evidence],
        native=native,
    )


def verification_from_verdict(verdict) -> Verification:
    return Verification(
        verdict=verdict.verdict,
        verdict_reason=verdict.verdict_reason,
        layers=[
            LayerOutcome(layer=item.layer, status=item.status, detail=item.detail,
                         checks=[c.model_dump() for c in item.checks])
            for item in verdict.layers
        ],
        trust=verdict.trust.model_dump() if verdict.trust else {},
        evidence=[e.model_dump() for e in verdict.evidence],
        limitations=list(verdict.limitations),
        native=verdict,
    )


def statement_from_parsed(parsed) -> Statement:
    return Statement(
        rows=[txn_row(t) for t in parsed.transactions],
        footer_count=parsed.footer_count,
        page_count=parsed.page_count,
        warnings=list(parsed.warnings),
        native=parsed,
    )
