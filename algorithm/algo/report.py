from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from ..ocr.models import Transaction
from .hits import HitResult
from .self_check import SelfCheckResult
from .metrics import MetricSet, MetricValue, MonthlyFlow
from .models import Evidence, LayerStatus
from .thresholds import (
    Conclusion,
    ThresholdConfig,
    evaluate_thresholds,
)
from .verdict import Verdict, VerdictResult

Carrier = Literal["electronic", "image", "screenshot"]


class ReportLayer(BaseModel):
    layer: Literal["file", "content", "ledger", "external"]
    status: LayerStatus
    detail: str


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


class ReportSelfCheckItem(BaseModel):
    code: str
    name: str
    status: Literal["pass", "limited", "inconsistent"]
    detail: str
    ratio: float | None = None


class ReportSelfCheck(BaseModel):
    """识别自检：解析值能否回查到原件；只说明把握程度，不改变五态结论。"""

    status: Literal["pass", "limited", "inconsistent"]
    summary: str
    items: list[ReportSelfCheckItem] = Field(default_factory=list)


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
    trend: list[MonthlyFlow] = Field(default_factory=list)
    evidence: list[ReportEvidence] = Field(default_factory=list)
    materials: list[ReportMaterial] = Field(default_factory=list)
    self_check: ReportSelfCheck | None = None
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
) -> tuple[list[ReportEvidence], int]:
    seen: set[tuple] = set()
    result: list[ReportEvidence] = []
    missing = 0
    for item in items:
        key = (item.rule_code, item.page_no, item.row_no)
        if key in seen:
            continue
        seen.add(key)
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
    return result, missing


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
    self_check: SelfCheckResult | None = None,
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
    position_ids = _position_ids(transactions, txn_ids)
    evidence, missing = _evidence(verdict.evidence, position_ids)

    report_materials = list(materials or [])

    report_self_check: ReportSelfCheck | None = None
    limitations = list(verdict.limitations) + list(threshold_result.notes) + list(metrics.notes)
    if self_check is None:
        limitations.append("未执行识别自检，报告无法说明解析结果能否回查到原件")
    else:
        report_self_check = ReportSelfCheck(
            status=self_check.status,
            summary=self_check.summary,
            items=[
                ReportSelfCheckItem(
                    code=item.code,
                    name=item.name,
                    status=item.status,
                    detail=item.detail,
                    ratio=item.ratio,
                )
                for item in self_check.items
            ],
        )
        for item in self_check.items:
            if item.status != "pass":
                limitations.append(f"识别自检 {item.code} {item.name}：{item.detail}")
    if not report_materials:
        limitations.append("材料清单未提供，报告无法说明依据了哪几份材料")
    if missing:
        limitations.append("交易号未落库，证据定位到页/行/坐标")
    limitations = _dedupe(limitations)

    return Report(
        carrier=carrier,
        verdict=verdict.verdict,
        verdict_reason=verdict.verdict_reason,
        limitations=limitations,
        layers=[
            ReportLayer(layer=layer.layer, status=layer.status, detail=layer.detail)
            for layer in verdict.layers
        ],
        metrics=metrics.metrics,
        metric_set_version=metrics.metric_set_version,
        threshold_version=threshold_result.version,
        conclusions=threshold_result.conclusions,
        trend=metrics.trend,
        evidence=evidence,
        materials=report_materials,
        self_check=report_self_check,
        version=version,
    )
