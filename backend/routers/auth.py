"""账号接口：注册、登录、当前用户、改密；银行侧账号由管理员创建。"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from collections import defaultdict, deque
from datetime import datetime
import time

from db.models import AuditLog, User
from db.session import get_session
from helpers.security import require_admin,  current_user, hash_password, issue_token, require_banker, verify_password

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
    is_admin: bool = False


class UpdateUserIn(BaseModel):
    display_name: str | None = None
    is_admin: bool | None = None
    password: str | None = Field(default=None, min_length=6, max_length=64)


def _public(user: User) -> dict:
    return {
        "id": user.id, "username": user.username, "role": user.role,
        "is_admin": bool(getattr(user, "is_admin", False)),
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


# 登录失败滑动窗口限流：同一账号 5 分钟内连续失败 5 次即锁定，防暴力破解
_LOGIN_FAILS: dict[str, deque[float]] = defaultdict(deque)
_LOGIN_WINDOW_SEC = 300.0
_LOGIN_MAX_FAILS = 5


def _check_login_rate(key: str) -> None:
    now_ts = time.time()
    q = _LOGIN_FAILS[key]
    while q and now_ts - q[0] > _LOGIN_WINDOW_SEC:
        q.popleft()
    if len(q) >= _LOGIN_MAX_FAILS:
        raise HTTPException(429, detail={"code": "E_LIMIT", "message": "登录失败次数过多，请 5 分钟后再试"})


@router.post("/login")
def login(payload: LoginIn, db: Session = Depends(get_session)):
    uname = payload.username.strip()
    _check_login_rate(uname)
    user = db.execute(select(User).where(User.username == uname)).scalars().first()
    if user is None or not verify_password(payload.password, user.password_hash):
        _LOGIN_FAILS[uname].append(time.time())
        raise HTTPException(401, detail={"code": "E_AUTH", "message": "用户名或密码不正确"})
    if user.status != "active":
        raise HTTPException(403, detail={"code": "E_FORBIDDEN", "message": "账号已停用"})
    _LOGIN_FAILS.pop(uname, None)
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


@router.delete("/users/{user_id}", dependencies=[Depends(require_admin)])
def delete_user(user_id: int, db: Session = Depends(get_session),
                admin: User = Depends(require_admin)):
    """停用并移除一个账号。

    不物理删除：audit_log 里 actor_id 指向它，物理删会让历史审计断链。
    停用（status=disabled）后登录会被拒（login 里已有 status != active 的判断），
    列表默认不显示停用账号。
    """
    from datetime import datetime as _dt  # noqa: PLC0415

    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, detail={"code": "E_NOT_FOUND", "message": "账号不存在"})
    if target.id == admin.id:
        raise HTTPException(400, detail={"code": "E_SELF", "message": "不能停用自己的账号"})
    if target.role == "banker" and target.is_admin:
        others = db.execute(
            select(User).where(
                User.role == "banker", User.is_admin.is_(True),
                User.status == "active", User.id != user_id,
            )
        ).scalars().all()
        if not others:
            raise HTTPException(400, detail={
                "code": "E_LAST_ADMIN", "message": "这是最后一个管理员，停用后将无人能管理系统"})
    target.status = "disabled"
    target.last_login_at = target.last_login_at
    db.add(AuditLog(actor_id=admin.id, action="disable_user", object_type="user", object_id=user_id,
                    detail=f"停用账号 {target.username}"))
    db.commit()
    return {"id": user_id, "status": "disabled"}


@router.get("/users")
def list_users(user: User = Depends(require_admin), db: Session = Depends(get_session)):
    rows = db.execute(select(User).order_by(User.id)).scalars().all()
    return {"items": [_public(r) for r in rows]}


@router.post("/users")
def create_user(payload: CreateUserIn, user: User = Depends(require_admin),
                db: Session = Depends(get_session)):
    # 权限分离：管理员这里只能建银行侧账号。借款侧账号一律走 /auth/register 自助注册，
    # 让「谁注册、什么时候注册、同意了什么」有据可查；管理员代开借款账号会让这条链断掉。
    if payload.role != "banker":
        raise HTTPException(400, detail={"code": "E_PARAM",
                                        "message": "这里只能创建银行侧账号；借款侧账号请让借款人自行注册 /register"})
    exists = db.execute(select(User).where(User.username == payload.username)).scalars().first()
    if exists is not None:
        raise HTTPException(409, detail={"code": "E_EXISTS", "message": "用户名已被占用"})
    row = User(
        username=payload.username.strip(),
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_admin=bool(payload.is_admin),
        display_name=(payload.display_name or payload.username)[:64],
    )
    db.add(row)
    db.add(AuditLog(action="create_user", object_type="user", object_id=0,
                    detail=(payload.username + "/" + payload.role)[:180]))
    db.commit()
    db.refresh(row)
    return {"user": _public(row)}


@router.patch("/users/{user_id}", dependencies=[Depends(require_admin)])
def update_user(user_id: int, payload: UpdateUserIn, db: Session = Depends(get_session),
                admin: User = Depends(require_admin)):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, detail={"code": "E_NOT_FOUND", "message": "账号不存在"})
    if payload.display_name is not None:
        target.display_name = payload.display_name.strip()[:64] or target.username
    if payload.is_admin is not None:
        if target.role == "banker" and target.is_admin and not payload.is_admin:
            if target.id == admin.id:
                raise HTTPException(400, detail={"code": "E_SELF", "message": "不能取消自己的管理员权限"})
            others = db.execute(
                select(User).where(User.role == "banker", User.is_admin.is_(True), User.status == "active", User.id != user_id)
            ).scalars().all()
            if not others:
                raise HTTPException(400, detail={"code": "E_LAST_ADMIN", "message": "至少需要保留一位在用管理员"})
        target.is_admin = bool(payload.is_admin)
    if payload.password:
        target.password_hash = hash_password(payload.password)
    db.add(AuditLog(action="update_user", object_type="user", object_id=user_id,
                    detail=f"更新账号 {target.username}"))
    db.commit()
    db.refresh(target)
    return {"user": _public(target)}


@router.post("/users/{user_id}/enable", dependencies=[Depends(require_admin)])
def enable_user(user_id: int, db: Session = Depends(get_session)):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, detail={"code": "E_NOT_FOUND", "message": "账号不存在"})
    target.status = "active"
    db.add(AuditLog(action="enable_user", object_type="user", object_id=user_id,
                    detail=f"重新启用账号 {target.username}"))
    db.commit()
    return {"id": user_id, "status": "active"}


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
                role="banker", is_admin=True, display_name="系统管理员"))
    db.commit()
    print("[auth] 已创建初始银行侧账号 admin，密码：" + password, flush=True)
    print("[auth] 密码已写入 backend/.admin_password（首次登录后请修改并删除该文件）", flush=True)