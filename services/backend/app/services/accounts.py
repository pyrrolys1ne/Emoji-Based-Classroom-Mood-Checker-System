import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.domain import Role, TeacherApprovalStatus, UserStatus
from app.core.errors import ApiError
from app.core.passwords import hash_password, needs_rehash, verify_password
from app.db.models import AppUser, TeacherApplication, UserSession
from app.db.session import transaction
from app.repositories.accounts import AccountsRepository
from app.schemas.contracts import (
    AdminBootstrapRequest, AdminInvitationRequest, AdminInvitationResponse, AdminRegistrationRequest,
    AuthSession, LoginRequest, PasswordRequest,
    RegisterRequest, TeacherApplication as ApplicationResponse, TeacherReviewRequest, User,
)

USER_TOKEN = re.compile(r"usr_[A-Za-z0-9_-]{43}")


@dataclass(frozen=True)
class Principal:
    user: User
    session_id: UUID


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def invalid_identity() -> ApiError:
    return ApiError(401, "UNAUTHENTICATED", "登录已失效，请重新登录。")


def is_account_approved(user: AppUser, approval: str | None) -> bool:
    if approval is not None and approval != TeacherApprovalStatus.APPROVED:
        return False
    return user.role != Role.TEACHER or approval == TeacherApprovalStatus.APPROVED


def user_response(user: AppUser, approval: str | None) -> User:
    return User(
        id=user.id, username=user.username, email=user.email,
        role=user.role, status=user.status, student_no=user.student_no,
        real_name=user.real_name, class_name=user.class_name,
        teacher_approval_status=approval,
    )


def _application_response(application: TeacherApplication) -> ApplicationResponse:
    return ApplicationResponse(
        id=application.id, user_id=application.user_id, status=application.status,
        submitted_at=application.submitted_at, reviewed_at=application.reviewed_at,
        reviewed_by=application.reviewed_by, reason=application.reason,
    )


def _active(identity: UserSession | None, now: datetime) -> bool:
    return identity is not None and identity.revoked_at is None and identity.expires_at > now


def authorize_actor(repo: AccountsRepository, principal: Principal, *, users=None, admin=False) -> AppUser:
    # 与登录、改密、退出共用用户行锁；写入前再次校验实时身份。
    users = users if users is not None else repo.lock_users([principal.user.id])
    user = users.get(principal.user.id)
    identity = repo.identity(principal.session_id, principal.user.id)
    application = repo.application_for(principal.user.id)
    approval = application.status if application else None
    if user is None or user.status != UserStatus.ACTIVE or not _active(identity, datetime.now(timezone.utc)) or not is_account_approved(user, approval):
        raise invalid_identity()
    if admin and user.role != Role.ADMIN:
        raise ApiError(403, "FORBIDDEN", "该操作仅限管理员。")
    return user


def account_conflict(error: IntegrityError) -> None:
    if getattr(error.orig, "sqlstate", None) != "23505":
        raise error
    constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if constraint == "app_user_student_no_key":
        raise ApiError(409, "STUDENT_NO_EXISTS", "学号已被使用。") from None
    if constraint in {"app_user_username_key", "app_user_email_key"}:
        raise ApiError(409, "ACCOUNT_EXISTS", "用户名或邮箱已被使用。") from None
    raise error


def register(body: RegisterRequest) -> None:
    password_hash = hash_password(body.password)
    try:
        with transaction() as session:
            repo = AccountsRepository(session)
            user = repo.add_user(
                username=body.username, email=str(body.email), password_hash=password_hash,
                role=Role.STUDENT, status=UserStatus.ACTIVE, student_no=body.student_no,
                real_name=body.real_name, class_name=body.class_name,
            )
            repo.audit("AUTH_REGISTER", user.id, user.id)
            if body.role == "TEACHER":
                repo.add_application(user.id)
                repo.audit("TEACHER_APPLICATION_SUBMIT", user.id, user.id)
    except IntegrityError as error:
        account_conflict(error)


def login(body: LoginRequest) -> AuthSession:
    with transaction() as session:
        repo = AccountsRepository(session)
        user = repo.find_user(body.username, lock=True)
        user, approval = verify_account_login(repo, user, body.password)
        now = datetime.now(timezone.utc)
        token = "usr_" + token_urlsafe(32)
        repo.add_identity(
            user_id=user.id, token_hash=token_digest(token), created_at=now,
            expires_at=now + timedelta(seconds=get_settings().user_session_ttl_seconds),
        )
        repo.audit("AUTH_LOGIN", user.id, user.id)
        result = AuthSession(token=token, user=user_response(user, approval))
    return result


def issue_admin_invitation(body: AdminInvitationRequest, principal: Principal | None = None) -> AdminInvitationResponse:
    code = "adm_" + token_urlsafe(32)
    with transaction() as session:
        repo = AccountsRepository(session)
        actor = authorize_actor(repo, principal, admin=True) if principal is not None else None
        now = datetime.now(timezone.utc)
        invitation = repo.add_invitation(token_hash=token_digest(code), created_at=now,
            expires_at=now + timedelta(hours=body.expires_in_hours), created_by=actor.id if actor else None)
        repo.audit("ADMIN_INVITATION_CREATE", actor.id if actor else None, invitation.id)
        result = AdminInvitationResponse(code=code, expires_at=invitation.expires_at)
    return result


