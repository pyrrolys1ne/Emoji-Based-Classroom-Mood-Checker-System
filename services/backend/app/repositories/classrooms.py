from uuid import UUID

from sqlalchemy import and_, delete, select
from sqlalchemy.orm import Session, aliased

from app.core.domain import Role
from app.db.models import AppUser, ClassSession, ClassroomImport, Course, EmojiRecord, ScheduleUser


class ClassroomsRepository:
    def __init__(self, session: Session):
        self.session = session

    def course(self, course_id: UUID, *, lock: bool = False) -> Course | None:
        query = select(Course).where(Course.id == course_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def courses(self) -> list[Course]:
        return list(self.session.scalars(select(Course).order_by(Course.name, Course.id)).all())

    def classroom(self, session_id: UUID, *, lock: bool = False) -> ClassSession | None:
        query = select(ClassSession).where(ClassSession.id == session_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def session_rows(self, role: Role, user_id: UUID, session_id: UUID | None = None):
        teacher = aliased(AppUser, name="session_teacher")
        student = aliased(AppUser, name="scheduled_student")
        roster = ScheduleUser.session_id == ClassSession.id
        if role == Role.STUDENT:
            roster = and_(roster, ScheduleUser.user_id == user_id)
        # 课堂范围与名单在同一 SQL 快照读取，避免多次查询间安排变化导致越界。
        query = (
            select(ClassSession, Course.name, teacher, student).select_from(ClassSession)
            .join(Course, Course.id == ClassSession.course_id)
            .join(teacher, teacher.id == ClassSession.teacher_id)
            .outerjoin(ScheduleUser, roster)
            .outerjoin(student, student.id == ScheduleUser.user_id)
        )
        if role == Role.TEACHER:
            query = query.where(ClassSession.teacher_id == user_id)
        elif role == Role.STUDENT:
            assigned = (
                select(ScheduleUser.id).where(
                    ScheduleUser.session_id == ClassSession.id, ScheduleUser.user_id == user_id,
                ).correlate(ClassSession).exists()
            )
            query = query.where(assigned)
        if session_id is not None:
            query = query.where(ClassSession.id == session_id)
        return self.session.execute(query.order_by(ClassSession.starts_at, ClassSession.id, student.id)).all()

    def add_course(self, **values) -> Course:
        course = Course(**values)
        self.session.add(course)
        self.session.flush()
        return course

    def add_classroom(self, **values) -> ClassSession:
        classroom = ClassSession(**values)
        self.session.add(classroom)
        self.session.flush()
        return classroom

    def replace_schedule(self, session_id: UUID, user_ids: list[UUID]) -> None:
        self.session.execute(delete(ScheduleUser).where(ScheduleUser.session_id == session_id))
        self.session.add_all(ScheduleUser(session_id=session_id, user_id=user_id) for user_id in user_ids)
        self.session.flush()

    def has_records(self, session_id: UUID) -> bool:
        return bool(self.session.scalar(select(
            select(EmojiRecord.id).where(EmojiRecord.session_id == session_id).exists()
        )))

    def begin_import(self, import_id: UUID, actor_id: UUID) -> None:
        self.session.add(ClassroomImport(id=import_id, actor_id=actor_id))
        self.session.flush()
