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

    # custom_<指标代号>_max 不是 ThresholdConfig 的字段，要单独收进 custom 字典，
    # 否则 validate_values 放行了、这里又会因为「多余字段」报错。
    custom: dict[str, Decimal] = {}
    for key, val in list(payload.items()):
        if not key.startswith("custom_") or val is None:
            continue
        payload.pop(key)
        # custom_OUTFLOW_TOTAL_max -> OUTFLOW_TOTAL
        code = key[len("custom_"):]
        code = code[:-len("_max")] if code.endswith("_max") else code
        try:
            custom[code] = Decimal(str(val))
        except Exception:  # noqa: BLE001
            continue
    if custom:
        payload["custom"] = custom
    return ThresholdConfig(version=version, **payload)


def history(db: Session, limit: int = 10) -> list[dict]:
    """阈值版本历史，附带「同一时期的口径变更」。

    为什么联动：阈值是绑在指标口径上的——口径新增了字段、删了字段，阈值是否还成立就变了。
    只看阈值自己的历史，会读成「阈值没动过」，其实是口径动了。
    """
    rows = db.execute(
        select(ThresholdProfile).order_by(ThresholdProfile.version.desc()).limit(limit)
    ).scalars().all()
    items = [
        {
            "version": row.version,
            "note": row.note,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "values": row.values,
        }
        for row in rows
    ]

    # 口径变更事件（新增/删除自定义指标），按时间到版本映射
    from db.models import AuditLog  # noqa: PLC0415

    metric_events = db.execute(
        select(AuditLog)
        .where(AuditLog.action.in_(("add_metric", "remove_metric")))
        .order_by(AuditLog.created_at.desc())
        .limit(50)
    ).scalars().all()
    # 每个版本只挂「这个版本之后」发生的口径变更——否则所有版本都会显示同一批事件，读不出先后
    from datetime import datetime as _dt

    for item, row in zip(items, rows):
        since = row.created_at
        item["related_metrics"] = [
            {
                "action": "新增口径" if ev.action == "add_metric" else "删除口径",
                "detail": ev.detail,
                "at": ev.created_at.isoformat() if ev.created_at else None,
            }
            for ev in metric_events
            if ev.created_at is not None and (since is None or ev.created_at >= since)
        ]
    return items


def save_version(db: Session, values: dict, note: str | None) -> ThresholdProfile:
    cleaned = validate_values(values)
    latest = db.execute(
        select(ThresholdProfile).order_by(ThresholdProfile.version.desc())
    ).scalars().first()
    next_version = (latest.version + 1) if latest else (DEFAULT_THRESHOLDS.version + 1)
    row = ThresholdProfile(version=next_version, values=cleaned, note=(note or "")[:255] or None)
    db.add(row)
    return row


def custom_metric_thresholds(db) -> list[dict]:
    """把启用的自定义指标也做成阈值项。

    没有这一层，自定义指标算出来只是个数字——不会触发任何结论，
    在判定阈值页也看不见，等于白算。
    键名约定 custom_<code>_max：超过它就命中，和内置阈值同一套比较口径。
    """
    from db.models import CustomMetric  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    rows = db.execute(
        select(CustomMetric).where(CustomMetric.enabled.is_(True)).order_by(CustomMetric.code)
    ).scalars().all()
    out = []
    for r in rows:
        out.append({
            "key": f"custom_{r.code}_max",
            "label": f"{r.name}上限",
            "group": "自定义指标",
            "kind": "max",
            "unit": r.unit or "",
            "default": None,          # 不设默认：没配就是不启用，避免误伤
            "minimum": None,
            "maximum": None,
            "desc": (r.note or f"{r.name}的触发上限；留空表示不按这一项判定") + f"（指标 {r.code}）",
            "impacts": [r.code],
            "calibrated": False,
            "custom": True,
            "metric_code": r.code,
        })
    return out


def definitions(db=None) -> list[dict]:
    base = threshold_defs()
    if db is None:
        return base
    try:
        return base + custom_metric_thresholds(db)
    except Exception:  # noqa: BLE001
        return base