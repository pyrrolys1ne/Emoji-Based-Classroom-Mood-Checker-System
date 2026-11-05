from secrets import compare_digest

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.core.domain import Role
from app.core.errors import ApiError
from app.services.accounts import Principal, authenticate

user_bearer = HTTPBearer(auto_error=False, scheme_name="UserBearer")
ai_bearer = HTTPBearer(auto_error=False, scheme_name="AIServiceBearer")


def require_user(credentials: HTTPAuthorizationCredentials | None = Depends(user_bearer)) -> Principal:
    if credentials is None:
        raise HTTPException(401, "请先登录。", headers={"WWW-Authenticate": "Bearer"})
    return authenticate(credentials.credentials)


def require_admin(principal: Principal = Depends(require_user)) -> Principal:
    if principal.user.role != Role.ADMIN:
        raise ApiError(403, "FORBIDDEN", "该操作仅限管理员。")
    return principal


def require_teacher_or_admin(principal: Principal = Depends(require_user)) -> Principal:
    if principal.user.role not in {Role.TEACHER, Role.ADMIN}:
        raise ApiError(403, "FORBIDDEN", "该操作仅限任课教师或管理员。")
    return principal


def require_student(principal: Principal = Depends(require_user)) -> Principal:
    if principal.user.role != Role.STUDENT:
        raise ApiError(403, "FORBIDDEN", "只有学生可以提交手动反馈。")
    return principal


def require_ai(credentials: HTTPAuthorizationCredentials | None = Depends(ai_bearer)) -> None:
    expected = get_settings().ai_service_token.get_secret_value()
    if not expected:
        raise HTTPException(503, "尚未配置 AI 服务令牌。")
    if credentials is None or not compare_digest(credentials.credentials.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(401, "AI 服务令牌无效。", headers={"WWW-Authenticate": "Bearer"})
