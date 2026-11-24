"""能力之间交换的唯一语言。

硬规则：能力只认这里的类型，不互相 import。
新增契约时同步在 CONTRACTS 登记，注册表据此校验 provides/requires。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(slots=True)
class SourceDocument:
    """受理层交进来的原始文件。"""
    data: bytes
    filename: str = ""
    mime: str = ""
    sha256: str = ""
    password: str | None = None


@dataclass(slots=True)
class DocumentProfile:
    """预读结论：这份文件是什么、能不能读。"""
    carrier: str = "unknown"          # electronic / image / screenshot / unknown
    pages: int = 0
    has_text_layer: bool = False
    encrypted: bool = False
    bank_code: str | None = None
    bank_name: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    is_statement: bool = True
    reasons: list[str] = field(default_factory=list)
    native: Any = None


@dataclass(slots=True)
class ColumnBand:
    """一列在页面上的横向带：归一化 0-1。"""
    field: str
    x: float
    w: float
    confidence: float = 1.0


@dataclass(slots=True)
class TableRegion:
    """一个表格区：页号 0 起，plus 列带与来源。"""
    page: int
    slot: str = "auto"                # first / middle / last / auto
    area: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    header_y: float | None = None
    columns: list[ColumnBand] = field(default_factory=list)
    source: str = ""                  # anchor_spread / geometry / template / model
    confidence: float = 0.0


@dataclass(slots=True)
class LayoutPlan:
    """版式结论：表格在哪、列怎么切。空 plan 表示没有可用的几何信息。"""
    page_size: tuple[float, float] | None = None
    page_count: int = 0
    regions: list[TableRegion] = field(default_factory=list)
    confidence: float = 0.0
    method: str = "none"
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TxnRow:
    txn_date: str | None = None
    trade_time: str | None = None
    reference_no: str | None = None
    direction: str | None = None       # in / out
    amount: Decimal | None = None
    balance: Decimal | None = None
    summary: str | None = None
    counterparty_name: str | None = None
    page_no: int = 0
    row_no: int = 0
    confidence: float = 1.0
    extra: dict[str, str] | None = None


@dataclass(slots=True)
class Statement:
    """解析结论：逐笔明细 + 页脚声明 + 告警。"""
    rows: list[TxnRow] = field(default_factory=list)
    footer_count: int | None = None
    page_count: int = 0
    warnings: list[str] = field(default_factory=list)
    native: Any = None


@dataclass(slots=True)
class LayerOutcome:
    layer: str                        # file / content / ledger / external
    status: str                       # pass / limited / inconsistent / undetermined / skipped
    detail: str = ""
    checks: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class LayerResult:
    """单层核验结果：四层各是一个可以单独替换、单独停用的能力。

    native 是过渡字段：判据（尤其内容层的成因区分）还在封存版本的实现里，
    换成自己的实现时这里就该为空，由 compose 重新解释。
    """
    layer: str
    status: str = "skipped"          # pass / fail / limited / skipped / unavailable / undetermined
    detail: str = ""
    outcome: str | None = None
    checks: list[dict] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    native: Any = None


@dataclass(slots=True)
class Verification:
    """核验结论：四层 + 五态 + 置信分层。"""
    verdict: str = "undetermined"
    verdict_reason: str = ""
    layers: list[LayerOutcome] = field(default_factory=list)
    trust: dict = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    native: Any = None


@dataclass(slots=True)
class MetricItem:
    code: str
    name: str
    value: Decimal | None = None
    unit: str = ""
    note: str = ""
    group: str = ""
    caliber_version: int = 1


@dataclass(slots=True)
class MetricTable:
    items: list[MetricItem] = field(default_factory=list)
    set_version: int = 1
    native: Any = None


@dataclass(slots=True)
class FeatureSet:
    """特征衍生产物：一行一个特征值，带定义版本，供指标/报告/模型消费。"""
    records: list[dict] = field(default_factory=list)
    schema: dict = field(default_factory=dict)
    version: str = "1.0"


@dataclass(slots=True)
class ReportBundle:
    payload: dict = field(default_factory=dict)
    version: int = 1


# 由流水线外部提供、不需要任何能力产出的契约（上传受理就是交一份 document 进来）。
# 装配时遇到它直接当作已满足，否则会误报「没有人产出 document」。
EXTERNAL_CONTRACTS: frozenset[str] = frozenset({"document"})


CONTRACTS: dict[str, type] = {
    "document": SourceDocument,
    "profile": DocumentProfile,
    "layout": LayoutPlan,
    "statement": Statement,
    "layer_file": LayerResult,
    "layer_content": LayerResult,
    "layer_ledger": LayerResult,
    "layer_external": LayerResult,
    "verification": Verification,
    "metrics": MetricTable,
    "features": FeatureSet,
    "report": ReportBundle,
}


def contract_names() -> tuple[str, ...]:
    return tuple(CONTRACTS)
