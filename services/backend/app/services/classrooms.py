from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.domain import Role, TeacherApprovalStatus, UserStatus
from app.core.errors import ApiError
from app.db.models import AppUser, ClassSession as SessionModel, Course as CourseModel
from app.db.session import transaction
from app.repositories.accounts import AccountsRepository
from app.repositories.classrooms import ClassroomsRepository
from app.schemas.contracts import (
    ClassSession, ClassroomSeedRequest, ClassroomSeedResult, ClassroomStudent,
    Course, CourseRequest, LoginRequest, ScheduleRequest, SessionRequest,
    StudentProfileRequest, User,
)
from app.services.accounts import (
    Principal, account_conflict, authorize_actor, is_account_approved,
    user_response, verify_account_login,
)


def _teacher(user: AppUser | None, approval: str | None) -> AppUser:
    if user is None or user.role != Role.TEACHER or user.status != UserStatus.ACTIVE or approval != TeacherApprovalStatus.APPROVED:
        raise ApiError(422, "INVALID_TEACHER", "任课教师必须是已获准且启用的教师账号。")
    return user


def _student(user: AppUser | None, approval: str | None, *, active: bool = True) -> AppUser:
    if user is None or user.role != Role.STUDENT or not is_account_approved(user, approval) or (active and user.status != UserStatus.ACTIVE):
        raise ApiError(422, "INVALID_STUDENT", "只能使用符合要求的学生账号。")
    return user


def _course_response(course: CourseModel) -> Course:
    return Course(id=course.id, name=course.name, teacher_id=course.teacher_id)


def _session_responses(rows) -> list[ClassSession]:
    sessions: dict[UUID, ClassSession] = {}
    for classroom, course_name, teacher, student in rows:
        if classroom.id not in sessions:
            sessions[classroom.id] = ClassSession(
                id=classroom.id, course_id=classroom.course_id, course_name=course_name,
                teacher_id=classroom.teacher_id, teacher_name=teacher.real_name or teacher.username,
                class_name=classroom.class_name, room=classroom.room,
                starts_at=classroom.starts_at, ends_at=classroom.ends_at, scheduled_user_ids=[],
            )
        if student is not None:
            result = sessions[classroom.id]
            result.scheduled_user_ids.append(student.id)
            result.scheduled_students.append(ClassroomStudent(
                id=student.id, username=student.username, student_no=student.student_no,
                real_name=student.real_name, class_name=student.class_name, status=student.status,
            ))
    return list(sessions.values())


def sessions(principal: Principal) -> list[ClassSession]:
    with transaction() as session:
        actor = authorize_actor(AccountsRepository(session), principal)
        result = _session_responses(ClassroomsRepository(session).session_rows(actor.role, actor.id))
    return result


def courses(principal: Principal) -> list[Course]:
    with transaction() as session:
        authorize_actor(AccountsRepository(session), principal, admin=True)
        result = [_course_response(course) for course in ClassroomsRepository(session).courses()]
    return result


def save_course(principal: Principal, body: CourseRequest, course_id: UUID | None = None) -> Course:
    with transaction() as session:
        accounts = AccountsRepository(session)
        repo = ClassroomsRepository(session)
        locked = accounts.lock_users([principal.user.id, body.teacher_id])
        actor = authorize_actor(accounts, principal, users=locked, admin=True)
        application = accounts.application_for(body.teacher_id)
        _teacher(locked.get(body.teacher_id), application.status if application else None)
        if course_id is None:
            course = repo.add_course(name=body.name, teacher_id=body.teacher_id)
        else:
            course = repo.course(course_id, lock=True)
            if course is None:
                raise ApiError(404, "NOT_FOUND", "课程不存在。")
            course.name, course.teacher_id = body.name, body.teacher_id
        accounts.audit("COURSE_CREATE" if course_id is None else "COURSE_UPDATE", actor.id, course.id)
        session.flush()
        result = _course_response(course)
    return result


def _freeze_history(classroom: SessionModel, body: SessionRequest, teacher_id: UUID, repo: ClassroomsRepository) -> None:
    scope_changed = (
        classroom.course_id != body.course_id or classroom.teacher_id != teacher_id
        or classroom.starts_at != body.starts_at or classroom.ends_at != body.ends_at
    )
    if scope_changed and (classroom.starts_at <= datetime.now(timezone.utc) or repo.has_records(classroom.id)):
        raise ApiError(409, "CLASSROOM_LOCKED", "课堂已开始或已有记录，不能更改课程、任课人及起止时间。")


def save_session(principal: Principal, body: SessionRequest, session_id: UUID | None = None) -> ClassSession:
    with transaction() as session:
        accounts = AccountsRepository(session)
        repo = ClassroomsRepository(session)
        original = repo.classroom(session_id) if session_id else None
        course = repo.course(body.course_id)
        if course is None or (session_id is not None and original is None):
            raise ApiError(404, "NOT_FOUND", "课程或课堂不存在。")
        teacher_id = body.teacher_id or (original.teacher_id if original else course.teacher_id)
        locked = accounts.lock_users([principal.user.id, teacher_id])
        actor = authorize_actor(accounts, principal, users=locked, admin=True)
        application = accounts.application_for(teacher_id)
        _teacher(locked.get(teacher_id), application.status if application else None)
        course = repo.course(body.course_id, lock=True)
        if course is None:
            raise ApiError(404, "NOT_FOUND", "课程不存在。")
        if session_id is None:
            if body.teacher_id is None and course.teacher_id != teacher_id:
                raise ApiError(409, "CONFLICT", "课程默认教师已变化，请重新提交。")
            classroom = repo.add_classroom(
                course_id=course.id, teacher_id=teacher_id, starts_at=body.starts_at,
                ends_at=body.ends_at, room=body.room, class_name=body.class_name,
            )
        else:
            classroom = repo.classroom(session_id, lock=True)
            if classroom is None:
                raise ApiError(404, "NOT_FOUND", "课堂不存在。")
            if body.teacher_id is None and classroom.teacher_id != teacher_id:
                raise ApiError(409, "CONFLICT", "课堂任课教师已变化，请重新提交。")
            _freeze_history(classroom, body, teacher_id, repo)
            classroom.course_id, classroom.teacher_id = course.id, teacher_id
            classroom.starts_at, classroom.ends_at = body.starts_at, body.ends_at
            classroom.room, classroom.class_name = body.room, body.class_name
        accounts.audit("CLASS_SESSION_CREATE" if session_id is None else "CLASS_SESSION_UPDATE", actor.id, classroom.id)
        session.flush()
        result = _session_responses(repo.session_rows(Role.ADMIN, actor.id, classroom.id))[0]
    return result


