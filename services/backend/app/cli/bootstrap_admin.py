import argparse
import getpass
import sys

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import ApiError
from app.db.session import close_database
from app.schemas.contracts import AdminBootstrapRequest
from app.services.accounts import bootstrap_admin


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, "命令参数无效，请使用 --help 查看用法。\n")


class InputError(ValueError):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = SafeArgumentParser(description="受控初始化首个管理员，不提升已有账号权限。")
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--real-name")
    parser.add_argument("--password-stdin", action="store_true", help="从标准输入读取单行密码，用于自动化环境")
    args = parser.parse_args(argv)
    try:
        if args.password_stdin:
            password = sys.stdin.read(1025).removesuffix("\n").removesuffix("\r")
            if "\n" in password or "\r" in password:
                raise InputError("标准输入必须只包含一行密码。")
        else:
            if not sys.stdin.isatty():
                raise InputError("交互输入需要终端；自动化环境请显式使用 --password-stdin。")
            password = getpass.getpass("管理员密码：")
            confirmation = getpass.getpass("再次输入密码：")
            if password != confirmation:
                raise InputError("两次密码输入不一致。")
        body = AdminBootstrapRequest(username=args.username, email=args.email, password=password, real_name=args.real_name)
        user = bootstrap_admin(body)
        print(f"管理员初始化完成，用户编号：{user.id}")
        return 0
    except ApiError as error:
        print(f"管理员初始化失败：{error.detail}", file=sys.stderr)
        return 1
    except ValidationError:
        print("管理员初始化失败：配置或账号资料不符合要求，密码长度须为 8—128 字符。", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("管理员初始化失败：请检查数据库连接、迁移及权限。", file=sys.stderr)
        return 1
    except InputError as error:
        print(f"管理员初始化失败：{error}", file=sys.stderr)
        return 1
    except (ValueError, EOFError, KeyboardInterrupt):
        print("管理员初始化失败：密码输入未完成或格式无效。", file=sys.stderr)
        return 1
    finally:
        close_database()


if __name__ == "__main__":
    raise SystemExit(main())
