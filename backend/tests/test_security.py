from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from helpers import security
from main import app


def test_password_comparison_rejects_missing_and_wrong_values():
    assert security.password_matches("local-test-password", "local-test-password")
    assert not security.password_matches(None, "local-test-password")
    assert not security.password_matches("wrong", "local-test-password")
    assert not security.password_matches("local-test-password", None)


def test_hash_and_verify_roundtrip():
    stored = security.hash_password("pass1234")
    assert stored.startswith("pbkdf2$sha256$")
    assert security.verify_password("pass1234", stored)
    assert not security.verify_password("wrong", stored)
    assert not security.verify_password("pass1234", "garbage")


def test_token_roundtrip_and_expiry(monkeypatch: pytest.MonkeyPatch):
    user = SimpleNamespace(id=7, role="banker")
    token = security.issue_token(user)
    payload = security.decode_token(token)
    assert payload["uid"] == 7
    assert payload["role"] == "banker"

    original = security.TOKEN_TTL_SECONDS
    monkeypatch.setattr(security, "TOKEN_TTL_SECONDS", -1)
    expired = security.issue_token(user)
    with pytest.raises(ValueError):
        security.decode_token(expired)
    monkeypatch.setattr(security, "TOKEN_TTL_SECONDS", original)


def test_business_endpoint_requires_token():
    # 用上下文管理器启动 lifespan，依赖（数据库会话）才会初始化
    with TestClient(app) as client:
        denied = client.get("/api/v1/tasks?limit=1")
    assert denied.status_code == 401
    assert denied.json()["detail"]["code"] == "E_AUTH"
