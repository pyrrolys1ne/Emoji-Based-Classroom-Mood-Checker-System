from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.core.domain import RecordSource, Role
from app.db.models import AppUser, ClassSession, Course, EmojiRecord, ScheduleUser
from app.schemas.contracts import RecordFilters


class FeedbackRepository:
    def __init__(self, session: Session):
        self.session = session

    def manual_request(self, user_id: UUID, key: str) -> EmojiRecord | None:
        return self.session.scalar(select(EmojiRecord).where(
            EmojiRecord.user_id == user_id, EmojiRecord.source == RecordSource.MANUAL,
            EmojiRecord.idempotency_key == key,
        ))

    def assigned(self, session_id: UUID, user_id: UUID) -> bool:
        return bool(self.session.scalar(select(select(ScheduleUser.id).where(
            ScheduleUser.session_id == session_id, ScheduleUser.user_id == user_id,
        ).exists())))

    def owns_history(self, session_id: UUID, user_id: UUID) -> bool:
        return bool(self.session.scalar(select(select(EmojiRecord.id).where(
            EmojiRecord.session_id == session_id, EmojiRecord.user_id == user_id,
            EmojiRecord.source == RecordSource.MANUAL,
        ).exists())))

    def add_manual(self, **values) -> EmojiRecord:
        record = EmojiRecord(source=RecordSource.MANUAL, simulated=False, **values)
        self.session.add(record)
        self.session.flush()
        return record

    def rows(self, role: Role, user_id: UUID, filters: RecordFilters, *, allow_simulated: bool = False, record_id: UUID | None = None):
        teacher = aliased(AppUser, name="record_teacher")
        student = aliased(AppUser, name="record_student")
        # 记录、授权范围与展示摘要在同一快照读取；不依赖当前名单保留历史。
        query = (
            select(EmojiRecord, ClassSession, Course.name, teacher, student)
            .join(ClassSession, ClassSession.id == EmojiRecord.session_id)
            .join(Course, Course.id == ClassSession.course_id)
            .join(teacher, teacher.id == ClassSession.teacher_id)
            .outerjoin(student, student.id == EmojiRecord.user_id)
        )
        if role == Role.STUDENT:
            query = query.where(EmojiRecord.user_id == user_id, EmojiRecord.source == RecordSource.MANUAL)
        elif role == Role.TEACHER:
            query = query.where(ClassSession.teacher_id == user_id)
        if not allow_simulated:
            query = query.where(EmojiRecord.simulated.is_(False))
        if record_id is not None:
            query = query.where(EmojiRecord.id == record_id)
        for value, column in (
            (filters.session_id, EmojiRecord.session_id), (filters.user_id, EmojiRecord.user_id),
            (filters.course, ClassSession.course_id), (filters.class_name, ClassSession.class_name),
        ):
            if value is not None:
                query = query.where(column == value)
        if filters.from_time is not None:
            query = query.where(EmojiRecord.recorded_at >= filters.from_time)
        if filters.to_time is not None:
            query = query.where(EmojiRecord.recorded_at < filters.to_time)
        if filters.source != "ALL":
            query = query.where(EmojiRecord.source == filters.source)
        return self.session.execute(query.order_by(EmojiRecord.recorded_at.desc(), EmojiRecord.id.desc())).all()
