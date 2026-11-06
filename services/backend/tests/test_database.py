from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.domain import Emotion, RecordSource, Role
from app.db.migrate import LOCK_ID, MigrationError, load_migrations, migrate
from app.db.models import AppUser, Base, ClassSession, Course, EmojiRecord, TeacherApplication, UserSession, WsTicket
from app.db.session import transaction

DIRECTORY = Path(__file__).resolve().parents[3] / "infra/database"
VERSIONS = [item.version for item in load_migrations(DIRECTORY)]


def seed(engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with transaction(factory) as session:
        teacher = AppUser(username="teacher", password_hash="synthetic-hash", email="teacher@example.edu", role=Role.TEACHER)
        student = AppUser(username="student", password_hash="synthetic-hash", email="student@example.edu")
        session.add_all([teacher, student])
        session.flush()
        course = Course(name="数据库", teacher_id=teacher.id)
        session.add(course)
        session.flush()
        now = datetime.now(timezone.utc)
        classroom = ClassSession(course_id=course.id, teacher_id=teacher.id, starts_at=now, ends_at=now + timedelta(hours=1), room="101", class_name="测试班")
        session.add(classroom)
        session.flush()
    return factory, student.id, classroom.id


def test_fresh_database_repeat_and_orm_schema(database):
    assert migrate(database, DIRECTORY) == VERSIONS
    assert migrate(database, DIRECTORY) == []
    inspector = inspect(database)
    assert set(inspector.get_table_names()) == set(Base.metadata.tables) | {"schema_migration"}
    for name, table in Base.metadata.tables.items():
        actual = {column["name"]: column for column in inspector.get_columns(name)}
        assert set(actual) == set(table.columns.keys())
        for column in table.columns:
            assert actual[column.name]["nullable"] == column.nullable
            assert str(actual[column.name]["type"].compile(dialect=database.dialect)) == str(column.type.compile(dialect=database.dialect))
        assert {item["name"] for item in inspector.get_indexes(name)} == {index.name for index in table.indexes} | {item["name"] for item in inspector.get_indexes(name) if item.get("duplicates_constraint")}
        assert {item["name"] for item in inspector.get_check_constraints(name)} == {constraint.name for constraint in table.constraints if constraint.__class__.__name__ == "CheckConstraint"}


@pytest.mark.parametrize("version", [1, 2, 3])
def test_upgrade_legacy_preserves_records_and_teacher_role(database, version):
    for migration in load_migrations(DIRECTORY)[:version]:
        with database.begin() as connection:
            connection.exec_driver_sql(migration.sql)
    # 旧结构通过 SQL 写入，避免依赖新 ORM 列。
    with database.begin() as connection:
        teacher_id = connection.scalar(text("INSERT INTO app_user(username, password_hash, email, role) VALUES ('teacher', 'synthetic-hash', 'teacher@example.edu', 'TEACHER') RETURNING id"))
        course_id = connection.scalar(text("INSERT INTO course(name, teacher_id) VALUES ('数据库', :teacher) RETURNING id"), {"teacher": teacher_id})
        classroom_id = connection.scalar(text("INSERT INTO class_session(course_id, starts_at, ends_at, room, class_name) VALUES (:course, now(), now() + interval '1 hour', '101', '测试班') RETURNING id"), {"course": course_id})
        record_id = connection.scalar(text("INSERT INTO emoji_record(session_id, emotion, source, confidence, device_id) VALUES (:classroom, 'HAPPY', 'AI', 0.9, 'test-camera') RETURNING id"), {"classroom": classroom_id})
    assert migrate(database, DIRECTORY) == VERSIONS[version:]
    assert migrate(database, DIRECTORY) == []
    with database.connect() as connection:
        assert connection.scalar(text("SELECT id FROM emoji_record")) == record_id
        assert connection.scalar(text("SELECT teacher_id FROM class_session WHERE id = :classroom"), {"classroom": classroom_id}) == teacher_id
        assert connection.scalar(text("SELECT status FROM teacher_application WHERE user_id = :user"), {"user": teacher_id}) == "APPROVED"
        assert connection.scalar(text("SELECT role FROM app_user WHERE id = :user"), {"user": teacher_id}) == "TEACHER"
        assert connection.scalar(text("SELECT count(*) FROM schema_migration")) == len(VERSIONS)


def test_unknown_legacy_schema_is_not_stamped(database):
    with database.begin() as connection:
        connection.exec_driver_sql(load_migrations(DIRECTORY)[0].sql)
        connection.exec_driver_sql("ALTER TABLE course DROP CONSTRAINT course_teacher_id_fkey")
    with pytest.raises(MigrationError, match="旧库结构"):
        migrate(database, DIRECTORY)
    assert "schema_migration" not in inspect(database).get_table_names()


def test_upgrade_from_tracked_foundation_preserves_classroom_and_backfills_teacher(database, tmp_path):
    for path in sorted(DIRECTORY.glob("*.sql"))[:4]:
        (tmp_path / path.name).write_bytes(path.read_bytes())
    assert migrate(database, tmp_path) == VERSIONS[:4]
    with database.begin() as connection:
        teacher = connection.scalar(text("INSERT INTO app_user(username, password_hash, email, role) VALUES ('teacher', 'synthetic-hash', 'teacher@example.edu', 'TEACHER') RETURNING id"))
        course = connection.scalar(text("INSERT INTO course(name, teacher_id) VALUES ('数据库', :teacher) RETURNING id"), {"teacher": teacher})
        classroom = connection.scalar(text("INSERT INTO class_session(course_id, starts_at, ends_at, room, class_name) VALUES (:course, now(), now() + interval '1 hour', '101', '测试班') RETURNING id"), {"course": course})
    assert migrate(database, DIRECTORY) == VERSIONS[4:]
    with database.connect() as connection:
        assert connection.scalar(text("SELECT teacher_id FROM class_session WHERE id = :classroom"), {"classroom": classroom}) == teacher
    assert migrate(database, DIRECTORY) == []


def test_constraint_failure_preserves_legacy_data_and_can_resume(database):
    for migration in load_migrations(DIRECTORY)[:3]:
        with database.begin() as connection:
            connection.exec_driver_sql(migration.sql)
    with database.begin() as connection:
        teacher = connection.scalar(text("INSERT INTO app_user(username, password_hash, email, role) VALUES ('teacher', 'synthetic-hash', 'teacher@example.edu', 'TEACHER') RETURNING id"))
        course = connection.scalar(text("INSERT INTO course(name, teacher_id) VALUES ('数据库', :teacher) RETURNING id"), {"teacher": teacher})
        classroom = connection.scalar(text("INSERT INTO class_session(course_id, starts_at, ends_at, room, class_name) VALUES (:course, now(), now() + interval '1 hour', '101', '测试班') RETURNING id"), {"course": course})
        record = connection.scalar(text("INSERT INTO emoji_record(session_id, emotion, source, confidence, device_id) VALUES (:classroom, 'FOCUSED', 'AI', 0.9, 'test-camera') RETURNING id"), {"classroom": classroom})
    with pytest.raises(IntegrityError):
        migrate(database, DIRECTORY)
    with database.connect() as connection:
        assert connection.scalar(text("SELECT id FROM emoji_record")) == record
        assert connection.scalar(text("SELECT max(version) FROM schema_migration")) == "003"
    assert "teacher_application" not in inspect(database).get_table_names()
    with database.begin() as connection:
        connection.execute(text("UPDATE emoji_record SET emotion = 'HAPPY' WHERE id = :record"), {"record": record})
    assert migrate(database, DIRECTORY) == VERSIONS[3:]


def copy_migrations(tmp_path):
    for path in DIRECTORY.glob("*.sql"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    return tmp_path


def test_checksum_failure_and_atomic_retry(database, tmp_path):
    migrate(database, DIRECTORY)
    directory = copy_migrations(tmp_path)
    path = directory / "004_backend_foundation.sql"
    original = path.read_text(encoding="utf-8")
    path.write_text(original + "\n-- 修改已执行文件\n", encoding="utf-8")
    with pytest.raises(MigrationError, match="文件被修改"):
        migrate(database, directory)
    path.write_text(original, encoding="utf-8")
    next_version = f"{len(VERSIONS) + 1:03}"
    future = directory / f"{next_version}_test.sql"
    future.write_text("CREATE TABLE migration_probe(id integer); SELECT 1 / 0;")
    with pytest.raises(DBAPIError):
        migrate(database, directory)
    assert "migration_probe" not in inspect(database).get_table_names()
    with database.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM schema_migration")) == len(VERSIONS)
    future.write_text("CREATE TABLE migration_probe(id integer);")
    assert migrate(database, directory) == [next_version]


def test_migration_lock_and_unknown_version(database):
    with database.connect() as holder:
        holder.execute(text("SELECT pg_advisory_lock(:id)"), {"id": LOCK_ID})
        try:
            with pytest.raises(MigrationError, match="正在运行"):
                migrate(database, DIRECTORY)
        finally:
            holder.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})
    migrate(database, DIRECTORY)
    with database.begin() as connection:
        connection.execute(text("UPDATE schema_migration SET version = :unknown WHERE version = :latest"), {"unknown": f"{len(VERSIONS) + 1:03}", "latest": VERSIONS[-1]})
    with pytest.raises(MigrationError, match="版本未知"):
        migrate(database, DIRECTORY)


