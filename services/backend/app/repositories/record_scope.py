from uuid import UUID

from app.core.domain import RecordSource, Role
from app.db.models import ClassSession, EmojiRecord
from app.schemas.contracts import RecordFilters


def record_predicates(role: Role, user_id: UUID, filters: RecordFilters, *, allow_simulated: bool):
    predicates = []
    if role == Role.STUDENT:
        predicates.extend((EmojiRecord.user_id == user_id, EmojiRecord.source == RecordSource.MANUAL))
    elif role == Role.TEACHER:
        predicates.append(ClassSession.teacher_id == user_id)
    if not allow_simulated:
        predicates.append(EmojiRecord.simulated.is_(False))
    for value, column in (
        (filters.session_id, EmojiRecord.session_id), (filters.user_id, EmojiRecord.user_id),
        (filters.course, ClassSession.course_id), (filters.class_name, ClassSession.class_name),
        (filters.emotion, EmojiRecord.emotion),
    ):
        if value is not None:
            predicates.append(column == value)
    if filters.from_time is not None:
        predicates.append(EmojiRecord.recorded_at >= filters.from_time)
    if filters.to_time is not None:
        predicates.append(EmojiRecord.recorded_at < filters.to_time)
    if filters.source != "ALL":
        predicates.append(EmojiRecord.source == filters.source)
    return predicates
