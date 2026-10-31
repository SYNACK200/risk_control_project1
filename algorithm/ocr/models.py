from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

Direction = Literal["in", "out"]


class Template(BaseModel):
    """银行版式模板。field_map 的键为规范字段名，值为表头别名或 0 起的列序号。"""

    bank_code: str
    version: int
    field_map: dict[str, str | int] = Field(default_factory=dict)


class Transaction(BaseModel):
    page_no: int
    row_no: int
    txn_date: str | None = None
    trade_time: str | None = None  # HH:MM:SS；原件未印时分时为 None
    reference_no: str | None = None  # 银行流水号/凭证号；原件未印时为 None
    summary: str | None = None
    counterparty_name: str | None = None
    direction: Direction | None = None
    amount: Decimal | None = None
    balance: Decimal | None = None
    confidence: float = 1.0
    bbox: tuple[float, float, float, float] | None = None


class PageSummary(BaseModel):
    """页脚印的合计与笔数；文件没印的项为 None。"""

    page_no: int
    printed_count: int | None = None
    printed_in: Decimal | None = None
    printed_out: Decimal | None = None
    footer_bbox: tuple[float, float, float, float] | None = None


class HeaderField(BaseModel):
    """页眉字段值；原值保留掩码，比较时再按未掩码位对齐。"""

    value: str
    bbox: tuple[float, float, float, float] | None = None
    confidence: float = 1.0


class PageHeader(BaseModel):
    """单页页眉中可跨页比对的字段；未识别到的字段为 None，不猜。"""

    page_no: int
    account_no: HeaderField | None = None
    account_name: HeaderField | None = None
    period_start: HeaderField | None = None
    period_end: HeaderField | None = None

    @property
    def is_empty(self) -> bool:
        return all(
            getattr(self, field) is None
            for field in ("account_no", "account_name", "period_start", "period_end")
        )


class ParseResult(BaseModel):
    transactions: list[Transaction] = Field(default_factory=list)
    field_completeness: float = 0.0
    avg_confidence: float = 0.0
    low_conf_ratio: float = 0.0
    page_count: int = 0
    footer_count: int | None = None
    page_summaries: list[PageSummary] = Field(default_factory=list)
    headers: list[PageHeader] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