def test_transaction_commit_rollback_and_identity_uniqueness(database):
    migrate(database, DIRECTORY)
    factory, student_id, _ = seed(database)
    with pytest.raises(RuntimeError):
        with transaction(factory) as session:
            session.get(AppUser, student_id).real_name = "不会保存"
            session.flush()
            raise RuntimeError("回滚")
    with transaction(factory) as session:
        assert session.get(AppUser, student_id).real_name is None
        session.get(AppUser, student_id).student_no = "20260001"
    with pytest.raises(IntegrityError):
        with transaction(factory) as session:
            session.add(AppUser(username="duplicate", email="duplicate@example.edu", password_hash="synthetic-hash", student_no="20260001"))


def test_ai_and_manual_idempotency_are_separate_and_concurrent(database):
    migrate(database, DIRECTORY)
    factory, student_id, classroom_id = seed(database)

    def insert(source, key, user_id=None):
        try:
            with transaction(factory) as session:
                session.add(EmojiRecord(user_id=user_id, session_id=classroom_id, emotion=Emotion.HAPPY, source=source, confidence=0.9 if source == RecordSource.AI else None, device_id="test-camera" if source == RecordSource.AI else None, idempotency_key=key, request_hash="a" * 64))
            return True
        except IntegrityError:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(lambda _: insert(RecordSource.AI, "same-event"), range(8))) == 1
    assert insert(RecordSource.MANUAL, "same-event", student_id)
    assert not insert(RecordSource.MANUAL, "same-event", student_id)


