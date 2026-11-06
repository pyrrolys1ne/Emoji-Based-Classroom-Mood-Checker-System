import hashlib
import json
from datetime import datetime, timezone

from app.core.config import get_settings
from app.core.domain import Role
from app.core.errors import ApiError
from app.db.session import transaction
from app.repositories.accounts import AccountsRepository
from app.repositories.classrooms import ClassroomsRepository
from app.repositories.feedback import FeedbackRepository
from app.schemas.contracts import EmojiRecord, EmojiSubmission, RecordFilters
from app.services.accounts import Principal, authorize_actor
from app.services.record_views import record_response
from app.services.record_scope import authorize_records


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def submit(principal: Principal, body: EmojiSubmission, key: str) -> EmojiRecord:
    payload = json.dumps(body.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":"))
    request_hash = hashlib.sha256(payload.encode()).hexdigest()
    with transaction() as session:
        accounts = AccountsRepository(session)
        # 用户锁与退出、改密、角色变更协调，同时串行化该用户的幂等请求。
        actor = authorize_actor(accounts, principal)
        if actor.role != Role.STUDENT:
            raise ApiError(403, "FORBIDDEN", "只有学生可以提交手动反馈。")
        repo = FeedbackRepository(session)
        record = repo.manual_request(actor.id, key)
        if record is not None:
            if record.request_hash != request_hash:
                raise ApiError(409, "IDEMPOTENCY_CONFLICT", "同一幂等键不能提交不同的反馈。")
        else:
            classroom = ClassroomsRepository(session).classroom(body.session_id, lock=True)
            if classroom is None:
                raise ApiError(404, "NOT_FOUND", "课堂不存在。")
            if not repo.assigned(classroom.id, actor.id):
                raise ApiError(403, "FORBIDDEN", "只能向已安排的课堂提交反馈。")
            # 等待用户锁、课堂锁后取实际时间，不能使用请求到达时间或事务开始时间。
            now = utc_now()
            if not classroom.starts_at <= now < classroom.ends_at:
                raise ApiError(409, "CLASSROOM_NOT_OPEN", "请在课堂开始后、结束前提交反馈。")
            record = repo.add_manual(
                user_id=actor.id, session_id=classroom.id, emotion=body.emotion,
                recorded_at=now, idempotency_key=key, request_hash=request_hash,
            )
            accounts.audit("EMOJI_MANUAL_SUBMIT", actor.id, record.id)
        result = record_response(repo.rows(actor.role, actor.id, RecordFilters(), record_id=record.id)[0])
    return result


def history(principal: Principal, filters: RecordFilters) -> list[EmojiRecord]:
    with transaction() as session:
        actor = authorize_records(session, principal, filters)
        repo = FeedbackRepository(session)
        result = [record_response(row) for row in repo.rows(actor.role, actor.id, filters, allow_simulated=get_settings().allow_simulated_ai)]
    return result
