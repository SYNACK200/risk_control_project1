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
        if "user_id" not in columns:
            conn.execute(text("ALTER TABLE task ADD COLUMN user_id INT NULL"))
            conn.execute(text("CREATE INDEX ix_task_user_id ON task (user_id)"))
            done.append("task.user_id")
    try:
        tcols = {c["name"] for c in insp.get_columns("template")}
    except Exception:  # noqa: BLE001 - 老库可能还没有 template 表
        tcols = set()
    if tcols:
        with engine.begin() as conn:
            if "sample_file_id" not in tcols:
                conn.execute(text("ALTER TABLE template ADD COLUMN sample_file_id INT NULL"))
                done.append("template.sample_file_id")
            if "layout" not in tcols:
                conn.execute(text("ALTER TABLE template ADD COLUMN layout JSON NULL"))
                done.append("template.layout")
    return done
