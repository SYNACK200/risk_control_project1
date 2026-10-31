from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .models import ContentLayerResult, Evidence, LayerConclusion

Verdict = Literal["未发现异常", "存在不一致", "余额可疑", "来源可疑", "无法判定"]


class VerdictResult(BaseModel):
    verdict: Verdict
    verdict_reason: str
    limitations: list[str] = Field(default_factory=list)
    layers: list[LayerConclusion] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _dedupe_evidence(items: list[Evidence]) -> list[Evidence]:
    seen: set[tuple] = set()
    result: list[Evidence] = []
    for item in items:
        key = (item.rule_code, item.page_no, item.row_no)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _layer(name: str, provided: LayerConclusion | None) -> LayerConclusion:
    if provided is None:
        return LayerConclusion(layer=name, status="skipped", detail="未执行")
    if provided.layer == name:
        return provided
    return provided.model_copy(update={"layer": name})


def _content_layer(content: ContentLayerResult) -> LayerConclusion:
    detail = "；".join(
        f"{check.code} {check.name}{'提示' if check.status == 'hint' else check.status}"
        for check in content.checks
    )
    status_map = {
        "pass": "pass",
        "limited": "limited",
        "inconsistent": "fail",
        "undetermined": "undetermined",
    }
    outcome = {"inconsistent": "存在不一致", "undetermined": "无法判定"}.get(content.status)
    evidence = [
        item
        for check in content.checks
        if check.status == "fail"
        for item in check.evidence
    ]
    return LayerConclusion(
        layer="content",
        status=status_map[content.status],
        detail=detail,
        outcome=outcome,
        checks=list(content.checks),
        limitations=content.limitations,
        evidence=evidence,
    )


def _first_failure(content: ContentLayerResult, cause: str | None = None):
    for check in content.checks:
        if check.status != "fail":
            continue
        if cause is not None and (check.attribution is None or check.attribution.cause != cause):
            continue
        return check
    return None


def conclude(
    content: ContentLayerResult,
    *,
    carrier: str = "electronic",
    file_layer: LayerConclusion | None = None,
    ledger: LayerConclusion | None = None,
    external: LayerConclusion | None = None,
) -> VerdictResult:
    """五态合成。file/ledger 未接入时传 None，按未执行处理，结论封顶为未发现异常（核验受限）。"""
    file_layer = _layer("file", file_layer)
    ledger = _layer("ledger", ledger)
    external = _layer("external", external)
    content_layer = _content_layer(content)
    layers = [file_layer, content_layer, ledger, external]

    limitations: list[str] = list(content.limitations)
    if carrier == "image":
        limitations.append("影像件，核验受限，需人工复核")
    if carrier == "screenshot":
        limitations.append("截图件，不得作为授信依据")
    for layer in (file_layer, ledger, external):
        if layer.limitations:
            limitations.extend(layer.limitations)
        elif layer.status in ("skipped", "unavailable"):
            limitations.append(f"{layer.layer} 未执行")
    limitations = _dedupe(limitations)

    if carrier == "screenshot":
        return VerdictResult(
            verdict="来源可疑",
            verdict_reason="载体为截图件，结论封顶为来源可疑",
            limitations=limitations,
            layers=layers,
            evidence=file_layer.evidence,
        )

    if file_layer.outcome == "来源可疑":
        return VerdictResult(
            verdict="来源可疑",
            verdict_reason=file_layer.detail or "文件层发现来源可疑痕迹",
            limitations=limitations,
            layers=layers,
            evidence=_dedupe_evidence(file_layer.evidence),
        )

    if content.status == "inconsistent":
        failure = _first_failure(content, cause="data") or _first_failure(content)
        reason = f"内容层核对失败（数据断）：{failure.detail}" if failure else "内容层核对失败（数据断）"
        return VerdictResult(
            verdict="存在不一致",
            verdict_reason=reason,
            limitations=limitations,
            layers=layers,
            evidence=_dedupe_evidence(content_layer.evidence),
        )

    if content.status == "undetermined":
        if "未解析到交易明细，无法核对" in content.limitations:
            return VerdictResult(
                verdict="无法判定",
                verdict_reason="未解析到交易明细，无法核对",
                limitations=limitations,
                layers=layers,
                evidence=[],
            )
        failure = _first_failure(content) or next(
            (check for check in content.checks if check.status == "skipped"), None
        )
        reason = f"识别结果不可靠，无法核对：{failure.detail}" if failure else "识别结果不可靠，无法核对"
        return VerdictResult(
            verdict="无法判定",
            verdict_reason=reason,
            limitations=limitations,
            layers=layers,
            evidence=_dedupe_evidence(content_layer.evidence),
        )

    if ledger.status == "fail":
        return VerdictResult(
            verdict="余额可疑",
            verdict_reason=ledger.detail or "账务层复算偏差超容差",
            limitations=limitations,
            layers=layers,
            evidence=_dedupe_evidence(ledger.evidence),
        )

    if external.status == "fail" or external.outcome == "存在不一致":
        return VerdictResult(
            verdict="存在不一致",
            verdict_reason=external.detail or "外部数据交叉不一致",
            limitations=limitations,
            layers=layers,
            evidence=_dedupe_evidence(external.evidence),
        )

    limited = content.status == "limited" or any(
        layer.status in ("limited", "skipped", "unavailable")
        for layer in (file_layer, ledger, external)
    )
    reason = "已完成的核验未发现矛盾；部分检查不可算" if limited else "内容层核对通过，未发现矛盾"
    return VerdictResult(
        verdict="未发现异常",
        verdict_reason=reason,
        limitations=limitations,
        layers=layers,
        evidence=[],
    )
