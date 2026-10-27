from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.core.errors import install_error_handlers

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", description="项目框架。健康检查可用；业务接口显式返回 501，认证与 RBAC 待实现。")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False, allow_methods=["GET", "POST", "PUT"], allow_headers=["Authorization", "Content-Type"])
install_error_handlers(app)
app.include_router(router)


@app.websocket("/ws/dashboard")
async def dashboard_socket(websocket: WebSocket):
    # 实时推送与鉴权尚未实现，不接受未认证连接。
    await websocket.close(code=1008, reason="实时看板鉴权和推送待实现")
