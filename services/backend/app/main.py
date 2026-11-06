from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
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
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan, description="账号、教师审批、课程课堂、学生安排、手动反馈与授权历史已实现；统计、实时看板及 AI 入库业务仍返回 501。")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False, allow_methods=["GET", "POST", "PUT"], allow_headers=["Authorization", "Content-Type", "Idempotency-Key"])
install_error_handlers(app)
app.include_router(router)


@app.websocket("/ws/dashboard")
async def dashboard_socket(websocket: WebSocket):
    # 实时推送与鉴权尚未实现，不接受未认证连接。
    await websocket.close(code=1008, reason="实时看板鉴权和推送待实现")
