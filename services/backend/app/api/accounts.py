from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.core.security import require_admin, require_user
from app.schemas.contracts import (
    AuthSession, Envelope, LoginRequest, PasswordRequest, RegisterRequest,
    TeacherApplication, TeacherReviewRequest, User,
)
from app.services import accounts
from app.services.accounts import Principal


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(dependencies=[Depends(no_store)])
CurrentUser = Annotated[Principal, Depends(require_user)]
Administrator = Annotated[Principal, Depends(require_admin)]


@router.post("/auth/register", tags=["认证"], response_model=Envelope[None])
def register(body: RegisterRequest):
    accounts.register(body)
    return Envelope(data=None)


@router.post("/auth/login", tags=["认证"], response_model=Envelope[AuthSession])
def login(body: LoginRequest):
    return Envelope(data=accounts.login(body))


@router.post("/auth/logout", tags=["认证"], response_model=Envelope[None])
def logout(principal: CurrentUser):
    accounts.logout(principal)
    return Envelope(data=None)


@router.put("/auth/password", tags=["认证"], response_model=Envelope[None])
def password(body: PasswordRequest, principal: CurrentUser):
    accounts.change_password(principal, body)
    return Envelope(data=None)


@router.get("/users/me", tags=["用户"], response_model=Envelope[User])
def me(principal: CurrentUser):
    return Envelope(data=principal.user)


@router.get("/admin/users", tags=["用户"], response_model=Envelope[list[User]])
def users(principal: Administrator):
    return Envelope(data=accounts.users(principal))


@router.get("/admin/teacher-applications", tags=["教师审批"], response_model=Envelope[list[TeacherApplication]])
def applications(principal: Administrator):
    return Envelope(data=accounts.applications(principal))


@router.put("/admin/teacher-applications/{application_id}", tags=["教师审批"], response_model=Envelope[TeacherApplication])
def review(application_id: UUID, body: TeacherReviewRequest, principal: Administrator):
    return Envelope(data=accounts.review(principal, application_id, body))
