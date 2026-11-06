from fastapi import APIRouter, Depends

from app.api.accounts import Administrator, no_store
from app.schemas.ai_control import AIConfig, AIStatus, EmptyRequest, ImageRequest, VisionResult, VisionStatus
from app.schemas.contracts import Envelope
from app.services import ai_control

router = APIRouter(dependencies=[Depends(no_store)])


@router.get("/admin/ai/status", tags=["AI 控制"], response_model=Envelope[AIStatus])
def status(principal: Administrator):
    return Envelope(data=ai_control.read(principal))


@router.get("/admin/ai/vision", tags=["AI 控制"], response_model=Envelope[VisionStatus])
def vision(principal: Administrator):
    return Envelope(data=ai_control.read(principal, vision=True))


@router.post("/admin/ai/start", tags=["AI 控制"], response_model=Envelope[AIStatus])
def start(body: AIConfig, principal: Administrator):
    return Envelope(data=ai_control.command(principal, "start", body))


@router.post("/admin/ai/stop", tags=["AI 控制"], response_model=Envelope[AIStatus])
def stop(principal: Administrator, body: EmptyRequest | None = None):
    return Envelope(data=ai_control.command(principal, "stop"))


@router.post("/admin/ai/analyze-image", tags=["AI 控制"], response_model=Envelope[VisionResult])
def analyze_image(body: ImageRequest, principal: Administrator):
    return Envelope(data=ai_control.command(principal, "analyze-image", body))