def schedule(principal: Principal, session_id: UUID, body: ScheduleRequest) -> None:
    ids = sorted(set(body.user_ids))
    with transaction() as session:
        accounts = AccountsRepository(session)
        repo = ClassroomsRepository(session)
        locked = accounts.lock_users([principal.user.id, *ids])
        actor = authorize_actor(accounts, principal, users=locked, admin=True)
        approvals = accounts.approval_statuses(ids)
        for user_id in ids:
            _student(locked.get(user_id), approvals.get(user_id))
        if repo.classroom(session_id, lock=True) is None:
            raise ApiError(404, "NOT_FOUND", "课堂不存在。")
        repo.replace_schedule(session_id, ids)
        accounts.audit("CLASS_SCHEDULE_REPLACE", actor.id, session_id)


def student_profile(principal: Principal, user_id: UUID, body: StudentProfileRequest) -> User:
    try:
        with transaction() as session:
            repo = AccountsRepository(session)
            locked = repo.lock_users([principal.user.id, user_id])
            actor = authorize_actor(repo, principal, users=locked, admin=True)
            if user_id not in locked:
                raise ApiError(404, "NOT_FOUND", "学生不存在。")
            application = repo.application_for(user_id)
            approval = application.status if application else None
            user = _student(locked[user_id], approval, active=False)
            for field, value in body.model_dump(exclude_unset=True).items():
                setattr(user, field, value)
            repo.audit("STUDENT_PROFILE_UPDATE", actor.id, user.id)
            session.flush()
            result = user_response(user, approval)
    except IntegrityError as error:
        account_conflict(error)
    return result


def import_classrooms(credentials: LoginRequest, body: ClassroomSeedRequest) -> ClassroomSeedResult:
    try:
        with transaction() as session:
            accounts = AccountsRepository(session)
            repo = ClassroomsRepository(session)
            names = {credentials.username, *(course.teacher_username for course in body.courses)}
            for item in body.sessions:
                names.update(item.student_usernames)
                if item.teacher_username:
                    names.add(item.teacher_username)
            by_name = {user.username: user for user in accounts.find_users(names)}
            locked = accounts.lock_users([user.id for user in by_name.values()])
            actor = by_name.get(credentials.username)
            actor = locked.get(actor.id) if actor else None
            actor, _ = verify_account_login(accounts, actor, credentials.password)
            if actor.role != Role.ADMIN:
                raise ApiError(403, "FORBIDDEN", "初始化课程与课堂需要管理员身份。")
            if set(by_name) != names:
                raise ApiError(422, "INVALID_IMPORT", "导入引用的账号不存在。")
            approvals = accounts.approval_statuses(list(locked))
            course_teachers = {}
            for item in body.courses:
                user = locked[by_name[item.teacher_username].id]
                course_teachers[item.key] = _teacher(user, approvals.get(user.id))
            for item in body.sessions:
                if item.teacher_username:
                    user = locked[by_name[item.teacher_username].id]
                    _teacher(user, approvals.get(user.id))
                for username in item.student_usernames:
                    user = locked[by_name[username].id]
                    _student(user, approvals.get(user.id))
            repo.begin_import(body.import_id, actor.id)
            courses_by_key = {}
            for item in body.courses:
                course = repo.add_course(name=item.name, teacher_id=course_teachers[item.key].id)
                courses_by_key[item.key] = course
                accounts.audit("COURSE_CREATE", actor.id, course.id)
            session_ids = []
            for item in body.sessions:
                teacher_id = by_name[item.teacher_username].id if item.teacher_username else course_teachers[item.course_key].id
                classroom = repo.add_classroom(
                    course_id=courses_by_key[item.course_key].id, teacher_id=teacher_id,
                    starts_at=item.starts_at, ends_at=item.ends_at, room=item.room, class_name=item.class_name,
                )
                ids = sorted({by_name[name].id for name in item.student_usernames})
                repo.replace_schedule(classroom.id, ids)
                session_ids.append(classroom.id)
                accounts.audit("CLASS_SESSION_CREATE", actor.id, classroom.id)
                accounts.audit("CLASS_SCHEDULE_REPLACE", actor.id, classroom.id)
            accounts.audit("CLASSROOM_IMPORT", actor.id, body.import_id)
            result = ClassroomSeedResult(import_id=body.import_id, course_ids=[course.id for course in courses_by_key.values()], session_ids=session_ids)
    except IntegrityError as error:
        if getattr(getattr(error.orig, "diag", None), "constraint_name", None) == "classroom_import_pkey":
            raise ApiError(409, "IMPORT_ALREADY_EXISTS", "该初始化批次已提交，不能重复导入。") from None
        raise
    return result
