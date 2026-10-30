"""本地账号体系：密码哈希、令牌签发/校验、角色依赖。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from config import settings
from db.models import User
from db.session import get_session

_bearer = HTTPBearer(auto_error=False)

ITERATIONS = 120_000
TOKEN_TTL_SECONDS = 12 * 3600


def _secret() -> bytes:
    return os.getenv("AUTH_SECRET", "dev-secret-change-me").encode("utf-8")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), ITERATIONS)
    return "pbkdf2$sha256$" + str(ITERATIONS) + "$" + salt + "$" + digest.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, algo, iterations, salt, digest = stored.split("$")
        if scheme != "pbkdf2" or algo != "sha256":
            return False
        computed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations))
        return hmac.compare_digest(computed.hex(), digest)
    except (ValueError, TypeError):
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_token(user: User) -> str:
    payload = {"uid": user.id, "role": user.role, "exp": int(time.time()) + TOKEN_TTL_SECONDS}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return body + "." + signature


def decode_token(token: str) -> dict:
    try:
        body, signature = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("令牌格式不正确") from exc
    expected = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, signature):
        raise ValueError("令牌签名不正确")
    payload = json.loads(_unb64(body).decode("utf-8"))
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("令牌已过期")
    return payload


def password_matches(provided: str | None, expected: str | None) -> bool:
    return bool(provided and expected and hmac.compare_digest(provided, expected))


def require_local_access(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """服务端总开关（可选）：未配置则不拦截。"""
    expected = settings.local_access_password
    if not expected:
        return
    token = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else None
    if not password_matches(token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "E_AUTH", "message": "本地访问口令无效或缺失"},
            headers={"WWW-Authenticate": "Bearer"},
        )


def _token_from(credentials: HTTPAuthorizationCredentials | None) -> str | None:
    if credentials and credentials.scheme.lower() == "bearer":
        return credentials.credentials
    return None


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_session),
) -> User:
    token = _token_from(credentials)
    if not token:
        raise HTTPException(status_code=401, detail={"code": "E_AUTH", "message": "请先登录"})
    try:
        payload = decode_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail={"code": "E_AUTH", "message": str(exc)}) from exc
    user = db.get(User, int(payload.get("uid", 0)))
    if user is None:
        raise HTTPException(status_code=401, detail={"code": "E_AUTH", "message": "账号不存在"})
    if user.status != "active":
        raise HTTPException(status_code=403, detail={"code": "E_FORBIDDEN", "message": "账号已停用"})
    return user


def require_banker(user: User = Depends(current_user)) -> User:
    if user.role != "banker":
        raise HTTPException(status_code=403, detail={"code": "E_FORBIDDEN", "message": "需要银行侧账号"})
    return user
