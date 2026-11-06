import json
import sys
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.cli.common import InputError, SafeArgumentParser, read_password
from app.core.errors import ApiError
from app.db.session import close_database
from app.schemas.contracts import ClassroomSeedRequest, LoginRequest
from app.services.classrooms import import_classrooms

MAX_FILE_BYTES = 1024 * 1024


def main(argv: list[str] | None = None) -> int:
    parser = SafeArgumentParser(description="验证管理员身份并原子导入课程、课堂和学生安排。")
    parser.add_argument("--username", required=True)
    parser.add_argument("--file", required=True)
    parser.add_argument("--password-stdin", action="store_true", help="从标准输入读取管理员密码")
    args = parser.parse_args(argv)
    try:
        with Path(args.file).open("rb") as source:
            content = source.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            raise InputError("导入文件不能超过 1 MiB。")
        body = ClassroomSeedRequest.model_validate(json.loads(content.decode("utf-8-sig")))
        credentials = LoginRequest(username=args.username, password=read_password(args.password_stdin))
        result = import_classrooms(credentials, body)
        print(f"导入完成，批次：{result.import_id}，课程：{len(result.course_ids)}，课堂：{len(result.session_ids)}")
        return 0
    except ApiError as error:
        print(f"课堂导入失败：{error.code}，{error.detail}", file=sys.stderr)
        return 1
    except (OSError, UnicodeError, ValidationError, json.JSONDecodeError):
        print("课堂导入失败：文件、账号或配置不符合要求。", file=sys.stderr)
        return 1
    except InputError as error:
        print(f"课堂导入失败：{error}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("课堂导入失败：请检查数据库连接、迁移、权限及数据约束。", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("课堂导入失败：密码输入未完成。", file=sys.stderr)
        return 1
    finally:
        close_database()


if __name__ == "__main__":
    raise SystemExit(main())