@pytest.mark.parametrize("extra", [
    {"emotion": Emotion.FOCUSED}, {"emotion": Emotion.CONFUSED},
    {"device_id": ""}, {"confidence": 1.1},
    {"inference_provider": "DeepSeek", "confidence_kind": "model_score"},
    {"idempotency_key": "missing-hash"},
])
def test_ai_constraints(database, extra):
    migrate(database, DIRECTORY)
    factory, _, classroom_id = seed(database)
    values = {"session_id": classroom_id, "emotion": Emotion.HAPPY, "source": RecordSource.AI, "confidence": 0.9, "device_id": "test-camera", **extra}
    with pytest.raises(IntegrityError):
        with transaction(factory) as session:
            session.add(EmojiRecord(**values))


def test_ticket_lifetime_and_teacher_review_constraints(database):
    migrate(database, DIRECTORY)
    factory, student_id, _ = seed(database)
    now = datetime.now(timezone.utc)
    with transaction(factory) as session:
        identity = UserSession(user_id=student_id, token_hash="a" * 64, created_at=now, expires_at=now + timedelta(hours=8))
        session.add(identity)
        session.flush()
    with pytest.raises(IntegrityError):
        with transaction(factory) as session:
            session.add(WsTicket(session_id=identity.id, token_hash="b" * 64, created_at=now, expires_at=now + timedelta(seconds=31)))
    with pytest.raises(IntegrityError):
        with transaction(factory) as session:
            session.add(TeacherApplication(user_id=student_id, status="APPROVED"))


def test_pool_reuse_and_database_readiness(database, monkeypatch):
    from app.core.config import get_settings
    from app.db.session import close_database, get_engine, get_session_factory
    from app.repositories.health import database_available

    close_database()
    monkeypatch.setenv("MOOD_DATABASE_URL", database.url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    try:
        assert get_engine() is get_engine()
        assert get_session_factory() is get_session_factory()
        assert database_available()
        close_database()
        monkeypatch.setenv("MOOD_DATABASE_URL", "postgresql+psycopg://test@127.0.0.1:1/unavailable")
        get_settings.cache_clear()
        assert not database_available()
    finally:
        close_database()
        get_settings.cache_clear()
