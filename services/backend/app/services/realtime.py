import hashlib
import json
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from uuid import UUID

from app.core.config import get_settings
from app.core.domain import Role
from app.core.errors import ApiError
from app.db.session import transaction
from app.repositories.accounts import AccountsRepository
from app.repositories.feedback import FeedbackRepository
from app.repositories.realtime import RealtimeRepository
from app.schemas.contracts import RealtimeDashboard, RealtimeSnapshot, RecordFilters, WsTicketResponse
from app.services.accounts import Principal, authorize_actor, token_digest, user_response
from app.services.record_scope import authorize_records
from app.services.record_views import record_response


def utc_now():
    return datetime.now(timezone.utc)


def _viewer(actor):
    if actor.role not in (Role.ADMIN, Role.TEACHER):
        raise ApiError(403, "FORBIDDEN", "实时看板仅限教师和管理员。")


def issue_ticket(principal: Principal) -> WsTicketResponse:
    with transaction() as session:
        accounts = AccountsRepository(session)
        actor = authorize_actor(accounts, principal)
        _viewer(actor)
        identity = accounts.identity(principal.session_id, actor.id)
        now = utc_now()
        expires = min(identity.expires_at, now + timedelta(seconds=get_settings().ws_ticket_ttl_seconds))
        if expires <= now:
            raise ApiError(401, "UNAUTHENTICATED", "登录已失效。")
        ticket = "wst_" + token_urlsafe(32)
        RealtimeRepository(session).add_ticket(identity.id, token_digest(ticket), now, expires)
        result = WsTicketResponse(ticket=ticket, expires_at=expires)
    return result


def consume_ticket(ticket: str) -> Principal:
    with transaction() as session:
        repo = RealtimeRepository(session)
        owner = repo.ticket_owner(token_digest(ticket))
        if owner is None:
            raise ApiError(401, "UNAUTHENTICATED", "实时票据无效。")
        session_id, user_id = owner
        accounts = AccountsRepository(session)
        users = accounts.lock_users([user_id])
        user = users.get(user_id)
        if user is None:
            raise ApiError(401, "UNAUTHENTICATED", "实时票据无效。")
        application = accounts.application_for(user_id)
        principal = Principal(user_response(user, application.status if application else None), session_id)
        actor = authorize_actor(accounts, principal, users=users)
        _viewer(actor)
        record = repo.ticket(token_digest(ticket))
        now = utc_now()
        if record is None or record.consumed_at is not None or record.expires_at <= now:
            raise ApiError(401, "UNAUTHENTICATED", "实时票据已失效。")
        record.consumed_at = now
    return principal


def snapshot(principal: Principal, session_id: UUID | None = None) -> RealtimeSnapshot:
    with transaction() as session:
        actor = authorize_records(session, principal, RecordFilters(session_id=session_id), aggregate=True)
        if actor.role != principal.user.role:
            raise ApiError(403, "FORBIDDEN", "身份角色已变化，请重新建立连接。")
        total, latest_id, versions = RealtimeRepository(session).snapshot(actor.role, actor.id, session_id,
            allow_simulated=get_settings().allow_simulated_ai)
        revision = hashlib.sha256(json.dumps(sorted(versions or []), separators=(",", ":")).encode()).hexdigest()
        result = RealtimeSnapshot(total=total, latest_id=latest_id, version=revision)
    return result


def dashboard(principal: Principal, filters: RecordFilters) -> RealtimeDashboard:
    with transaction() as session:
        actor = authorize_records(session, principal, filters, aggregate=True)
        records = [record_response(row) for row in FeedbackRepository(session).rows(actor.role, actor.id, filters,
            allow_simulated=get_settings().allow_simulated_ai)]
        result = RealtimeDashboard(records=records, total=len(records), latest_id=records[0].id if records else None, updated_at=utc_now())
    return result
