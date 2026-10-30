"""本地环境的临时访问保护。正式 RBAC 上线前统一从这里校验。"""
from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import settings

_bearer = HTTPBearer(auto_error=False)


def password_matches(provided: str | None, expected: str | None) -> bool:
    """常量时间比较；配置缺失时必须拒绝，不能意外开放受保护接口。"""
    return bool(provided and expected and hmac.compare_digest(provided, expected))


def require_local_access(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """要求 ``Authorization: Bearer $LOCAL_ACCESS_PASSWORD``。"""
    if not settings.local_access_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "E_AUTH", "message": "服务端尚未配置本地访问口令"},
        )
    token = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else None
    if not password_matches(token, settings.local_access_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "E_AUTH", "message": "本地访问口令无效或缺失"},
            headers={"WWW-Authenticate": "Bearer"},
        )
