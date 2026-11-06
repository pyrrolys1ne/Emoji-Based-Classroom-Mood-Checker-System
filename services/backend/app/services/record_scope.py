from sqlalchemy.orm import Session

from app.core.domain import Role
from app.core.errors import ApiError
from app.repositories.accounts import AccountsRepository
from app.repositories.classrooms import ClassroomsRepository
from app.repositories.feedback import FeedbackRepository
from app.schemas.contracts import RecordFilters
from app.services.accounts import Principal, authorize_actor


def authorize_records(session: Session, principal: Principal, filters: RecordFilters, *, aggregate=False, admin=False):
    actor = authorize_actor(AccountsRepository(session), principal, admin=admin)
    if aggregate and actor.role not in (Role.TEACHER, Role.ADMIN):
        raise ApiError(403, "FORBIDDEN", "统计仅限教师和管理员。")
    if actor.role == Role.STUDENT and (filters.user_id not in (None, actor.id) or filters.source == "AI"):
        raise ApiError(403, "FORBIDDEN", "学生只能查询本人的手动反馈。")
    if filters.session_id is not None:
        classroom = ClassroomsRepository(session).classroom(filters.session_id)
        if classroom is None:
            raise ApiError(404, "NOT_FOUND", "课堂不存在。")
        repo = FeedbackRepository(session)
        if (actor.role == Role.TEACHER and classroom.teacher_id != actor.id) or (
            actor.role == Role.STUDENT and not repo.assigned(classroom.id, actor.id)
            and not repo.owns_history(classroom.id, actor.id)
        ):
            raise ApiError(403, "FORBIDDEN", "无权查询该课堂记录。")
    return actor
