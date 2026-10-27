from secrets import compare_digest

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

user_bearer = HTTPBearer(auto_error=False, scheme_name="UserBearer")
ai_bearer = HTTPBearer(auto_error=False, scheme_name="AIServiceBearer")


def require_user(credentials: HTTPAuthorizationCredentials | None = Depends(user_bearer)):
    if credentials is None:
        raise HTTPException(401, "请先登录。", headers={"WWW-Authenticate": "Bearer"})
    # 真实 JWT 校验和 RBAC 尚未实现。禁止将任意非空令牌当成合法身份。
    raise HTTPException(501, "身份认证与 RBAC 待实现，当前不开放受保护业务。")


def require_ai(credentials: HTTPAuthorizationCredentials | None = Depends(ai_bearer)) -> None:
    expected = get_settings().ai_service_token
    if not expected:
        raise HTTPException(503, "尚未配置 AI 服务令牌。")
    if credentials is None or not compare_digest(credentials.credentials, expected):
        raise HTTPException(401, "AI 服务令牌无效。", headers={"WWW-Authenticate": "Bearer"})
