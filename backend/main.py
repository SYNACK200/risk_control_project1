"""后端入口：启动时自动建库建表，挂载任务/报告/模板接口。"""
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from db.session import init_db
from helpers.logging_config import configure_logging
from routers import audit, entities, reports, tasks, templates, thresholds

logger = logging.getLogger("risk_control")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    init_db()
    logger.info("服务启动；数据库已就绪（缺表自动创建）。")
    try:
        yield
    finally:
        logger.info("服务已停止。")


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

