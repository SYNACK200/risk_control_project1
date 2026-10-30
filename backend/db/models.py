"""数据表模型：按 contract.md 的十一张表建，字段名保持英文原名。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def now() -> datetime:
    return datetime.now()


class StaffUser(Base):
    __tablename__ = "staff_user"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(32))  # 审批人/模板管理员/运营管理员/系统管理员
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class FileObj(Base):
    __tablename__ = "file_obj"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    mime: Mapped[str | None] = mapped_column(String(64))
    carrier: Mapped[str | None] = mapped_column(String(16))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    pages: Mapped[int | None] = mapped_column(Integer)
    has_text_layer: Mapped[bool | None] = mapped_column(Boolean)
    storage_path: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Task(Base):
    __tablename__ = "task"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    biz_no: Mapped[str] = mapped_column(String(32), unique=True)
    task_type: Mapped[str] = mapped_column(String(16), default="credit")
    channel: Mapped[str] = mapped_column(String(16), default="upload")
    file_id: Mapped[int | None] = mapped_column(ForeignKey("file_obj.id"))
    carrier: Mapped[str | None] = mapped_column(String(16))
    template_id: Mapped[int | None] = mapped_column(Integer)
    template_version: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="PENDING")
    check_result: Mapped[dict | None] = mapped_column(JSON)
    period_start: Mapped[str | None] = mapped_column(String(16))
    period_end: Mapped[str | None] = mapped_column(String(16))
    hits: Mapped[dict | None] = mapped_column(JSON)
    failure_code: Mapped[str | None] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class TaskFile(Base):
    __tablename__ = "task_file"
    __table_args__ = (UniqueConstraint("task_id", "seq", name="uq_task_seq"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task.id"))
    file_id: Mapped[int] = mapped_column(ForeignKey("file_obj.id"))
    role: Mapped[str] = mapped_column(String(16), default="original")
    seq: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class BankAccount(Base):
    __tablename__ = "bank_account"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task.id"))
    account_no: Mapped[str | None] = mapped_column(String(64))
    bank_name: Mapped[str | None] = mapped_column(String(64))
    period_start: Mapped[str | None] = mapped_column(String(16))
    period_end: Mapped[str | None] = mapped_column(String(16))
    opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    closing_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))


class Txn(Base):
    __tablename__ = "txn"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task.id"), index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("bank_account.id"))
    txn_date: Mapped[str | None] = mapped_column(String(16))
    direction: Mapped[str | None] = mapped_column(String(8))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    summary: Mapped[str | None] = mapped_column(String(255))
    counterparty_name: Mapped[str | None] = mapped_column(String(255))
    page_no: Mapped[int | None] = mapped_column(Integer)
    coord_x: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    coord_y: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    drop_reason: Mapped[str | None] = mapped_column(String(64))


class MetricValue(Base):
    __tablename__ = "metric_value"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task.id"), index=True)
    metric_code: Mapped[str] = mapped_column(String(16))
    metric_name: Mapped[str] = mapped_column(String(64))
    value_num: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    unit: Mapped[str | None] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(String(255))
    caliber_version: Mapped[int] = mapped_column(Integer, default=1)


class Report(Base):
    __tablename__ = "report"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    carrier: Mapped[str | None] = mapped_column(String(16))
    verdict: Mapped[str | None] = mapped_column(String(32))
    verdict_reason: Mapped[str | None] = mapped_column(String(255))
    layers: Mapped[list | None] = mapped_column(JSON)
    limitations: Mapped[list | None] = mapped_column(JSON)
    evidence: Mapped[list | None] = mapped_column(JSON)
    materials: Mapped[list | None] = mapped_column(JSON)
    metric_set_version: Mapped[int | None] = mapped_column(Integer)
    threshold_version: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Template(Base):
    __tablename__ = "template"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bank_code: Mapped[str] = mapped_column(String(16), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft/enabled/disabled
    field_map: Mapped[dict | None] = mapped_column(JSON)
    header_columns: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Rule(Base):
    __tablename__ = "rule"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_code: Mapped[str] = mapped_column(String(32), unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    category: Mapped[str | None] = mapped_column(String(32))
    expr: Mapped[str | None] = mapped_column(Text)
    threshold: Mapped[dict | None] = mapped_column(JSON)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(32))
    object_type: Mapped[str | None] = mapped_column(String(32))
    object_id: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)



class ThresholdProfile(Base):
    """银行自定义阈值的一次快照；最新 version 生效，旧版本保留可追溯。"""
    __tablename__ = "threshold_profile"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    values: Mapped[dict] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
