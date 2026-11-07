"""OCR 路由：决定某次解析走本地引擎还是云端 API。

规则可改（ocr_routing 表 + 管理接口），不写死在代码里：
  - enabled=false        → 一律本地
  - enabled=true 且 张数 ≥ min_images → 云端 API 并发
  - 否则                 → 本地
云端 API 单张 4–10s，本地通常更快；只有多张并发才划算，所以门槛按张数算。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from db.models import OcrRouting

DEFAULTS = {"enabled": False, "min_images": 3, "workers": 2, "model": "PP-OCRv6",
            "endpoint": None, "api_key": None}


def get_config(db) -> dict:
    row = db.execute(select(OcrRouting).order_by(OcrRouting.id)).scalars().first()
    if row is None:
        return dict(DEFAULTS)
    return {
        "enabled": bool(row.enabled),
        "min_images": int(row.min_images or DEFAULTS["min_images"]),
        "workers": int(row.workers or DEFAULTS["workers"]),
        "model": row.model or DEFAULTS["model"],
        "endpoint": row.endpoint,
        # 故意不回显 key：只说有没有。前端拿不到明文，日志也不会带出去。
        "has_api_key": bool(row.api_key),
    }


def save_config(db, payload: dict, username: str | None = None) -> dict:
    row = db.execute(select(OcrRouting).order_by(OcrRouting.id)).scalars().first()
    if row is None:
        row = OcrRouting()
        db.add(row)
    row.enabled = bool(payload.get("enabled", False))
    row.min_images = max(1, int(payload.get("min_images") or DEFAULTS["min_images"]))
    row.workers = max(1, min(8, int(payload.get("workers") or DEFAULTS["workers"])))
    row.model = (payload.get("model") or DEFAULTS["model"])[:32]
    ep = (payload.get("endpoint") or "").strip()
    row.endpoint = ep[:255] if ep else None
    # key 只在用户填了新值时才覆盖；传空串表示「不改」，避免误把已存的 key 清掉
    key = (payload.get("api_key") or "").strip()
    if key:
        row.api_key = key[:255]
    row.note = (payload.get("note") or "")[:255] or None
    row.updated_by = username
    row.updated_at = datetime.utcnow()
    db.commit()
    return get_config(db)


def should_use_api(db, image_count: int) -> tuple[bool, dict]:
    """给定图片张数，判断是否走云端 API。返回 (是否走, 配置快照)。"""
    cfg = get_config(db)
    if not cfg["enabled"]:
        return False, cfg
    return image_count >= cfg["min_images"], cfg