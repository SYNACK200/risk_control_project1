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
    # 审计 detail 里会拼任务 id 列表，255 不够用（批量 61 条会超）
    try:
        acols = {c["name"]: c for c in insp.get_columns("audit_log")}
        detail_col = acols.get("detail")
        if detail_col is not None:
            max_len = getattr(detail_col.get("type"), "length", None)
            if max_len is not None and max_len < 1024:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE audit_log MODIFY COLUMN detail VARCHAR(1024) NULL"))
                done.append("audit_log.detail")
    except Exception:  # noqa: BLE001 - 老库可能还没有 audit_log
        pass
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
        ucols = {c["name"] for c in insp.get_columns("app_user")}
    except Exception:  # noqa: BLE001
        ucols = set()
    if ucols and "is_admin" not in ucols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE app_user ADD COLUMN is_admin TINYINT(1) NOT NULL DEFAULT 0"))
            conn.execute(text("UPDATE app_user SET is_admin = 1 WHERE username = 'admin'"))
        done.append("app_user.is_admin")
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
            if "deleted_at" not in tcols:
                conn.execute(text("ALTER TABLE template ADD COLUMN deleted_at DATETIME NULL"))
                done.append("template.deleted_at")
    return done