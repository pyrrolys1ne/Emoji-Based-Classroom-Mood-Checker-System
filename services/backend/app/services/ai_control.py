import json
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.errors import ApiError
from app.db.session import transaction
from app.repositories.accounts import AccountsRepository
from app.repositories.ai_control import AIControlRepository
from app.repositories.classrooms import ClassroomsRepository
from app.schemas.ai_control import AIConfig, AIStatus, ImageRequest, VisionResult, VisionStatus
from app.services.accounts import Principal, authorize_actor


def control_client(timeout: float):
    return httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False)


def _contains_secret(value, secrets):
    if isinstance(value, str):
        return any(secret and secret in value for secret in secrets)
    if isinstance(value, dict):
        return any(_contains_secret(item, secrets) for item in value.values())
    if isinstance(value, list):
        return any(_contains_secret(item, secrets) for item in value)
    return False


def _request(method: str, path: str, response_model, body=None, *, timeout=8):
    settings = get_settings()
    token = settings.ai_control_token.get_secret_value()
    if not token:
        raise ApiError(503, "AI_UNAVAILABLE", "未配置 AI 控制服务。")
    try:
        with control_client(timeout) as client:
            with client.stream(method, settings.ai_base_url + path, json=body,
                headers={"Authorization": "Bearer " + token}) as response:
                if response.status_code != 200:
                    status, code, message = {
                        401: (502, "AI_UPSTREAM_AUTH", "AI 控制服务认证失败，请核对服务端配置。"),
                        403: (502, "AI_UPSTREAM_AUTH", "AI 控制服务拒绝访问。"),
                        404: (404, "AI_SAMPLE_NOT_FOUND", "AI 测试样本或服务接口不存在。"),
                        409: (409, "AI_BUSY", "AI 任务已在运行、正在停止或配置尚未就绪，请核对状态。"),
                        422: (422, "AI_CONFIGURATION_REJECTED", "AI 服务拒绝当前参数。"),
                        429: (429, "AI_RATE_LIMITED", "AI 服务请求限流，请稍后手动重试。"),
                    }.get(response.status_code, (502, "AI_UPSTREAM_ERROR", "AI 控制服务请求失败。"))
                    raise ApiError(status, code, message)
                if response.headers.get("content-type", "").split(";")[0].strip() != "application/json":
                    raise ValueError("响应类型无效")
                chunks, length = [], 0
                for chunk in response.iter_bytes():
                    length += len(chunk)
                    if length > 1024 * 1024:
                        raise ValueError("响应超出结构化结果限制")
                    chunks.append(chunk)
                data = json.loads(b"".join(chunks))
                if not isinstance(data, dict) or data.get("code") != "OK":
                    raise ValueError("响应包装无效")
                result = response_model.model_validate(data.get("data"))
                public = result.model_dump(mode="json", by_alias=True)
                if _contains_secret(public, (token, settings.ai_service_token.get_secret_value())):
                    raise ValueError("响应包含服务端凭据")
                return result
    except httpx.TimeoutException:
        raise ApiError(504, "AI_TIMEOUT", "AI 服务响应超时，操作结果可能未知，请核对状态后决定是否重试。") from None
    except httpx.HTTPError:
        raise ApiError(503, "AI_UNAVAILABLE", "AI 服务暂时不可用，请核对进程及服务端连接。") from None
    except (ValueError, ValidationError):
        raise ApiError(502, "AI_INVALID_RESPONSE", "AI 服务返回的结构化结果无效。") from None


def _authorize(session, principal):
    return authorize_actor(AccountsRepository(session), principal, admin=True)


def _start_scope(session, config: AIConfig):
    classroom = ClassroomsRepository(session).classroom(config.session_id)
    if classroom is None:
        raise ApiError(404, "NOT_FOUND", "课堂不存在。")
    if not classroom.starts_at <= datetime.now(timezone.utc) < classroom.ends_at:
        raise ApiError(409, "CLASSROOM_NOT_OPEN", "请在课堂有效时段内启动采样。")
    if config.mode == "simulation" and not get_settings().allow_simulated_ai:
        raise ApiError(403, "SIMULATED_AI_DISABLED", "当前环境不允许模拟采样。")


