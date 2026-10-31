from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from ..ocr.models import Transaction
from ..ocr.parse import LOW_CONF
from .hits import HitResult
from .scores import ScoreResult, compute_scores
from .metrics import MetricSet, MetricValue, MonthlyFlow
from .models import Evidence, LayerStatus
from .thresholds import (
    DEFAULT_THRESHOLDS,
    Conclusion,
    ThresholdConfig,
    ThresholdResult,
    evaluate_thresholds,
)
from .verdict import Verdict, VerdictResult

Carrier = Literal["electronic", "image", "screenshot"]


class ReportCheck(BaseModel):
    """单个检查点的运行结果；方法说明见 verification_defs。"""

    code: str
    name: str
    status: str
    detail: str = ""


class ReportLayer(BaseModel):
    layer: Literal["file", "content", "ledger", "external"]
    status: LayerStatus
    detail: str
    checks: list[ReportCheck] = Field(default_factory=list)


class ReportEvidence(BaseModel):
    txn_id: int | None = None
    rule_code: str
    page_no: int
    x: float
    y: float


class ReportMaterial(BaseModel):
    """报告依据的材料；来源为后端 task_file，算法不自行推断。"""

    file_id: int
    role: Literal["original", "supplement"]
    pages: int | None = None
    sha256: str | None = None


class Report(BaseModel):
    """contract.md「报告结构」；layers 按契约输出数组，每项为四层之一。"""

    carrier: Carrier
    verdict: Verdict
    verdict_reason: str
    limitations: list[str] = Field(default_factory=list)
    layers: list[ReportLayer] = Field(default_factory=list)
    metrics: list[MetricValue] = Field(default_factory=list)
    metric_set_version: int
    threshold_version: int
    conclusions: list[Conclusion] = Field(default_factory=list)
    scores: ScoreResult | None = None
    trend: list[MonthlyFlow] = Field(default_factory=list)
    evidence: list[ReportEvidence] = Field(default_factory=list)
    materials: list[ReportMaterial] = Field(default_factory=list)
    self_check: list[ReportCheck] = Field(default_factory=list)
    version: int = 1


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _position_ids(
    transactions: list[Transaction] | None,
    txn_ids: list[int | None] | None,
) -> dict[tuple[int, int], int | None]:
    if transactions is None and txn_ids is None:
        return {}
    if transactions is None or txn_ids is None:
        raise ValueError("transactions 与 txn_ids 必须同时提供")
    if len(transactions) != len(txn_ids):
        raise ValueError("txn_ids 长度必须与交易笔数一致")
    return {
        (txn.page_no, txn.row_no): txn_id
        for txn, txn_id in zip(transactions, txn_ids)
    }


def _evidence(
    items: list[Evidence],
    position_ids: dict[tuple[int, int], int | None],
) -> tuple[list[ReportEvidence], int, int]:
    seen: set[tuple] = set()
    result: list[ReportEvidence] = []
    missing = 0
    no_coord = 0
    for item in items:
        key = (item.rule_code, item.page_no, item.row_no)
        if key in seen:
            continue
        seen.add(key)
        if item.x == 0 and item.y == 0:
            no_coord += 1
        txn_id = item.txn_id
        if txn_id is None:
            txn_id = position_ids.get((item.page_no, item.row_no))
        if txn_id is None:
            missing += 1
        result.append(
            ReportEvidence(
                txn_id=txn_id,
                rule_code=item.rule_code,
                page_no=item.page_no,
                x=item.x,
                y=item.y,
            )
        )
    return result, missing, no_coord


def _column_limitations(transactions: list[Transaction]) -> list[str]:
    """整列缺失时给一次明确的「哪类指标不可算」，不逐项重复。"""
    if not transactions:
        return []
    limits: list[str] = []
    if not any((txn.counterparty_name or "").strip() for txn in transactions):
        limits.append(
            "明细无对手方名称（版式缺列或整列为空），E01/E02 不可算，对手方集中度未判定"
        )
    if not any(txn.balance is not None for txn in transactions):
        limits.append("明细无余额（版式缺余额列或整列为空），C03–C06、B07 不可算，余额链核对受限")
    if not any(txn.txn_date for txn in transactions):
        limits.append("明细无交易日期（版式缺日期列或整列为空），A02–A08、D01、D06、D08 不可算")
    if not any(txn.direction in ("in", "out") for txn in transactions):
        limits.append(
            "明细无收付方向（版式缺方向列且金额未印正负号），收入/支出类指标不可算"
        )
    if not any(txn.amount is not None for txn in transactions):
        limits.append("明细无交易金额，金额类指标不可算")
    return limits


