from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.core.security import require_ai, require_user
from app.schemas.contracts import (
    AIAccepted, AIFiltered, AIResult, AuthSession, ClassSession, EmojiRecord, EmojiSubmission,
    EmotionStatistics, Envelope, ExportFilters, IdempotencyKey, LoginRequest,
    PasswordRequest, RecordFilters, RegisterRequest, ScheduleRequest,
    StatisticsFilters, User,
)
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


@router.post("/auth/register", tags=["认证"], response_model=Envelope[None])
def register(body: RegisterRequest):
    return pending("用户注册")


@router.post("/auth/login", tags=["认证"], response_model=Envelope[AuthSession])
def login(body: LoginRequest):
    return pending("用户登录")


protected = APIRouter(dependencies=[Depends(require_user)])


@protected.put("/auth/password", tags=["认证"])
def password(body: PasswordRequest):
    return pending("修改密码")


@protected.get("/users/me", tags=["用户"], response_model=Envelope[User])
def me():
    return pending("当前用户查询")


@protected.get("/admin/users", tags=["用户"], response_model=Envelope[list[User]])
def users():
    return pending("管理员用户查询")


@protected.get("/sessions", tags=["课堂"], response_model=Envelope[list[ClassSession]])
def sessions():
    return pending("课堂会话查询")


@protected.post("/admin/sessions/{session_id}/schedule", tags=["课堂"])
def schedule(session_id: UUID, body: ScheduleRequest):
    return pending("课堂用户安排")


@protected.post("/emoji", tags=["情绪"], response_model=Envelope[EmojiRecord])
def emoji(body: EmojiSubmission, idempotency_key: Annotated[IdempotencyKey, Header(alias="Idempotency-Key")]):
    return pending("手动情绪提交")


@protected.get("/emoji/history", tags=["情绪"], response_model=Envelope[list[EmojiRecord]])
def history(filters: Annotated[RecordFilters, Query()]):
    return pending("情绪历史查询")


@protected.get("/emoji/statistics", tags=["情绪"], response_model=Envelope[EmotionStatistics])
def statistics(filters: Annotated[StatisticsFilters, Query()]):
    return pending("情绪基础统计")


@protected.get("/admin/dashboard/realtime", tags=["看板"])
def realtime(session_id: UUID = Query(alias="sessionId")):
    return pending("实时情绪看板")


@protected.get("/admin/statistics", tags=["看板"], response_model=Envelope[EmotionStatistics])
def multidimensional(filters: Annotated[StatisticsFilters, Query()]):
    return pending("多维统计")


@protected.get("/admin/emoji/export", tags=["导出"])
def export_csv(filters: Annotated[ExportFilters, Query()]):
    return pending("服务端 CSV 导出")


@router.post("/ai/emoji-results", tags=["AI 入库"], dependencies=[Depends(require_ai)], response_model=Envelope[AIAccepted | AIFiltered])
def ai_results(body: AIResult, idempotency_key: Annotated[IdempotencyKey, Header(alias="Idempotency-Key")]):
    return pending("AI 结果入库")


router.include_router(protected)
