from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import require_ai, require_user
from app.schemas.contracts import AIResult, EmojiSubmission, Envelope, LoginRequest, PasswordRequest, RegisterRequest, ScheduleRequest
from app.services.business import pending
from app.services.health import readiness

router = APIRouter(prefix="/api")


@router.get("/health", tags=["运行状态"], response_model=Envelope[dict[str, str]])
def health():
    return Envelope(data={"status": "ok", "version": "0.1.0", "stage": "scaffold"})


@router.get("/ready", tags=["运行状态"], response_model=Envelope[dict[str, str]])
def ready():
    if not readiness():
        raise HTTPException(503, "数据库尚未就绪。")
    return Envelope(data={"database": "ready"})


@router.post("/auth/register", tags=["认证"])
def register(body: RegisterRequest):
    return pending("用户注册")


@router.post("/auth/login", tags=["认证"])
def login(body: LoginRequest):
    return pending("用户登录")


protected = APIRouter(dependencies=[Depends(require_user)])


@protected.put("/auth/password", tags=["认证"])
def password(body: PasswordRequest):
    return pending("修改密码")


@protected.get("/users/me", tags=["用户"])
def me():
    return pending("当前用户查询")


@protected.get("/admin/users", tags=["用户"])
def users():
    return pending("管理员用户查询")


@protected.get("/sessions", tags=["课堂"])
def sessions():
    return pending("课堂会话查询")


@protected.post("/admin/sessions/{session_id}/schedule", tags=["课堂"])
def schedule(session_id: UUID, body: ScheduleRequest):
    return pending("课堂用户安排")


@protected.post("/emoji", tags=["情绪"])
def emoji(body: EmojiSubmission):
    return pending("手动情绪提交")


@protected.get("/emoji/history", tags=["情绪"])
def history(session_id: UUID | None = Query(None, alias="sessionId")):
    return pending("情绪历史查询")


@protected.get("/emoji/statistics", tags=["情绪"])
def statistics(session_id: UUID | None = Query(None, alias="sessionId")):
    return pending("情绪基础统计")


@protected.get("/admin/dashboard/realtime", tags=["看板"])
def realtime(session_id: UUID = Query(alias="sessionId")):
    return pending("实时情绪看板")


@protected.get("/admin/statistics", tags=["看板"])
def multidimensional(course: UUID | None = None, class_name: str | None = Query(None, alias="class"), from_time: datetime | None = Query(None, alias="from"), to_time: datetime | None = Query(None, alias="to")):
    return pending("多维统计")


@protected.get("/admin/emoji/export", tags=["导出"])
def export_csv(format: str = Query("csv", pattern="^csv$")):
    return pending("服务端 CSV 导出")


@router.post("/ai/emoji-results", tags=["AI 入库"], dependencies=[Depends(require_ai)])
def ai_results(body: AIResult):
    return pending("AI 结果入库")


router.include_router(protected)