def _low_confidence_limitation(transactions: list[Transaction]) -> list[str]:
    """低置信行照常计入，但必须在报告里留痕，不能让人误以为是确定读数。"""
    low = [txn for txn in transactions if txn.confidence < LOW_CONF]
    if not low:
        return []
    pages = sorted({txn.page_no for txn in low})
    shown = "、".join(str(page) for page in pages[:5])
    if len(pages) > 5:
        shown += " 等"
    return [
        f"{len(low)} 笔明细置信度低于 {LOW_CONF:.2f}（第 {shown} 页），"
        "相关行按识别值计入，核对原页后再采信"
    ]


def _uses_uncalibrated_default(conclusion: Conclusion, config: ThresholdConfig) -> bool:
    if conclusion.code == "NET_OUTFLOW":
        return (
            "单月≥" in conclusion.threshold
            and config.net_outflow_month_floor == DEFAULT_THRESHOLDS.net_outflow_month_floor
        )
    if conclusion.code == "FAST_IN_OUT":
        return config.fast_in_out_min_amount == DEFAULT_THRESHOLDS.fast_in_out_min_amount
    if conclusion.code == "NEW_LOAN":
        return config.new_loan_min_income_ratio == DEFAULT_THRESHOLDS.new_loan_min_income_ratio
    if conclusion.code == "CRYPTO_HIT":
        return config.crypto_min_amount == DEFAULT_THRESHOLDS.crypto_min_amount
    return False


def _uncalibrated_limitations(
    threshold_result: ThresholdResult, config: ThresholdConfig
) -> list[str]:
    """未校准默认值一旦触发结论，必须在报告里注明，不能当作已定稿阈值。"""
    codes = [
        conclusion.code
        for conclusion in threshold_result.conclusions
        if _uses_uncalibrated_default(conclusion, config)
    ]
    if not codes:
        return []
    return [
        f"{'、'.join(dict.fromkeys(codes))} 使用了未校准默认值，"
        "仅作线索，待样本校准或业务确认后再定稿"
    ]


def build_report(
    verdict: VerdictResult,
    metrics: MetricSet,
    *,
    carrier: Carrier,
    hits: HitResult | None = None,
    thresholds: ThresholdConfig | None = None,
    monthly_payment: Decimal | None = None,
    transactions: list[Transaction] | None = None,
    txn_ids: list[int | None] | None = None,
    materials: list[ReportMaterial] | None = None,
    self_check: list[ReportCheck] | None = None,
    version: int = 1,
) -> Report:
    """把五态、指标、阈值、趋势、证据与识别自检聚合成一份报告。"""
    if version < 1:
        raise ValueError("报告版本必须从 1 起")

    threshold_result = evaluate_thresholds(
        metrics,
        hits=hits,
        config=thresholds,
        monthly_payment=monthly_payment,
        transactions=transactions,
    )
    active_thresholds = thresholds if thresholds is not None else DEFAULT_THRESHOLDS
    position_ids = _position_ids(transactions, txn_ids)
    evidence, missing, no_coord = _evidence(
        list(verdict.evidence) + list(threshold_result.evidence),
        position_ids,
    )

    report_materials = list(materials or [])

    report_self_check: list[ReportCheck] = list(self_check or [])
    limitations = list(verdict.limitations) + list(threshold_result.notes) + list(metrics.notes)
    limitations.extend(_column_limitations(transactions or []))
    limitations.extend(_low_confidence_limitation(transactions or []))
    limitations.extend(_uncalibrated_limitations(threshold_result, active_thresholds))
    if self_check is None:
        limitations.append("未执行识别自检，报告无法说明解析结果能否回查到原件")
    else:
        for item in self_check:
            if item.status != "pass":
                limitations.append(f"识别自检 {item.code} {item.name}：{item.detail}")
    if not report_materials:
        limitations.append("材料清单未提供，报告无法说明依据了哪几份材料")
    if missing:
        limitations.append("交易号未落库，证据定位到页/行/坐标")
    if no_coord:
        limitations.append(f"{no_coord} 条证据为文件级判断或原行无坐标，无法跳转到页内位置")
    limitations = _dedupe(limitations)

    return Report(
        carrier=carrier,
        verdict=verdict.verdict,
        verdict_reason=verdict.verdict_reason,
        limitations=limitations,
        layers=[
            ReportLayer(
                layer=layer.layer,
                status=layer.status,
                detail=layer.detail,
                checks=[
                    ReportCheck(code=c.code, name=c.name, status=c.status, detail=c.detail or "")
                    for c in layer.checks
                ],
            )
            for layer in verdict.layers
        ],
        metrics=metrics.metrics,
        metric_set_version=metrics.metric_set_version,
        threshold_version=threshold_result.version,
        conclusions=threshold_result.conclusions,
        scores=compute_scores(metrics.metrics, threshold_result.conclusions),
        trend=metrics.trend,
        evidence=evidence,
        materials=report_materials,
        self_check=report_self_check,
        version=version,
    )
