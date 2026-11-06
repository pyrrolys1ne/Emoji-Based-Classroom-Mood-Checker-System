from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.api.accounts import router as accounts_router
from app.api.classrooms import router as classrooms_router
from app.api.feedback import router as feedback_router
from app.core.security import require_admin, require_ai, require_teacher_or_admin, require_user
from app.schemas.contracts import (
    AIAccepted, AIFiltered, AIResult,
    EmotionStatistics, Envelope, ExportFilters, IdempotencyKey,
    StatisticsFilters,
)
from app.services.business import pending
from app.services.health import readiness

router = APIRouter(prefix="/api")


@router.get("/health", tags=["运行状态"], response_model=Envelope[dict[str, str]])
def health():
    return Envelope(data={"status": "ok", "version": "0.1.0", "stage": "feedback"})


@router.get("/ready", tags=["运行状态"], response_model=Envelope[dict[str, str]])
def ready():
    if not readiness():
        raise HTTPException(503, "数据库尚未就绪。")
    return Envelope(data={"database": "ready"})


protected = APIRouter(dependencies=[Depends(require_user)])


@protected.get("/emoji/statistics", tags=["情绪"], response_model=Envelope[EmotionStatistics], dependencies=[Depends(require_teacher_or_admin)])
def statistics(filters: Annotated[StatisticsFilters, Query()]):
    return pending("情绪基础统计")


@protected.get("/admin/dashboard/realtime", tags=["看板"], dependencies=[Depends(require_teacher_or_admin)])
def realtime(session_id: UUID = Query(alias="sessionId")):
    return pending("实时情绪看板")


@protected.get("/admin/statistics", tags=["看板"], response_model=Envelope[EmotionStatistics], dependencies=[Depends(require_teacher_or_admin)])
def multidimensional(filters: Annotated[StatisticsFilters, Query()]):
    return pending("多维统计")


@protected.get("/admin/emoji/export", tags=["导出"], dependencies=[Depends(require_admin)])
def export_csv(filters: Annotated[ExportFilters, Query()]):
    return pending("服务端 CSV 导出")


@router.post("/ai/emoji-results", tags=["AI 入库"], dependencies=[Depends(require_ai)], response_model=Envelope[AIAccepted | AIFiltered])
def ai_results(body: AIResult, idempotency_key: Annotated[IdempotencyKey, Header(alias="Idempotency-Key")]):
    return pending("AI 结果入库")


router.include_router(protected)
router.include_router(accounts_router)
router.include_router(classrooms_router)
router.include_router(feedback_router)
