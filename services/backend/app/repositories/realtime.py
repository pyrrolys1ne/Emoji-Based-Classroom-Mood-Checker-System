from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.domain import Role
from app.db.models import ClassSession, EmojiRecord, UserSession, WsTicket


class RealtimeRepository:
    def __init__(self, session: Session):
        self.session = session

    def add_ticket(self, session_id: UUID, token_hash: str, created_at: datetime, expires_at: datetime):
        self.session.add(WsTicket(session_id=session_id, token_hash=token_hash, created_at=created_at, expires_at=expires_at))

    def ticket_owner(self, token_hash: str):
        return self.session.execute(select(UserSession.id, UserSession.user_id)
            .join(WsTicket, WsTicket.session_id == UserSession.id).where(WsTicket.token_hash == token_hash)).one_or_none()

    def ticket(self, token_hash: str):
        return self.session.scalar(select(WsTicket).where(WsTicket.token_hash == token_hash)
            .with_for_update().execution_options(populate_existing=True))

    def snapshot(self, role: Role, user_id: UUID, session_id: UUID | None, *, allow_simulated: bool):
        visible = select(ClassSession.id, ClassSession.revision)
        if role == Role.TEACHER:
            visible = visible.where(ClassSession.teacher_id == user_id)
        if session_id is not None:
            visible = visible.where(ClassSession.id == session_id)
        classrooms = visible.cte("visible_classrooms")
        records = select(EmojiRecord.id, EmojiRecord.recorded_at).join(classrooms, classrooms.c.id == EmojiRecord.session_id)
        if not allow_simulated:
            records = records.where(EmojiRecord.simulated.is_(False))
        records = records.cte("visible_records")
        # 计数、最新记录和课堂版本来自同一数据库快照，不广播其他课堂信息。
        return self.session.execute(select(
            select(func.count()).select_from(records).scalar_subquery(),
            select(records.c.id).order_by(records.c.recorded_at.desc(), records.c.id.desc()).limit(1).scalar_subquery(),
            select(func.jsonb_agg(func.jsonb_build_array(classrooms.c.id, classrooms.c.revision))).select_from(classrooms).scalar_subquery(),
        )).one()
