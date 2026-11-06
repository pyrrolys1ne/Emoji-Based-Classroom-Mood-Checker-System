from fastapi import APIRouter, HTTPException

from app.api.accounts import router as accounts_router
from app.api.ai_control import router as ai_control_router
from app.api.ai_ingestion import router as ai_ingestion_router
from app.api.classrooms import router as classrooms_router
from app.api.feedback import router as feedback_router
from app.api.statistics import router as statistics_router
from app.api.realtime import router as realtime_router
from app.schemas.contracts import Envelope
from app.services.health import readiness

router = APIRouter(prefix="/api")


@router.get("/health", tags=["运行状态"], response_model=Envelope[dict[str, str]])
def health():
    return Envelope(data={"status": "ok", "version": "0.1.0", "stage": "realtime-ai-control"})


@router.get("/ready", tags=["运行状态"], response_model=Envelope[dict[str, str]])
def ready():
    if not readiness():
        raise HTTPException(503, "数据库尚未就绪。")
    return Envelope(data={"database": "ready"})


router.include_router(accounts_router)
router.include_router(classrooms_router)
router.include_router(feedback_router)
router.include_router(ai_ingestion_router)
router.include_router(statistics_router)
router.include_router(realtime_router)
router.include_router(ai_control_router)
