from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.domain import Role
from app.db.models import AuditLog, ClassSession, Course, EmojiRecord
from app.repositories.feedback import FeedbackRepository
from app.repositories.record_scope import record_predicates
from app.schemas.contracts import StatisticsFilters


class StatisticsRepository:
    def __init__(self, session: Session):
        self.session = session

    def counts(self, role: Role, user_id: UUID, filters: StatisticsFilters, *, allow_simulated: bool, multidimensional=False):
        minute = func.date_trunc("minute", EmojiRecord.recorded_at, "UTC").label("minute")
        dimensions = [EmojiRecord.emotion]
        if multidimensional:
            dimensions.extend((minute, ClassSession.course_id, Course.name, ClassSession.class_name, EmojiRecord.source))
        query = (
            select(*dimensions, func.count()).select_from(EmojiRecord)
            .join(ClassSession, ClassSession.id == EmojiRecord.session_id)
            .join(Course, Course.id == ClassSession.course_id)
            .where(*record_predicates(role, user_id, filters, allow_simulated=allow_simulated))
            .group_by(*dimensions)
        )
        return self.session.execute(query).all()

    def export_rows(self, role: Role, user_id: UUID, filters: StatisticsFilters, *, allow_simulated: bool):
        return FeedbackRepository(self.session).rows(role, user_id, filters, allow_simulated=allow_simulated)

    def audit_export(self, actor_id: UUID, session_id: UUID | None):
        self.session.add(AuditLog(actor_id=actor_id, action="EMOJI_CSV_EXPORT", target_id=session_id))