def register_admin(body: AdminRegistrationRequest) -> None:
    try:
        with transaction() as session:
            repo = AccountsRepository(session)
            invitation = repo.invitation(token_digest(body.invitation_code))
            now = datetime.now(timezone.utc)
            if invitation is None or invitation.used_at is not None or invitation.expires_at <= now:
                raise ApiError(403, "INVALID_ADMIN_INVITATION", "邀请码无效、已使用或已过期，请联系管理员。")
            user = repo.add_user(username=body.username, email=str(body.email), password_hash=hash_password(body.password),
                role=Role.ADMIN, status=UserStatus.ACTIVE, real_name=body.real_name)
            invitation.used_at = now
            invitation.used_by = user.id
            repo.audit("ADMIN_REGISTER", user.id, user.id)
            repo.audit("ADMIN_INVITATION_USE", user.id, invitation.id)
    except IntegrityError as error:
        account_conflict(error)


def verify_account_login(repo: AccountsRepository, user: AppUser | None, password: str) -> tuple[AppUser, str | None]:
    """调用方持有用户行锁，在当前事务验证凭据和账号状态。"""
    if not verify_password(password, user.password_hash if user else None):
        raise ApiError(401, "UNAUTHENTICATED", "账号或密码错误。")
    if user.status != UserStatus.ACTIVE:
        raise ApiError(403, "ACCOUNT_DISABLED", "账号已禁用，请联系管理员。")
    application = repo.application_for(user.id)
    approval = application.status if application else None
    if not is_account_approved(user, approval):
        raise ApiError(403, "TEACHER_APPROVAL_REQUIRED", "教师申请尚未获准，请联系管理员。")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user, approval


def authenticate(token: str) -> Principal:
    if not USER_TOKEN.fullmatch(token):
        raise invalid_identity()
    with transaction() as session:
        row = AccountsRepository(session).identity_by_hash(token_digest(token))
        if row is None:
            raise invalid_identity()
        identity, user, approval = row
        if not _active(identity, datetime.now(timezone.utc)) or user.status != UserStatus.ACTIVE or not is_account_approved(user, approval):
            raise invalid_identity()
        result = Principal(user_response(user, approval), identity.id)
    return result


def logout(principal: Principal) -> None:
    with transaction() as session:
        repo = AccountsRepository(session)
        user = authorize_actor(repo, principal)
        repo.revoke(user.id, datetime.now(timezone.utc), session_id=principal.session_id)
        repo.audit("AUTH_LOGOUT", user.id, user.id)


def change_password(principal: Principal, body: PasswordRequest) -> None:
    with transaction() as session:
        repo = AccountsRepository(session)
        user = authorize_actor(repo, principal)
        if not verify_password(body.old_password, user.password_hash):
            raise ApiError(403, "INVALID_PASSWORD", "原密码错误。")
        user.password_hash = hash_password(body.new_password)
        repo.revoke(user.id, datetime.now(timezone.utc))
        repo.audit("AUTH_PASSWORD_CHANGE", user.id, user.id)


def users(principal: Principal) -> list[User]:
    with transaction() as session:
        repo = AccountsRepository(session)
        authorize_actor(repo, principal, admin=True)
        result = [user_response(user, approval) for user, approval in repo.users()]
    return result


def applications(principal: Principal) -> list[ApplicationResponse]:
    with transaction() as session:
        repo = AccountsRepository(session)
        authorize_actor(repo, principal, admin=True)
        result = [_application_response(item) for item in repo.applications()]
    return result


def review(principal: Principal, application_id: UUID, body: TeacherReviewRequest) -> ApplicationResponse:
    with transaction() as session:
        repo = AccountsRepository(session)
        application = repo.application(application_id)
        if application is None:
            raise ApiError(404, "NOT_FOUND", "教师申请不存在。")
        # 固定用户锁顺序，再获取申请锁，避免审核、登录与改密互相死锁。
        locked = repo.lock_users([principal.user.id, application.user_id])
        actor = authorize_actor(repo, principal, users=locked, admin=True)
        application = repo.application(application_id, lock=True)
        if application is None:
            raise ApiError(404, "NOT_FOUND", "教师申请不存在。")
        applicant = locked[application.user_id]
        if application.status != TeacherApprovalStatus.PENDING or applicant.role != Role.STUDENT or applicant.status != UserStatus.ACTIVE:
            raise ApiError(409, "CONFLICT", "申请已处理或账号状态不允许审核。")
        now = datetime.now(timezone.utc)
        application.status = body.decision
        application.reviewed_at = now
        application.reviewed_by = actor.id
        application.reason = body.reason
        if body.decision == "APPROVED":
            applicant.role = Role.TEACHER
        repo.revoke(applicant.id, now)
        action = "TEACHER_APPLICATION_APPROVE" if body.decision == "APPROVED" else "TEACHER_APPLICATION_REJECT"
        repo.audit(action, actor.id, application.id)
        session.flush()
        result = _application_response(application)
    return result


def bootstrap_admin(body: AdminBootstrapRequest) -> User:
    password_hash = hash_password(body.password)
    try:
        with transaction() as session:
            repo = AccountsRepository(session)
            repo.lock_bootstrap()
            if repo.has_admin():
                raise ApiError(409, "ADMIN_ALREADY_EXISTS", "已存在管理员，不能重复初始化。")
            user = repo.add_user(username=body.username, email=str(body.email), password_hash=password_hash, role=Role.ADMIN, status=UserStatus.ACTIVE, real_name=body.real_name)
            repo.audit("ADMIN_BOOTSTRAP", user.id, user.id)
            result = user_response(user, None)
    except IntegrityError as error:
        account_conflict(error)
    return result
