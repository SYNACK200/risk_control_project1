"""账号接口：注册、登录、当前用户、改密；银行侧账号由管理员创建。"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from datetime import datetime

from db.models import AuditLog, User
from db.session import get_session
from helpers.security import current_user, hash_password, issue_token, require_banker, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=64)
    display_name: str | None = None


class LoginIn(BaseModel):
    username: str
    password: str


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=64)


class CreateUserIn(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=64)
    role: str = "banker"
    display_name: str | None = None


def _public(user: User) -> dict:
    return {
        "id": user.id, "username": user.username, "role": user.role,
        "display_name": user.display_name, "status": user.status,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


@router.post("/register")
def register(payload: RegisterIn, db: Session = Depends(get_session)):
    # 自助注册一律是借款侧账号；银行侧账号必须由管理员创建
    exists = db.execute(select(User).where(User.username == payload.username)).scalars().first()
    if exists is not None:
        raise HTTPException(409, detail={"code": "E_EXISTS", "message": "用户名已被占用"})
    user = User(
        username=payload.username.strip(),
        password_hash=hash_password(payload.password),
        role="borrower",
        display_name=(payload.display_name or payload.username)[:64],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"token": issue_token(user), "user": _public(user)}


@router.post("/login")
def login(payload: LoginIn, db: Session = Depends(get_session)):
    user = db.execute(select(User).where(User.username == payload.username.strip())).scalars().first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, detail={"code": "E_AUTH", "message": "用户名或密码不正确"})
    if user.status != "active":
        raise HTTPException(403, detail={"code": "E_FORBIDDEN", "message": "账号已停用"})
    user.last_login_at = datetime.utcnow()
    db.commit()
    return {"token": issue_token(user), "user": _public(user)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"user": _public(user)}


@router.post("/change-password")
def change_password(payload: ChangePasswordIn, user: User = Depends(current_user),
                    db: Session = Depends(get_session)):
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(400, detail={"code": "E_AUTH", "message": "原密码不正确"})
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"changed": True}


@router.get("/users")
def list_users(user: User = Depends(require_banker), db: Session = Depends(get_session)):
    rows = db.execute(select(User).order_by(User.id)).scalars().all()
    return {"items": [_public(r) for r in rows]}


@router.post("/users")
def create_user(payload: CreateUserIn, user: User = Depends(require_banker),
                db: Session = Depends(get_session)):
    if payload.role not in ("banker", "borrower"):
        raise HTTPException(400, detail={"code": "E_PARAM", "message": "role 只能是 banker 或 borrower"})
    exists = db.execute(select(User).where(User.username == payload.username)).scalars().first()
    if exists is not None:
        raise HTTPException(409, detail={"code": "E_EXISTS", "message": "用户名已被占用"})
    row = User(username=payload.username.strip(), password_hash=hash_password(payload.password),
               role=payload.role, display_name=(payload.display_name or payload.username)[:64])
    db.add(row)
    db.add(AuditLog(action="create_user", object_type="user", object_id=0,
                    detail=(payload.username + "/" + payload.role)[:180]))
    db.commit()
    db.refresh(row)
    return {"user": _public(row)}


def seed_admin(db: Session) -> None:
    """首次启动没有银行侧账号时创建 admin（密码取 ADMIN_PASSWORD，默认 admin123）。"""
    count = db.execute(select(func.count(User.id)).where(User.role == "banker")).scalar() or 0
    if count:
        return
    password = os.getenv("ADMIN_PASSWORD")
    if not password:
        password = secrets.token_urlsafe(9)
        path = Path(__file__).resolve().parents[1] / ".admin_password"
        path.write_text(password, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    db.add(User(username="admin", password_hash=hash_password(password),
                role="banker", display_name="系统管理员"))
    db.commit()
    print("[auth] 已创建初始银行侧账号 admin，密码：" + password, flush=True)
    print("[auth] 密码已写入 backend/.admin_password（首次登录后请修改并删除该文件）", flush=True)
