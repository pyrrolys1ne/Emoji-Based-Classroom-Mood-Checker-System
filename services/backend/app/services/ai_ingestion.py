import hashlib
import json
from datetime import datetime, timezone

from app.core.config import get_settings
from app.core.errors import ApiError
from app.db.session import transaction
from app.repositories.ai_ingestion import AIIngestionRepository
from app.repositories.classrooms import ClassroomsRepository
from app.schemas.contracts import AIAccepted, AIFiltered, AIResult
from app.services.record_views import record_response


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def payload_hash(body: AIResult) -> str:
    payload = body.model_dump(mode="json", by_alias=True)
    payload["recordedAt"] = body.recorded_at.astimezone(timezone.utc).isoformat()
    # JSON 将负零规范为零，等值数值与等值时区使用同一摘要。
    payload["confidence"] = body.confidence or 0.0
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def ingest(body: AIResult, key: str) -> AIAccepted | AIFiltered:
    settings = get_settings()
    if body.simulated and not settings.allow_simulated_ai:
        raise ApiError(403, "SIMULATED_AI_DISABLED", "当前环境不允许模拟 AI 入库。")
    request_hash = payload_hash(body)
    with transaction() as session:
        repo = AIIngestionRepository(session)
        repo.lock_key(key)
        receipt = repo.receipt(key)
        created = False
        if receipt is not None:
            if receipt.request_hash != request_hash:
                raise ApiError(409, "IDEMPOTENCY_CONFLICT", "同一幂等键不能上报不同的 AI 结果。")
        else:
            classroom = ClassroomsRepository(session).classroom(body.session_id, lock=True)
            if classroom is None:
                raise ApiError(404, "NOT_FOUND", "课堂不存在。")
            if body.recorded_at > utc_now():
                raise ApiError(422, "INVALID_RECORD_TIME", "采样时间不能晚于服务端当前时间。")
            if not classroom.starts_at <= body.recorded_at < classroom.ends_at:
                raise ApiError(409, "CLASSROOM_NOT_OPEN", "采样时间不在课堂有效时段内。")
            if body.confidence < settings.ai_min_confidence:
                receipt = repo.save_receipt(key, request_hash)
            else:
                record = repo.add_record(
                    **body.model_dump(exclude={"source"}),
                    idempotency_key=key, request_hash=request_hash,
                )
                receipt = repo.save_receipt(key, request_hash, record_id=record.id)
                created = True
        if receipt.record_id is None:
            result = AIFiltered(accepted=False, reason="LOW_CONFIDENCE")
        else:
            result = AIAccepted(accepted=True, created=created, record=record_response(repo.record_row(receipt.record_id)))
    return result
