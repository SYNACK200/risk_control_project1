from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CheckStatus = Literal["pass", "fail", "hint", "partial", "skipped"]
LayerStatus = Literal["pass", "fail", "limited", "skipped", "unavailable", "undetermined"]
Cause = Literal["recognition", "data"]
Action = Literal["manual", "stop"]


class Evidence(BaseModel):
    rule_code: str
    page_no: int
    x: float
    y: float
    row_no: int | None = None
    txn_id: int | None = None


class Attribution(BaseModel):
    cause: Cause
    action: Action
    detail: str


class CheckResult(BaseModel):
    code: str
    name: str
    rule_version: int = 1
    status: CheckStatus
    detail: str
    evidence: list[Evidence] = Field(default_factory=list)
    attribution: Attribution | None = None


class ContentLayerResult(BaseModel):
    """pass / limited（部分不可算）/ inconsistent（数据断）/ undetermined（识别不可靠）"""

    status: Literal["pass", "limited", "inconsistent", "undetermined"]
    checks: list[CheckResult] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class LayerConclusion(BaseModel):
    layer: Literal["file", "content", "ledger", "external"]
    status: LayerStatus
    detail: str
    outcome: str | None = None
    checks: list[CheckResult] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
