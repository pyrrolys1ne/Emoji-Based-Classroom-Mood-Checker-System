from pathlib import Path

from sqlalchemy import text

from app.db.migrate import load_migrations, migrate


def test_upgrade_preserves_records_and_versions_roll_back(database, tmp_path):
    directory = Path(__file__).resolve().parents[3] / "infra/database"
    for item in load_migrations(directory)[:6]:
        (tmp_path / item.name).write_text(item.sql, encoding="utf-8")
    migrate(database, tmp_path)
    with database.begin() as connection:
        teacher = connection.scalar(text("INSERT INTO app_user(username,password_hash,email,role) VALUES ('teacher','synthetic-hash','teacher@example.edu','TEACHER') RETURNING id"))
        course = connection.scalar(text("INSERT INTO course(name,teacher_id) VALUES ('课程',:teacher) RETURNING id"), {"teacher": teacher})
        classroom = connection.scalar(text("INSERT INTO class_session(course_id,teacher_id,starts_at,ends_at,room,class_name) VALUES (:course,:teacher,now(),now()+interval '1 hour','101','测试班') RETURNING id"), {"course": course, "teacher": teacher})
        record = connection.scalar(text("INSERT INTO emoji_record(session_id,user_id,emotion,source) VALUES (:classroom,:teacher,'HAPPY','MANUAL') RETURNING id"), {"classroom": classroom, "teacher": teacher})
    assert migrate(database, directory) == [item.version for item in load_migrations(directory)[6:]]
    with database.connect() as connection:
        assert connection.scalar(text("SELECT id FROM emoji_record")) == record
        assert connection.scalar(text("SELECT revision FROM class_session WHERE id=:id"), {"id": classroom}) == 0
        connection.execute(text("UPDATE class_session SET room='202' WHERE id=:id"), {"id": classroom})
        assert connection.scalar(text("SELECT revision FROM class_session WHERE id=:id"), {"id": classroom}) == 1
        connection.rollback()
    with database.connect() as connection:
        assert connection.scalar(text("SELECT revision FROM class_session WHERE id=:id"), {"id": classroom}) == 0
    assert migrate(database, directory) == []
