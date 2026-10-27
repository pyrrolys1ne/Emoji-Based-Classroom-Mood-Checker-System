"""本地参考实现：使用合成账号和独立 SQLite 数据，严禁部署为正式后端。"""

import asyncio
import csv
import io
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import httpx
from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from .store import Store

EMOTIONS = {
    "HAPPY",
    "FOCUSED",
    "NEUTRAL",
    "CONFUSED",
    "SAD",
    "ANGRY",
    "SURPRISED",
    "FEAR",
    "DISGUST",
}


def envelope(data=None, message="成功", code="OK"):
    return {"code": code, "message": message, "data": data}


class Login(BaseModel):
    username: str
    password: str


class Schedule(BaseModel):
    userIds: list[UUID] = Field(max_length=500)


class Result(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sessionId: UUID
    emotion: str
    source: Literal["AI"] = "AI"
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    recordedAt: datetime
    deviceId: str = Field(min_length=1, max_length=100)
    simulated: bool = False
    inferenceProvider: Literal["DeepSeek", "DeepFace"] | None = None
    confidenceKind: Literal["self_reported", "model_score"] | None = None

    @model_validator(mode="after")
    def score_metadata(self):
        if (
            self.inferenceProvider == "DeepSeek"
            and self.confidenceKind != "self_reported"
        ):
            raise ValueError("DeepSeek 分数必须标为模型自评分")
        return self

    @field_validator("emotion")
    @classmethod
    def valid_emotion(cls, value):
        if value not in EMOTIONS:
            raise ValueError("不支持的情绪类型")
        return value

    @field_validator("recordedAt")
    @classmethod
    def timezone_required(cls, value):
        if value.utcoffset() is None:
            raise ValueError("时间戳必须含时区")
        return value


class AIConfig(BaseModel):
    sessionId: UUID
    mode: Literal["simulation", "camera", "camera-api"]
    sampleIntervalSeconds: float = Field(ge=0.5, le=60)
    confidenceThreshold: float = Field(ge=0, le=1)
    cameraIndex: int = Field(ge=0, le=10)
    allowRemoteUpload: bool = False
    maxSamples: int = Field(default=5, ge=1, le=60)
    maxDurationSeconds: int = Field(default=120, ge=10, le=600)

    @model_validator(mode="after")
    def remote_camera(self):
        if self.mode == "camera-api" and (
            not self.allowRemoteUpload or self.sampleIntervalSeconds < 5
        ):
            raise ValueError("远程摄像头需要明确允许发送，采样间隔至少 5 秒")
        return self


class ImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    imageId: str = Field(min_length=1, max_length=80)
    allowRemoteUpload: Literal[True]


def create_app(database_path: str | None = None, *, testing=False) -> FastAPI:
    store = Store(
        database_path
        or str(Path(__file__).resolve().parents[3] / ".local" / "integration.sqlite")
    )
    sessions: dict[str, dict] = {}
    tickets: dict[str, tuple[str, dict, float]] = {}
    version = 0

    @asynccontextmanager
    async def lifespan(_app):
        if not testing and os.getenv("MOOD_INTEGRATION") != "1":
            raise RuntimeError(
                "该服务仅用于本地联调，请使用 npm run dev:integration 启动"
            )
        store.initialize()
        yield

    app = FastAPI(title="本地管理端与 AI 联调服务（非正式后端）", lifespan=lifespan)
    bearer = HTTPBearer(auto_error=False)

    @app.exception_handler(StarletteHTTPException)
    async def error(_request, exc):
        return JSONResponse(
            envelope(message=str(exc.detail), code=f"HTTP_{exc.status_code}"),
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, _exc):
        return JSONResponse(
            envelope(message="参数不符合接口契约", code="VALIDATION_ERROR"),
            status_code=422,
        )

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if (
            not testing
            and request.client
            and request.client.host not in {"127.0.0.1", "::1"}
        ):
            return JSONResponse(
                envelope(message="联调服务仅允许本机访问", code="FORBIDDEN"),
                status_code=403,
            )
        return await call_next(request)

    def current(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        item = sessions.get(credentials.credentials if credentials else "")
        if item is None or item["expires"] < datetime.now(timezone.utc).timestamp():
            raise HTTPException(401, "请登录本地联调账号")
        return item["user"]

    def admin(user=Depends(current)):
        if user["role"] != "ADMIN":
            raise HTTPException(403, "该操作仅限管理员")
        return user

    def visible(user):
        return store.sessions(None if user["role"] == "ADMIN" else user["id"])

    def allowed(user, session_id=None):
        items = visible(user)
        if session_id and session_id not in {item["id"] for item in items}:
            raise HTTPException(403, "无权访问该课堂")
        return items

    @app.get("/api/health")
    def health():
        return envelope({"status": "ok", "stage": "integration", "production": False})

    @app.post("/api/auth/login")
    def login(body: Login):
        # 只包含合成账号，不读取正式用户密码，不提供公开注册或管理员提权。
        if body.username not in {"admin", "teacher"} or not secrets.compare_digest(
            body.password.encode(), b"integration-only"
        ):
            raise HTTPException(401, "联调账号或密码不正确")
        user = next(user for user in store.users() if user["username"] == body.username)
        token = secrets.token_urlsafe(32)
        sessions[token] = {
            "user": user,
            "expires": datetime.now(timezone.utc).timestamp() + 8 * 3600,
        }
        return envelope({"token": token, "user": user})

    @app.post("/api/auth/logout")
    def logout(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if credentials:
            sessions.pop(credentials.credentials, None)
        return envelope()

    @app.get("/api/users/me")
    def me(user=Depends(current)):
        return envelope(user)

    @app.get("/api/admin/users")
    def users(_user=Depends(admin)):
        return envelope(store.users())

    @app.get("/api/sessions")
    def classrooms(user=Depends(current)):
        return envelope(visible(user))

    @app.post("/api/admin/sessions/{session_id}/schedule")
    def schedule(session_id: UUID, body: Schedule, user=Depends(admin)):
        allowed(user, str(session_id))
        student_ids = {
            item["id"]
            for item in store.users()
            if item["role"] == "STUDENT" and item["status"] == "ACTIVE"
        }
        if not {str(item) for item in body.userIds} <= student_ids:
            raise HTTPException(422, "只能安排有效学生")
        store.schedule(str(session_id), [str(item) for item in body.userIds])
        return envelope()

    @app.get("/api/emoji/history")
    def history(sessionId: UUID | None = None, user=Depends(current)):
        items = allowed(user, str(sessionId) if sessionId else None)
        ids = {str(sessionId)} if sessionId else {item["id"] for item in items}
        return envelope(store.records(ids))

    @app.get("/api/admin/dashboard/realtime")
    def realtime(sessionId: UUID | None = None, user=Depends(current)):
        rows = history(sessionId, user)["data"]
        return envelope(
            {
                "records": rows,
                "total": len(rows),
                "version": version,
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

    @app.get("/api/admin/statistics")
    def statistics(
        course: str | None = None,
        class_name: str | None = Query(None, alias="class"),
        from_time: datetime | None = Query(None, alias="from"),
        to_time: datetime | None = Query(None, alias="to"),
        user=Depends(current),
    ):
        if any(
            value is not None and value.utcoffset() is None
            for value in (from_time, to_time)
        ):
            raise HTTPException(422, "时间范围必须包含时区")
        if from_time and to_time and from_time >= to_time:
            raise HTTPException(422, "结束时间必须晚于开始时间")
        ids = {
            item["id"]
            for item in visible(user)
            if (not course or item["courseId"] == course)
            and (not class_name or item["className"] == class_name)
        }
        rows = [
            row
            for row in store.records(ids)
            if (not from_time or datetime.fromisoformat(row["recordedAt"]) >= from_time)
            and (not to_time or datetime.fromisoformat(row["recordedAt"]) < to_time)
        ]
        return envelope(
            {
                "total": len(rows),
                "distribution": {
                    emotion: sum(row["emotion"] == emotion for row in rows)
                    for emotion in sorted(EMOTIONS)
                },
            }
        )

    @app.get("/api/admin/emoji/export")
    def export(format: Literal["csv"] = "csv", user=Depends(admin)):
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "记录编号",
                "课堂编号",
                "情绪",
                "来源",
                "模型分数",
                "时间",
                "设备",
                "模拟输入",
                "推理提供方",
                "分数类型",
            ]
        )
        for row in store.records({item["id"] for item in visible(user)}):
            values = [
                row.get(key, "")
                for key in (
                    "id",
                    "sessionId",
                    "emotion",
                    "source",
                    "confidence",
                    "recordedAt",
                    "deviceId",
                    "simulated",
                    "inferenceProvider",
                    "confidenceKind",
                )
            ]
            writer.writerow(
                [
                    "'" + str(value)
                    if str(value).lstrip().startswith(("=", "+", "-", "@"))
                    or str(value).startswith(("\t", "\r", "\n"))
                    else value
                    for value in values
                ]
            )
        return Response(
            "\ufeff" + output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=mood-records.csv"},
        )

    @app.post("/api/ai/emoji-results")
    def ingest(
        body: Result,
        authorization: str = Header(""),
        idempotency_key: str = Header(
            ..., alias="Idempotency-Key", min_length=1, max_length=100
        ),
    ):
        nonlocal version
        token = os.getenv("MOOD_AI_SERVICE_TOKEN", "")
        if not token or not secrets.compare_digest(authorization, f"Bearer {token}"):
            raise HTTPException(401, "AI 服务认证失败")
        if str(body.sessionId) not in {item["id"] for item in store.sessions()}:
            raise HTTPException(404, "课堂不存在")
        if body.confidence < float(os.getenv("MOOD_AI_MIN_CONFIDENCE", "0.5")):
            return envelope({"accepted": False, "reason": "LOW_CONFIDENCE"})
        record = {**body.model_dump(mode="json"), "id": str(uuid4()), "userId": None}
        try:
            result, created = store.insert(record, idempotency_key)
        except ValueError:
            raise HTTPException(409, "幂等键已绑定其他结果")
        if created:
            version += 1
        return envelope({"accepted": True, "created": created, "record": result})

    @app.post("/api/auth/ws-ticket")
    def ws_ticket(
        user=Depends(current),
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ):
        # 一次性短票据，避免把可复用访问令牌放进 WebSocket URL。
        ticket = secrets.token_urlsafe(24)
        now = datetime.now(timezone.utc).timestamp()
        for key in list(tickets):
            if tickets[key][2] <= now:
                tickets.pop(key)
        tickets[ticket] = (credentials.credentials, user, now + 30)
        return envelope({"ticket": ticket})

    @app.websocket("/ws/dashboard")
    async def ws(websocket: WebSocket):
        if (
            not testing
            and websocket.client
            and websocket.client.host not in {"127.0.0.1", "::1"}
        ):
            await websocket.close(code=1008)
            return
        ticket = tickets.pop(websocket.query_params.get("ticket", ""), None)
        if (
            ticket is None
            or ticket[2] <= datetime.now(timezone.utc).timestamp()
            or ticket[0] not in sessions
        ):
            await websocket.close(code=1008)
            return
        origin = websocket.headers.get("origin")
        if origin and origin not in {
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:5175",
            "http://localhost:5175",
        }:
            await websocket.close(code=1008)
            return
        user = ticket[1]
        await websocket.accept()
        try:
            while True:
                if (
                    ticket[0] not in sessions
                    or sessions[ticket[0]]["expires"]
                    <= datetime.now(timezone.utc).timestamp()
                ):
                    await websocket.close(code=1008)
                    return
                rows = store.records({item["id"] for item in visible(user)})
                await websocket.send_json(
                    {
                        "type": "snapshot",
                        "total": len(rows),
                        "latestId": rows[0]["id"] if rows else None,
                    }
                )
                await asyncio.sleep(1)
        except (WebSocketDisconnect, RuntimeError):
            pass

    async def ai_proxy(method: str, path: str, body=None, *, timeout=8):
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.request(
                    method,
                    os.getenv("AI_CONTROL_URL", "http://127.0.0.1:8001") + path,
                    headers={
                        "Authorization": "Bearer " + os.getenv("AI_CONTROL_TOKEN", "")
                    },
                    json=body,
                )
                result = response.json()
                if response.is_error:
                    raise HTTPException(
                        response.status_code, result.get("message", "AI 服务请求失败")
                    )
                return result
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, "AI 服务不可用，请检查进程及连接")

    @app.get("/api/admin/ai/status")
    async def ai_status(_user=Depends(admin)):
        return await ai_proxy("GET", "/control/status")

    @app.post("/api/admin/ai/start")
    async def ai_start(config: AIConfig, user=Depends(admin)):
        allowed(user, str(config.sessionId))
        return await ai_proxy("POST", "/control/start", config.model_dump(mode="json"))

    @app.post("/api/admin/ai/stop")
    async def ai_stop(_user=Depends(admin)):
        return await ai_proxy("POST", "/control/stop")

    @app.get("/api/admin/ai/vision")
    async def ai_vision(_user=Depends(admin)):
        return await ai_proxy("GET", "/control/vision")

    @app.post("/api/admin/ai/analyze-image")
    async def ai_image(body: ImageRequest, _user=Depends(admin)):
        return await ai_proxy(
            "POST", "/control/analyze-image", body.model_dump(), timeout=40
        )

    app.state.store = store
    return app


app = create_app()
