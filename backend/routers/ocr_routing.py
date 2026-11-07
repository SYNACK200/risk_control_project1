"""OCR 路由配置：管理员可改「多少张图走云端 API」「并发几路」。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.session import get_session
from helpers.security import current_user, require_admin
from services.ocr_routing import get_config, save_config

router = APIRouter(prefix="/ocr-routing", tags=["ocr-routing"])


class RoutingIn(BaseModel):
    enabled: bool = False
    min_images: int = Field(default=3, ge=1, le=200)
    workers: int = Field(default=2, ge=1, le=8)
    model: str = "PP-OCRv6"
    note: str | None = None


@router.get("")
def read_routing(db: Session = Depends(get_session), user=Depends(current_user)):
    from services import ocr_api  # noqa: PLC0415

    cfg = get_config(db)
    return {**cfg, "credential_ready": ocr_api.available()}


@router.put("", dependencies=[Depends(require_admin)])
def write_routing(payload: RoutingIn, db: Session = Depends(get_session),
                  user=Depends(current_user)):
    from services import ocr_api  # noqa: PLC0415

    if payload.enabled and not ocr_api.available():
        raise HTTPException(400, detail={
            "code": "E_NO_CREDENTIAL",
            "message": "没有找到云端 OCR 凭据（~/.dsh/ocr/paddle.json），无法开启云端路由",
        })
    cfg = save_config(db, payload.model_dump(), username=getattr(user, "username", None))
    return cfg
