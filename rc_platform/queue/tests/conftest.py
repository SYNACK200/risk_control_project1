"""夹具：同一套用例在两种存储上各跑一遍，两种实现行为不一致就失败。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from rc_platform.queue import MemoryStore, QueueService, SqlAlchemyStore


class Clock:
    """可控时钟：退避与租约过期的用例不该靠 sleep 等真时间。"""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> datetime:
        self.now = self.now + timedelta(seconds=seconds)
        return self.now


@pytest.fixture(params=["memory", "sqlalchemy"])
def store(request):
    instance = MemoryStore() if request.param == "memory" else SqlAlchemyStore("sqlite:///:memory:")
    try:
        yield instance
    finally:
        instance.clear()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def service(store, clock) -> QueueService:
    return QueueService(store, clock=clock)
