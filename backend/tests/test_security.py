from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from helpers import security
from main import app


@pytest.fixture(autouse=True)
def local_password(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        security,
        "settings",
        replace(security.settings, local_access_password="local-test-password"),
    )


def test_password_comparison_rejects_missing_and_wrong_values():
    assert security.password_matches("local-test-password", "local-test-password")
    assert not security.password_matches(None, "local-test-password")
    assert not security.password_matches("wrong", "local-test-password")
    assert not security.password_matches("local-test-password", None)


def test_bank_endpoint_requires_bearer_password():
    client = TestClient(app)

    denied = client.get("/api/v1/metric-definitions")
    accepted = client.get(
        "/api/v1/metric-definitions",
        headers={"Authorization": "Bearer local-test-password"},
    )

    assert denied.status_code == 401
    assert denied.json()["detail"]["code"] == "E_AUTH"
    assert accepted.status_code == 200
    assert accepted.json()["items"]
