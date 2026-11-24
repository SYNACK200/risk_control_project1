"""持久化抽象：service 只认 QueueStore 这一层。

为什么重试/状态机不写进 store：两套实现各写一遍必然漂移，MemoryStore 就再也当不了
行为基线。store 只提供六个原语（加、取、列、原子领取、条件写回、清空），
规则全部集中在 service。

两个实现必须行为一致：
- MemoryStore：测试与单进程演示用，一把 RLock 保住线程安全；
- SqlAlchemyStore：声明式模型，测试跑 sqlite:///:memory:，生产可换成 MySQL，
  原子性由「条件 UPDATE + rowcount」保证（单机 sqlite 额外加锁串行，见类注释）。
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Mapping, Protocol, runtime_checkable

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, delete, or_, select, update
from sqlalchemy.engine import create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Job, QUEUED, RUNNING, as_utc


@runtime_checkable
class QueueStore(Protocol):
    """存储层契约。list() 的顺序即领取顺序：priority 大在前，同优先级 seq 小在前。"""

    def add(self, job: Job) -> Job: ...

    def get(self, job_id: str) -> Job | None: ...

    def list(self, status: str | None = None) -> list[Job]: ...

    def claim(self, worker_id: str, now: datetime, lease_until: datetime) -> Job | None: ...

    def write(self, job: Job, expect: Mapping[str, Any] | None = None) -> bool: ...

    def clear(self) -> None: ...


def _rank(job: Job) -> tuple[int, int]:
    return (-job.priority, job.seq)


class MemoryStore:
    """内存实现：进程内演示与单元测试用。

    内部只存副本，进出都不给调用方共享引用——否则 SqlAlchemyStore 读回来的对象
    和这里的可变对象行为会不一样，参数化测试就失去意义。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._seq = 0

    # ---- 原语 ----
    def add(self, job: Job) -> Job:
        with self._lock:
            self._seq += 1
            stored = job.copy()
            stored.seq = self._seq
            self._jobs[stored.id] = stored
            return stored.copy()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.copy() if job else None

    def list(self, status: str | None = None) -> list[Job]:
        with self._lock:
            jobs = [j for j in self._jobs.values() if status is None or j.status == status]
            jobs.sort(key=_rank)
            return [j.copy() for j in jobs]

    def claim(self, worker_id: str, now: datetime, lease_until: datetime) -> Job | None:
        # 整段在锁内完成：挑队首与改成 running 之间不允许别人插进来，这就是「原子领取」
        with self._lock:
            due = [
                j
                for j in self._jobs.values()
                if j.status == QUEUED and (j.next_run_at is None or as_utc(j.next_run_at) <= as_utc(now))
            ]
            if not due:
                return None
            job = min(due, key=_rank)
            job.status = RUNNING
            job.worker_id = worker_id
            job.attempts += 1
            job.started_at = as_utc(now)
            job.heartbeat_at = as_utc(now)
            job.lease_until = as_utc(lease_until)
            job.progress = 0.0
            job.stage = ""
            return job.copy()

    def write(self, job: Job, expect: Mapping[str, Any] | None = None) -> bool:
        with self._lock:
            current = self._jobs.get(job.id)
            if current is None:
                return False
            for name, value in (expect or {}).items():
                if getattr(current, name) != value:
                    return False
            self._jobs[job.id] = job.copy()
            return True

    def clear(self) -> None:
        with self._lock:
            self._jobs.clear()


class _Base(DeclarativeBase):
    pass


