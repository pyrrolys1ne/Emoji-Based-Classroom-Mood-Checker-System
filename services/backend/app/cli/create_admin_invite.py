"""由部署环境操作者生成管理员注册邀请码，不通过命令参数接收凭据。"""

import sys

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.cli.common import SafeArgumentParser
from app.db.session import close_database
from app.schemas.contracts import AdminInvitationRequest
from app.services.accounts import issue_admin_invitation


def main(argv: list[str] | None = None) -> int:
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("--expires-in-hours", type=int, default=24)
    args = parser.parse_args(argv)
    try:
        invitation = issue_admin_invitation(AdminInvitationRequest(expires_in_hours=args.expires_in_hours))
        print("管理员一次性邀请码：" + invitation.code)
        print("过期时间：" + invitation.expires_at.isoformat())
        return 0
    except ValidationError:
        print("生成失败：有效期应为 1—168 小时。", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("生成失败：请检查数据库连接、迁移和权限。", file=sys.stderr)
        return 1
    finally:
        close_database()


if __name__ == "__main__":
    raise SystemExit(main())
