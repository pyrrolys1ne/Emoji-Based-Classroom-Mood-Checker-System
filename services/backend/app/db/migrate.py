"""按版本执行 PostgreSQL SQL 迁移，兼容尚无版本表的既有初始化库。"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db.session import close_database, get_engine

LOCK_ID = 742031164


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    sql: str
    checksum: str


def load_migrations(directory: Path) -> list[Migration]:
    migrations = []
    for path in sorted(directory.glob("*.sql")):
        match = re.fullmatch(r"(\d{3})_[a-z0-9_]+\.sql", path.name)
        if not match:
            raise MigrationError("迁移文件必须使用三位连续编号与小写名称")
        # Windows 与 Linux 的换行及 UTF-8 BOM 不应改变同一迁移的校验和。
        sql = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        migrations.append(Migration(
            match[1], path.name, sql,
            hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        ))
    versions = [item.version for item in migrations]
    if not migrations or versions != [f"{i:03}" for i in range(1, len(migrations) + 1)]:
        raise MigrationError("迁移目录为空或版本编号不连续")
    return migrations


def _record_migration(connection: Connection, migration: Migration) -> None:
    connection.execute(
        text("INSERT INTO schema_migration(version, name, checksum) VALUES (:version, :name, :checksum)"),
        {"version": migration.version, "name": migration.name, "checksum": migration.checksum},
    )


def _signature(connection: Connection, schema: str) -> dict:
    """比较旧库的列、枚举、约束和索引；不读取或修改业务数据。"""
    inspector = inspect(connection)

    def normalize(value):
        return str(value).replace(f'"{schema}".', "").replace(f"{schema}.", "")

    tables = {}
    for name in inspector.get_table_names(schema=schema):
        if name == "schema_migration":
            continue
        tables[name] = {
            "columns": sorted((col["name"], normalize(col["type"].compile(dialect=connection.dialect)), col["nullable"], normalize(col["default"])) for col in inspector.get_columns(name, schema)),
            "pk": inspector.get_pk_constraint(name, schema)["constrained_columns"],
            "foreign_keys": sorted((tuple(fk["constrained_columns"]), "self" if fk.get("referred_schema") in {None, schema} else fk["referred_schema"], fk["referred_table"], tuple(fk["referred_columns"]), str(fk["options"])) for fk in inspector.get_foreign_keys(name, schema)),
            "unique": sorted(tuple(item["column_names"]) for item in inspector.get_unique_constraints(name, schema)),
            "checks": sorted(normalize(item["sqltext"]) for item in inspector.get_check_constraints(name, schema)),
            "indexes": sorted((item["name"], str(item["column_names"]), item["unique"], normalize(item.get("dialect_options", {}))) for item in inspector.get_indexes(name, schema)),
        }
    enums = connection.execute(text("""
        SELECT t.typname, array_agg(e.enumlabel ORDER BY e.enumsortorder)
        FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
        JOIN pg_enum e ON e.enumtypid = t.oid
        WHERE n.nspname = :schema GROUP BY t.typname ORDER BY t.typname
    """), {"schema": schema}).all()
    return {"tables": tables, "enums": [(name, tuple(values)) for name, values in enums]}


def _legacy_version(connection: Connection, migrations: list[Migration]) -> int:
    actual = _signature(connection, "public")
    if not actual["tables"] and not actual["enums"]:
        return 0
    # 仅接管原有 001—003 的完整结构，未知结构必须人工核对。
    for count in range(min(3, len(migrations)), 0, -1):
        schema = f"migration_check_{uuid4().hex}"
        savepoint = connection.begin_nested()
        try:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}", pg_catalog')
            for migration in migrations[:count]:
                connection.exec_driver_sql(migration.sql)
            expected = _signature(connection, schema)
        finally:
            # 回滚验证结构及 search_path，不留下临时表、枚举或数据。
            savepoint.rollback()
        if actual == expected:
            return count
    raise MigrationError("旧库结构与 001—003 不匹配，未接管版本；请核对表、约束及枚举")


def migrate(engine: Engine | None = None, directory: Path | None = None) -> list[str]:
    migrations = load_migrations(directory or get_settings().migration_directory)
    engine = engine or get_engine()
    if engine.dialect.name != "postgresql":
        raise MigrationError("正式数据库迁移仅支持 PostgreSQL")
    applied = []
    with engine.connect() as connection:
        with connection.begin():
            if not connection.scalar(text("SELECT pg_try_advisory_lock(:id)"), {"id": LOCK_ID}):
                raise MigrationError("已有数据库迁移正在运行")
            connection.exec_driver_sql("SET search_path TO public")
        try:
            with connection.begin():
                connection.exec_driver_sql("""
                    CREATE TABLE IF NOT EXISTS schema_migration (
                        version VARCHAR(3) PRIMARY KEY,
                        name VARCHAR(200) NOT NULL,
                        checksum VARCHAR(64) NOT NULL,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                """)
                rows = connection.execute(text("SELECT version, name, checksum FROM schema_migration ORDER BY version")).all()
                if [row.version for row in rows] != [item.version for item in migrations[:len(rows)]]:
                    raise MigrationError("数据库版本未知或迁移记录不连续")
                for row, migration in zip(rows, migrations):
                    if row.name != migration.name or row.checksum != migration.checksum:
                        raise MigrationError(f"已执行迁移 {row.version} 的文件被修改，拒绝继续升级")
                completed = len(rows)
                if not rows:
                    completed = _legacy_version(connection, migrations)
                    for migration in migrations[:completed]:
                        _record_migration(connection, migration)
            # 分文件提交，枚举新值在后续迁移使用前已生效；DDL 与版本记录同事务。
            for migration in migrations[completed:]:
                with connection.begin():
                    connection.exec_driver_sql(migration.sql)
                    _record_migration(connection, migration)
                applied.append(migration.version)
        finally:
            if connection.in_transaction():
                connection.rollback()
            with connection.begin():
                connection.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})
    return applied


def main() -> int:
    try:
        versions = migrate()
        print("数据库迁移完成：" + (", ".join(versions) if versions else "已是最新版本"))
        return 0
    except MigrationError as exc:
        print(f"数据库迁移失败：{exc}")
        return 1
    except SQLAlchemyError:
        # 不把连接凭据、SQL 参数或已有业务数据写入输出。
        print("数据库迁移失败：请检查数据库连接、权限及迁移约束")
        return 1
    except (OSError, UnicodeError, ValidationError):
        print("数据库迁移失败：请检查配置及迁移目录")
        return 1
    finally:
        close_database()


if __name__ == "__main__":
    raise SystemExit(main())