class JobRow(_Base):
    """表结构与 Job 一一映射。

    seq 用自增主键，只用于同优先级 FIFO；时间戳精度不够时它是唯一的稳定次序。
    时间列统一 naive UTC：MySQL DATETIME 不存时区，读写在 _to_db/_from_db 里补齐。
    """

    __tablename__ = "rc_queue_job"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    biz_no: Mapped[str | None] = mapped_column(String(128), default=None, index=True)
    status: Mapped[str] = mapped_column(String(16), default=QUEUED, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    stage: Mapped[str] = mapped_column(String(64), default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    worker_id: Mapped[str | None] = mapped_column(String(64), default=None)
    enqueued_at: Mapped[datetime] = mapped_column(DateTime)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, default=None)


_JOB_FIELDS = (
    "id",
    "biz_no",
    "status",
    "priority",
    "attempts",
    "max_attempts",
    "stage",
    "progress",
    "payload",
    "error",
    "worker_id",
    "enqueued_at",
    "started_at",
    "finished_at",
    "heartbeat_at",
    "next_run_at",
    "lease_until",
)
_DATETIME_FIELDS = frozenset(
    {"enqueued_at", "started_at", "finished_at", "heartbeat_at", "next_run_at", "lease_until"}
)


def _to_db(field: str, value: Any) -> Any:
    if field in _DATETIME_FIELDS and value is not None:
        stamped = as_utc(value)
        return stamped.replace(tzinfo=None) if stamped else None
    return value


def _from_db(row: JobRow) -> Job:
    data = {name: getattr(row, name) for name in _JOB_FIELDS}
    data["seq"] = int(row.seq)
    for name in _DATETIME_FIELDS:
        data[name] = as_utc(data[name])
    data["payload"] = dict(data["payload"] or {})
    return Job(**data)


class SqlAlchemyStore:
    """SQLAlchemy 2.x 实现：测试走 sqlite:///:memory:，生产接 MySQL。

    并发正确性靠「条件 UPDATE + rowcount == 1」：谁把 status 从 queued 改成 running
    谁赢，输的人换下一个候选。单机 sqlite 内存库所有线程共用一条连接（StaticPool），
    并发访问同一条连接会炸事务，所以进程内再加一把锁串行化——MySQL 下这把锁没有
    必要，但也只是多一层本地串行，不影响跨进程正确性。
    """

    def __init__(self, dsn: str = "sqlite:///:memory:", *, echo: bool = False, create_schema: bool = True):
        self.dsn = dsn
        kwargs: dict[str, Any] = {"echo": echo}
        if dsn.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if ":memory:" in dsn or dsn.rstrip("/") == "sqlite:":
                # 内存库每条连接都是一份空库，必须复用同一条连接
                kwargs["poolclass"] = StaticPool
        self._engine = create_engine(dsn, **kwargs)
        self._lock = threading.RLock()
        self._sessions = sessionmaker(bind=self._engine, expire_on_commit=False)
        if create_schema:
            # 生产由迁移脚本建表；这里建一次是幂等的，方便自测与本地起服务
            _Base.metadata.create_all(self._engine)

    # ---- 原语 ----
    def add(self, job: Job) -> Job:
        with self._lock, self._sessions() as session:
            session.add(JobRow(**{name: _to_db(name, getattr(job, name)) for name in _JOB_FIELDS}))
            session.commit()
            job_id = job.id
        stored = self.get(job_id)
        assert stored is not None  # 刚提交的行，取不到就是驱动/事务坏了
        return stored

    def get(self, job_id: str) -> Job | None:
        with self._lock, self._sessions() as session:
            row = session.scalars(select(JobRow).where(JobRow.id == job_id)).first()
            return _from_db(row) if row is not None else None

    def list(self, status: str | None = None) -> list[Job]:
        stmt = select(JobRow)
        if status is not None:
            stmt = stmt.where(JobRow.status == status)
        stmt = stmt.order_by(JobRow.priority.desc(), JobRow.seq.asc())
        with self._lock, self._sessions() as session:
            return [_from_db(row) for row in session.scalars(stmt)]

    def claim(self, worker_id: str, now: datetime, lease_until: datetime) -> Job | None:
        stamp = _to_db("started_at", now)
        deadline = _to_db("lease_until", lease_until)
        with self._lock, self._sessions() as session:
            # 候选抢不到就换下一个：说明别人先改了状态，重查一次比让调用方重试更省事
            for _ in range(8):
                candidates = list(
                    session.scalars(
                        select(JobRow.id)
                        .where(
                            JobRow.status == QUEUED,
                            or_(JobRow.next_run_at.is_(None), JobRow.next_run_at <= stamp),
                        )
                        .order_by(JobRow.priority.desc(), JobRow.seq.asc())
                        .limit(8)
                    )
                )
                if not candidates:
                    return None
                for job_id in candidates:
                    result = session.execute(
                        update(JobRow)
                        .where(JobRow.id == job_id, JobRow.status == QUEUED)
                        .values(
                            status=RUNNING,
                            worker_id=worker_id,
                            attempts=JobRow.attempts + 1,
                            started_at=stamp,
                            heartbeat_at=stamp,
                            lease_until=deadline,
                            progress=0.0,
                            stage="",
                        )
                        .execution_options(synchronize_session=False)
                    )
                    if result.rowcount == 1:
                        session.commit()
                        return self.get(job_id)
                session.rollback()
            return None

    def write(self, job: Job, expect: Mapping[str, Any] | None = None) -> bool:
        conditions = [JobRow.id == job.id]
        for name, value in (expect or {}).items():
            column = getattr(JobRow, name, None)
            if column is None:
                raise ValueError(f"未知的期望字段：{name}")
            conditions.append(column == _to_db(name, value))
        values = {name: _to_db(name, getattr(job, name)) for name in _JOB_FIELDS if name != "id"}
        with self._lock, self._sessions() as session:
            result = session.execute(
                update(JobRow)
                .where(*conditions)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                session.rollback()
                return False
            session.commit()
            return True

    def clear(self) -> None:
        with self._lock, self._sessions() as session:
            session.execute(delete(JobRow))
            session.commit()

    # ---- 排障用 ----
    def table_name(self) -> str:
        return JobRow.__tablename__
