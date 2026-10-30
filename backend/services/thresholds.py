"""阈值（超参）配置：读取当前生效版本、校验并保存新版本。"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from algorithm.algo.thresholds import (
    DEFAULT_THRESHOLDS,
    THRESHOLD_DEFS,
    ThresholdConfig,
    threshold_defs,
    validate_values,
)
from db.models import ThresholdProfile


def default_values() -> dict:
    values = {}
    for definition in THRESHOLD_DEFS:
        values[definition.key] = definition.default
    return values


def active_version(db: Session) -> tuple[int, dict]:
    """返回当前生效 (版本号, 参数值)；没有自定义时给算法默认值。"""
    row = db.execute(
        select(ThresholdProfile).order_by(ThresholdProfile.version.desc())
    ).scalars().first()
    if row is None:
        return DEFAULT_THRESHOLDS.version, default_values()
    return row.version, dict(row.values or {})


def build_config(db: Session) -> ThresholdConfig:
    version, values = active_version(db)
    payload = {key: (None if value is None else value) for key, value in values.items()}
    for key in ("dti_high", "income_cv_high", "low_balance_multiple", "night_ratio",
                "net_outflow_ratio", "net_outflow_month_floor", "balance_decline_ratio",
                "fast_in_out_ratio", "fast_in_out_min_amount", "counterparty_missing_ratio",
                "counterparty_hhi", "new_loan_min_income_ratio", "crypto_min_amount"):
        if payload.get(key) is not None:
            payload[key] = Decimal(str(payload[key]))
    return ThresholdConfig(version=version, **payload)


def history(db: Session, limit: int = 10) -> list[dict]:
    rows = db.execute(
        select(ThresholdProfile).order_by(ThresholdProfile.version.desc()).limit(limit)
    ).scalars().all()
    return [
        {
            "version": row.version,
            "note": row.note,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "values": row.values,
        }
        for row in rows
    ]


def save_version(db: Session, values: dict, note: str | None) -> ThresholdProfile:
    cleaned = validate_values(values)
    latest = db.execute(
        select(ThresholdProfile).order_by(ThresholdProfile.version.desc())
    ).scalars().first()
    next_version = (latest.version + 1) if latest else (DEFAULT_THRESHOLDS.version + 1)
    row = ThresholdProfile(version=next_version, values=cleaned, note=(note or "")[:255] or None)
    db.add(row)
    return row


def definitions() -> list[dict]:
    return threshold_defs()
