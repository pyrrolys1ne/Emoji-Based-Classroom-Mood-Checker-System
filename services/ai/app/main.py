import os
import secrets
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from .runner import Runner
from .vision import VisionError, analyze_sample, vision_status


class ImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    imageId: str = Field(min_length=1, max_length=80)
    allowRemoteUpload: Literal[True]


class Config(BaseModel):
    sessionId: UUID
    mode: Literal["simulation", "camera"] = "simulation"
    sampleIntervalSeconds: float = Field(default=2, ge=0.5, le=60)
    confidenceThreshold: float = Field(default=0.75, ge=0, le=1)
    cameraIndex: int = Field(default=0, ge=0, le=10)


def create_app(outbox_path=None):
    runner = Runner(outbox_path)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        runner.stop()

    app = FastAPI(title="Classroom Mood AI Service", version="0.2.0", lifespan=lifespan)
    app.state.runner = runner

    @app.exception_handler(StarletteHTTPException)
    async def error(_request, exc):
        return JSONResponse(
            {"code": "AI_ERROR", "message": str(exc.detail), "data": None},
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation(_request, _exc):
        return JSONResponse(
            {"code": "VALIDATION_ERROR", "message": "采样参数不符合约束", "data": None},
            status_code=422,
        )

    def control(authorization: str = Header("")):
        token = os.getenv("AI_CONTROL_TOKEN", "")
        if not token or not secrets.compare_digest(authorization, "Bearer " + token):
            raise HTTPException(401, "AI 控制认证失败")

    def status():
        return {"code": "OK", "message": "成功", "data": runner.status()}

    @app.get("/health")
    def health():
        return {
            "code": "OK",
            "message": "成功",
            "data": {
                "status": "ok",
                "version": "0.2.0",
                "modelLoaded": runner.status()["modelLoaded"],
            },
        }

    @app.get("/control/status", dependencies=[Depends(control)])
    def get_status():
        return status()

    @app.post("/control/start", dependencies=[Depends(control)])
    def start(config: Config):
        try:
            runner.start(config.model_dump(mode="json"))
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))
        return status()

    @app.post("/control/stop", dependencies=[Depends(control)])
    def stop():
        runner.stop()
        return status()

    @app.get("/control/vision", dependencies=[Depends(control)])
    def get_vision():
        return {"code": "OK", "message": "成功", "data": vision_status()}

    @app.post("/control/analyze-image", dependencies=[Depends(control)])
    def image(request: ImageRequest):
        try:
            result = analyze_sample(request.imageId)
        except VisionError as exc:
            raise HTTPException(exc.status, str(exc)) from None
        return {"code": "OK", "message": "成功", "data": result}

    return app


app = create_app()
