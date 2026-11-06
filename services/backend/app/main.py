from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.realtime import socket_router
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.db.session import close_database


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        yield
    finally:
        close_database()

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan, description="账号、教师审批、课程课堂、学生安排、手动反馈、授权历史与匿名 AI 入库、全量统计与 CSV 导出已实现；实时看板与 AI 控制代理提供受保护接口。")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False, allow_methods=["GET", "POST", "PUT"], allow_headers=["Authorization", "Content-Type", "Idempotency-Key"])
install_error_handlers(app)
app.include_router(router)

app.include_router(socket_router)