def read(principal: Principal, *, vision=False):
    with transaction() as session:
        _authorize(session, principal)
    result = _request("GET", "/control/vision" if vision else "/control/status", VisionStatus if vision else AIStatus)
    with transaction() as session:
        _authorize(session, principal)
    return result


def command(principal: Principal, action: str, body: AIConfig | ImageRequest | None = None):
    actions = {"start": "AI_START", "stop": "AI_STOP", "analyze-image": "AI_IMAGE_ANALYZE"}
    event = actions[action]
    operation_id = uuid4()
    # 请求意图先提交；外部设备操作不能与本地事务一起回滚。
    with transaction() as session:
        actor = _authorize(session, principal)
        if action == "start":
            _start_scope(session, body)
        if not get_settings().ai_control_token.get_secret_value():
            raise ApiError(503, "AI_UNAVAILABLE", "未配置 AI 控制服务。")
        AIControlRepository(session).audit(event + "_REQUEST", actor.id, operation_id)
    dispatched = False
    try:
        with transaction() as session:
            repo = AIControlRepository(session)
            repo.lock_control()
            actor = _authorize(session, principal)
            if action == "start":
                _start_scope(session, body)
            if action == "analyze-image":
                vision = _request("GET", "/control/vision", VisionStatus)
                sample = next((sample for sample in vision.samples if sample.id == body.image_id), None)
                if sample is None or not sample.available:
                    raise ApiError(404, "AI_SAMPLE_NOT_FOUND", "公开测试样本不存在或尚未准备。")
                if not vision.configured:
                    raise ApiError(503, "AI_UNAVAILABLE", "图片分析服务尚未配置。")
            dispatched = True
            result = _request("POST", "/control/" + action, VisionResult if action == "analyze-image" else AIStatus,
                body.model_dump(mode="json", by_alias=True) if body else None, timeout=40 if action == "analyze-image" else 8)
            if action == "analyze-image" and result.image_id != body.image_id:
                raise ApiError(502, "AI_INVALID_RESPONSE", "图片回执与请求样本不一致。")
            if action == "start" and (result.session_id != body.session_id or result.config != body):
                raise ApiError(502, "AI_INVALID_RESPONSE", "AI 启动回执与请求配置不一致。")
            repo.audit(event + "_SUCCESS", actor.id, operation_id)
        return result
    except Exception as error:
        # 失败后的意图记录仍在；网络中断或无效回执须标为未知，不自动重试。
        rejected = isinstance(error, ApiError) and error.code in (
            "AI_UPSTREAM_AUTH", "AI_BUSY", "AI_CONFIGURATION_REJECTED", "AI_RATE_LIMITED", "AI_SAMPLE_NOT_FOUND")
        unknown = dispatched and not rejected and (not isinstance(error, ApiError) or error.status_code in (502, 503, 504))
        outcome = "_UNKNOWN" if unknown else "_REJECTED"
        try:
            with transaction() as session:
                AIControlRepository(session).audit(event + outcome, principal.user.id, operation_id)
        except Exception:
            if dispatched:
                raise ApiError(503, "AI_OPERATION_UNCONFIRMED", "AI 操作可能已经执行且审计确认失败，请核实后再决定是否重试。") from None
            raise
        if unknown and not isinstance(error, ApiError):
            raise ApiError(500, "AI_OPERATION_UNCONFIRMED", "AI 操作可能已经执行但尚未确认，请核实后再决定是否重试。") from None
        if unknown and error.code != "AI_TIMEOUT":
            raise ApiError(error.status_code, error.code, str(error.detail) + " 操作可能已经执行，请核实后再决定是否重试。") from None
        raise
