from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.accounts import Administrator, CurrentUser, no_store
from app.schemas.contracts import (
    ClassSession, Course, CourseRequest, Envelope, ScheduleRequest,
    SessionRequest, StudentProfileRequest, User,
)
from app.services import classrooms

router = APIRouter(dependencies=[Depends(no_store)])


@router.get("/sessions", tags=["课堂"], response_model=Envelope[list[ClassSession]])
def sessions(principal: CurrentUser):
    return Envelope(data=classrooms.sessions(principal))


@router.get("/admin/courses", tags=["课程管理"], response_model=Envelope[list[Course]])
def courses(principal: Administrator):
    return Envelope(data=classrooms.courses(principal))


@router.post("/admin/courses", tags=["课程管理"], response_model=Envelope[Course])
def create_course(body: CourseRequest, principal: Administrator):
    return Envelope(data=classrooms.save_course(principal, body))


@router.put("/admin/courses/{course_id}", tags=["课程管理"], response_model=Envelope[Course])
def update_course(course_id: UUID, body: CourseRequest, principal: Administrator):
    return Envelope(data=classrooms.save_course(principal, body, course_id))


@router.post("/admin/sessions", tags=["课堂管理"], response_model=Envelope[ClassSession])
def create_session(body: SessionRequest, principal: Administrator):
    return Envelope(data=classrooms.save_session(principal, body))


@router.put("/admin/sessions/{session_id}", tags=["课堂管理"], response_model=Envelope[ClassSession])
def update_session(session_id: UUID, body: SessionRequest, principal: Administrator):
    return Envelope(data=classrooms.save_session(principal, body, session_id))


@router.post("/admin/sessions/{session_id}/schedule", tags=["课堂管理"], response_model=Envelope[None])
def schedule(session_id: UUID, body: ScheduleRequest, principal: Administrator):
    classrooms.schedule(principal, session_id, body)
    return Envelope(data=None)


@router.put("/admin/users/{user_id}/student-profile", tags=["学生资料"], response_model=Envelope[User])
def student_profile(user_id: UUID, body: StudentProfileRequest, principal: Administrator):
    return Envelope(data=classrooms.student_profile(principal, user_id, body))
