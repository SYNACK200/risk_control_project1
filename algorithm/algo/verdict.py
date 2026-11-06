from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .models import ContentLayerResult, Evidence, LayerConclusion

Verdict = Literal["未发现异常", "存在不一致", "余额可疑", "来源可疑", "无法判定"]


class LayerTrust(BaseModel):
    """单个核验层的得分与权重，用于解释真实性总分的构成。"""
    layer: str
    label: str
    status: str
    score: float          # 0-100
    weight: float         # 归一化后的权重
    note: str = ""


class TrustScore(BaseModel):
    """真实性加权得分：比五态结论更细，能反映「各层做了多少、结论有多硬」。"""
    score: float = 0.0            # 0-100
    level: str = "unknown"        # high / medium / low / unknown
    label: str = "未知"
    carrier: str = "electronic"
    layers: list[LayerTrust] = Field(default_factory=list)
    note: str = ""


class VerdictResult(BaseModel):
    verdict: Verdict
    verdict_reason: str
    limitations: list[str] = Field(default_factory=list)
    layers: list[LayerConclusion] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    trust: TrustScore | None = None


# 真实性各层的默认权重。
# 设计取向：内容层与账务层直接反映「流水本身对不对」，是主体；
# 载体层（PDF 结构取证）与外部层（跨机构交叉核验）只作辅证——
# 借款人上传影像件很常见，载体层本就不该一票定生死；外部层多数场景未接入，
# 权重过高会让总分长期失真。载体不同时按 CARRIER_ADJ 再调（见下）。
TRUST_WEIGHTS: dict[str, float] = {
    "content": 0.45,
    "ledger": 0.30,
    "file": 0.15,
    "external": 0.10,
}

# 载体修正系数：影像/截图件的载体层证据本就弱，进一步降权；
# 但降低的部分要按比例回流到内容层与账务层（它们对影像件仍然可测），
# 不能简单丢弃——否则影像件的真实性永远算不出来。
CARRIER_ADJ: dict[str, dict[str, float]] = {
    "electronic": {},
    "image": {"file": 0.5, "external": 0.8},
    "screenshot": {"file": 0.3, "external": 0.6},
}

LAYER_LABEL = {"content": "内容层", "ledger": "账务层", "file": "载体层", "external": "外部层"}

# 各层状态对应的基准分（0-100）
_STATUS_SCORE = {
    "pass": 100.0,
    "limited": 70.0,
    "skipped": 0.0,
    "unavailable": 0.0,
    "fail": 0.0,
}


def _layer_score(status: str, outcome: str | None = None) -> float:
    if outcome in ("存在不一致", "来源可疑", "余额可疑"):
        return 0.0
    return _STATUS_SCORE.get(status, 50.0)


def _trust_score(layers: list[LayerConclusion], carrier: str) -> TrustScore:
    """按层状态与载体修正，算真实性加权得分。未执行的层不计入分母。"""
    adj = CARRIER_ADJ.get(carrier, {})
    raw: dict[str, float] = {}
    for layer in layers:
        weight = TRUST_WEIGHTS.get(layer.layer, 0.0) * adj.get(layer.layer, 1.0)
        if layer.status in ("skipped", "unavailable"):
            # 未执行：不参与加权（避免把「没查」算成「差」），但会体现在 note 里
            continue
        raw[layer.layer] = weight
    total_weight = sum(raw.values())

    items: list[LayerTrust] = []
    score = 0.0
    for layer in layers:
        weight_raw = TRUST_WEIGHTS.get(layer.layer, 0.0) * adj.get(layer.layer, 1.0)
        # 未执行的层不参与加权，权重显示 0（避免「0.111 权重却不计分」的误读）
        norm = (weight_raw / total_weight) if (total_weight and layer.layer in raw) else 0.0
        s = _layer_score(layer.status, getattr(layer, "outcome", None))
        if layer.layer in raw:
            score += s * norm
        items.append(LayerTrust(
            layer=layer.layer,
            label=LAYER_LABEL.get(layer.layer, layer.layer),
            status=layer.status,
            score=round(s, 1),
            weight=round(norm, 3),
            note=("未执行，不参与加权" if layer.layer not in raw else (layer.detail or "")[:80]),
        ))

    skipped = [i.label for i in items if i.status in ("skipped", "unavailable")]
    note = ""
    if skipped:
        note = "未执行层（不计入加权）：" + "、".join(skipped)
    if carrier != "electronic":
        note = (note + "；" if note else "") + f"载体为 {carrier}，载体层权重已下调"

    if total_weight <= 0:
        return TrustScore(score=0.0, level="unknown", label="无法评估",
                          carrier=carrier, layers=items, note=note or "所有核验层均未执行")
    if score >= 80:
        level, label = "high", "较高"
    elif score >= 55:
        level, label = "medium", "一般"
    else:
        level, label = "low", "较低"
    return TrustScore(score=round(score, 1), level=level, label=label,
                      carrier=carrier, layers=items, note=note)


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
    trust = _trust_score(layers, carrier)

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
        trust=trust,
            evidence=file_layer.evidence,
        )

    if file_layer.outcome == "来源可疑":
        return VerdictResult(
            verdict="来源可疑",
            verdict_reason=file_layer.detail or "文件层发现来源可疑痕迹",
            limitations=limitations,
            layers=layers,
        trust=trust,
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
        trust=trust,
            evidence=_dedupe_evidence(content_layer.evidence),
        )

    if content.status == "undetermined":
        if "未解析到交易明细，无法核对" in content.limitations:
            return VerdictResult(
                verdict="无法判定",
                verdict_reason="未解析到交易明细，无法核对",
                limitations=limitations,
                layers=layers,
        trust=trust,
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
        trust=trust,
            evidence=_dedupe_evidence(content_layer.evidence),
        )

    if ledger.status == "fail":
        return VerdictResult(
            verdict="余额可疑",
            verdict_reason=ledger.detail or "账务层复算偏差超容差",
            limitations=limitations,
            layers=layers,
        trust=trust,
            evidence=_dedupe_evidence(ledger.evidence),
        )

    if external.status == "fail" or external.outcome == "存在不一致":
        return VerdictResult(
            verdict="存在不一致",
            verdict_reason=external.detail or "外部数据交叉不一致",
            limitations=limitations,
            layers=layers,
        trust=trust,
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
        trust=trust,
        evidence=[],
    )