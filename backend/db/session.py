"""数据库连接与会话；启动时自动建库建表。"""
from __future__ import annotations

import os
from collections.abc import Iterator

import pymysql
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DB = os.getenv("MYSQL_DB", "risk_control")


def ensure_database() -> None:
    conn = pymysql.connect(host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASSWORD)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DB}` "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
        conn.commit()
    finally:
        conn.close()


def _url() -> str:
    return (
        f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
        "?charset=utf8mb4"
    )


engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def init_db() -> None:
    """建立连接并建缺失表；连接失败时提供可执行的中文提示。"""
    global engine, SessionLocal
    if engine is not None and SessionLocal is not None:
        return
    try:
        ensure_database()
        engine = create_engine(_url(), pool_pre_ping=True, pool_recycle=1800, future=True)
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    except (pymysql.MySQLError, SQLAlchemyError) as exc:
        raise RuntimeError(
            f"数据库连接失败：请确认 MySQL 已启动，以及 MYSQL_HOST/PORT/USER/PASSWORD/DB 配置正确。原因：{exc}"
        ) from exc


def get_session() -> Iterator[Session]:
    if SessionLocal is None:
        raise RuntimeError("数据库尚未初始化；请先启动 FastAPI 应用。")
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

