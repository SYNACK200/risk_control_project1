"""后端入口：启动时自动建库建表，挂载任务/报告/模板接口。"""
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from db.session import init_db
from helpers.logging_config import configure_logging
from routers import audit, auth, entities, reports, tasks, templates, thresholds

logger = logging.getLogger("risk_control")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    init_db()
    ensure_columns()
    from db.session import SessionLocal
    from routers.auth import seed_admin

    session = SessionLocal()
    try:
        seed_admin(session)
    finally:
        session.close()
    logger.info("服务启动；数据库已就绪（缺表自动创建）。")
    try:
        yield
    finally:
        logger.info("服务已停止。")


from db.migrate import ensure_columns

app = FastAPI(title=settings.app_name, version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://127.0.0.1:5174",
                   "http://localhost:5173", "http://localhost:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks.router, prefix=settings.api_prefix)
app.include_router(reports.router, prefix=settings.api_prefix)
app.include_router(templates.router, prefix=settings.api_prefix)
app.include_router(entities.router, prefix=settings.api_prefix)
app.include_router(audit.router, prefix=settings.api_prefix)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(thresholds.router, prefix=settings.api_prefix)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/health")
def health_v1():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level=settings.log_level.lower())


# ---- 内置前端静态托管：一个进程即可独立运行，不依赖任何开发服务器 ----
from pathlib import Path as _Path

import mimetypes as _mimetypes

# Windows 注册表可能把 .js 解析成 text/plain，导致浏览器拒绝加载 ES module；这里强制正确类型
_mimetypes.add_type("application/javascript", ".js")
_mimetypes.add_type("text/css", ".css")
_mimetypes.add_type("image/svg+xml", ".svg")
_mimetypes.add_type("application/wasm", ".wasm")
_mimetypes.add_type("application/json", ".json")

from fastapi.staticfiles import StaticFiles as _StaticFiles
from starlette.responses import FileResponse as _FileResponse


class _SpaStaticFiles(_StaticFiles):
    """SPA 静态服务：找不到文件时回退 index.html（前端路由自己处理）。"""

    async def get_response(self, path, scope):
        from starlette.exceptions import HTTPException as _StarletteHTTP

        try:
            response = await super().get_response(path, scope)
        except _StarletteHTTP:
            response = None
        if response is None or response.status_code == 404:
            index = _Path(self.directory) / "index.html"
            if index.exists():
                return _FileResponse(index)
        return response


_ROOT = _Path(__file__).resolve().parents[1]
_BORROWER_DIST = _ROOT / "frontend" / "dist"
_PORTAL_DIR = _ROOT / "portal"
_ADMIN_DIST = _ROOT / "frontend-admin" / "dist"

if _ADMIN_DIST.exists():
    app.mount("/bank", _SpaStaticFiles(directory=_ADMIN_DIST, html=True), name="bank")
if _BORROWER_DIST.exists():
    app.mount("/app", _SpaStaticFiles(directory=_BORROWER_DIST, html=True), name="borrower")
if _PORTAL_DIR.exists():
    app.mount("/", _StaticFiles(directory=_PORTAL_DIR, html=True), name="portal")
