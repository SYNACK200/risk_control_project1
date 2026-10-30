"""最小的幂等迁移：给老库补新增列（create_all 不会补列）。"""
from __future__ import annotations

from sqlalchemy import inspect, text

from . import session as db_session


def ensure_columns() -> list[str]:
    """必须在 init_db() 之后调用：engine 是懒加载的。"""
    engine = db_session.engine
    if engine is None:
        return []
    done: list[str] = []
    insp = inspect(engine)
    columns = {c["name"] for c in insp.get_columns("task")}
    with engine.begin() as conn:
        if "deleted_at" not in columns:
            conn.execute(text("ALTER TABLE task ADD COLUMN deleted_at DATETIME NULL"))
            done.append("task.deleted_at")
    return done
