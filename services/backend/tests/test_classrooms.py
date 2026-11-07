import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.domain import Role, UserStatus
from app.core.passwords import hash_password
from app.core.errors import ApiError
from app.db.models import AppUser, AuditLog, ClassSession, ClassroomImport, Course, EmojiRecord, ScheduleUser
from app.schemas.contracts import ClassroomSeedRequest, LoginRequest
from app.services import classrooms

PASSWORD = "synthetic-password-2026"
ROOT = Path(__file__).resolve().parents[3]


def create_course(data, teacher="teacher-a", name="软件工程"):
    response = data["client"].post("/api/admin/courses", headers=data["headers"]["admin"], json={"name": name, "teacherId": data["users"][teacher]["id"]})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def session_body(course, **extra):
    start = datetime.now(timezone.utc) + timedelta(days=2)
    return {"courseId": course["id"], "startsAt": start.isoformat(), "endsAt": (start + timedelta(hours=1)).isoformat(), "room": "101", "className": "测试班", **extra}


def create_session(data, course, **extra):
    body = session_body(course, **extra)
    response = data["client"].post("/api/admin/sessions", headers=data["headers"]["admin"], json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"], body


def schedule(data, classroom, names):
    return data["client"].post(f"/api/admin/sessions/{classroom['id']}/schedule", headers=data["headers"]["admin"], json={"userIds": [data["users"][name]["id"] for name in names]})


def visible(data, name):
    response = data["client"].get("/api/sessions", headers=data["headers"][name])
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    return response.json()["data"]


def test_classroom_scope_and_student_roster_privacy(actors):
    data = actors
    course_a, course_b = create_course(data), create_course(data, "teacher-b", "数据库")
    classroom_a, _ = create_session(data, course_a)
    classroom_b, _ = create_session(data, course_b)
    assert schedule(data, classroom_a, ["student-a", "student-b"]).status_code == 200
    assert schedule(data, classroom_b, ["student-b"]).status_code == 200
    assert len(visible(data, "admin")) == 2
    assert [row["id"] for row in visible(data, "teacher-a")] == [classroom_a["id"]]
    assert [row["id"] for row in visible(data, "teacher-b")] == [classroom_b["id"]]
    first = visible(data, "student-a")
    assert [row["id"] for row in first] == [classroom_a["id"]]
    assert first[0]["scheduledUserIds"] == [data["users"]["student-a"]["id"]]
    assert [student["id"] for student in first[0]["scheduledStudents"]] == first[0]["scheduledUserIds"]
    assert data["users"]["student-b"]["id"] not in json.dumps(first)
    roster = visible(data, "teacher-a")[0]["scheduledStudents"]
    assert {student["id"] for student in roster} == {data["users"][name]["id"] for name in ("student-a", "student-b")}
    assert all(set(student) == {"id", "username", "studentNo", "realName", "className", "status"} for student in roster)
    assert "email" not in json.dumps(first) and "password" not in json.dumps(roster)
    assert len(visible(data, "student-b")) == 2
    attempted = data["client"].get("/api/sessions", headers=data["headers"]["teacher-a"], params={"teacherId": data["users"]["teacher-b"]["id"]})
    assert [row["id"] for row in attempted.json()["data"]] == [classroom_a["id"]]


def test_course_default_teacher_does_not_reassign_existing_classrooms(actors):
    data = actors
    course = create_course(data)
    original, _ = create_session(data, course)
    override, _ = create_session(data, course, teacherId=data["users"]["teacher-b"]["id"])
    response = data["client"].put(f"/api/admin/courses/{course['id']}", headers=data["headers"]["admin"], json={"name": "软件工程新名称", "teacherId": data["users"]["teacher-b"]["id"]})
    assert response.status_code == 200
    future, _ = create_session(data, course)
    assert future["teacherId"] == data["users"]["teacher-b"]["id"]
    assert [row["id"] for row in visible(data, "teacher-a")] == [original["id"]]
    assert {row["id"] for row in visible(data, "teacher-b")} == {override["id"], future["id"]}
    assert all(row["courseName"] == "软件工程新名称" for row in visible(data, "admin"))


@pytest.mark.parametrize("name", ["teacher-a", "student-a"])
def test_non_admin_cannot_manage_courses_sessions_rosters_or_profiles(actors, name):
    data = actors
    client, identity = data["client"], data["headers"][name]
    body = {"name": "课程", "teacherId": data["users"]["teacher-a"]["id"]}
    assert client.get("/api/admin/courses", headers=identity).status_code == 403
    assert client.post("/api/admin/courses", headers=identity, json=body).status_code == 403
    assert client.put(f"/api/admin/courses/{uuid4()}", headers=identity, json=body).status_code == 403
    classroom = session_body({"id": str(uuid4())})
    assert client.post("/api/admin/sessions", headers=identity, json=classroom).status_code == 403
    assert client.put(f"/api/admin/sessions/{uuid4()}", headers=identity, json=classroom).status_code == 403
    assert client.post(f"/api/admin/sessions/{uuid4()}/schedule", headers=identity, json={"userIds": []}).status_code == 403
    assert client.put(f"/api/admin/users/{data['users']['student-a']['id']}/student-profile", headers=identity, json={"realName": "不能越权修改"}).status_code == 403


def test_missing_identity_and_missing_objects(actors):
    data = actors
    client, identity = data["client"], data["headers"]["admin"]
    assert client.get("/api/sessions").status_code == 401
    assert client.get("/api/admin/courses").status_code == 401
    course = create_course(data)
    assert client.put(f"/api/admin/courses/{uuid4()}", headers=identity, json={"name": "课程", "teacherId": data["users"]["teacher-a"]["id"]}).status_code == 404
    assert client.post("/api/admin/sessions", headers=identity, json=session_body({"id": str(uuid4())})).status_code == 404
    assert client.put(f"/api/admin/sessions/{uuid4()}", headers=identity, json=session_body(course)).status_code == 404
    assert client.post(f"/api/admin/sessions/{uuid4()}/schedule", headers=identity, json={"userIds": []}).status_code == 404
    assert client.put(f"/api/admin/users/{uuid4()}/student-profile", headers=identity, json={"realName": "姓名"}).status_code == 404


@pytest.mark.parametrize("invalid", ["student-a", "admin", "missing", "disabled", "pending"])
def test_course_requires_active_approved_teacher(actors, invalid):
    data = actors
    client = data["client"]
    if invalid == "pending":
        assert client.post("/api/auth/register", json={"username": "pending", "email": "pending@example.edu", "password": PASSWORD, "role": "TEACHER"}).status_code == 200
        with data["factory"]() as session:
            teacher_id = str(session.scalar(select(AppUser).where(AppUser.username == "pending")).id)
    elif invalid == "disabled":
        teacher_id = data["users"]["teacher-a"]["id"]
        with data["factory"].begin() as session:
            session.get(AppUser, UUID(teacher_id)).status = UserStatus.DISABLED
    else:
        teacher_id = str(uuid4()) if invalid == "missing" else data["users"][invalid]["id"]
    response = client.post("/api/admin/courses", headers=data["headers"]["admin"], json={"name": "课程", "teacherId": teacher_id})
    assert response.status_code == 422 and response.json()["code"] == "INVALID_TEACHER"
    with data["factory"]() as session:
        assert session.scalar(select(func.count()).select_from(Course)) == 0


def test_session_validation_and_explicit_teacher_assignment(actors):
    data = actors
    client, identity = data["client"], data["headers"]["admin"]
    course = create_course(data)
    for extra in ({"startsAt": "2027-01-01T09:00:00"}, {"endsAt": "2000-01-01T00:00:00Z"}, {"room": " "}, {"teacherId": None}, {"extra": "unexpected"}):
        assert client.post("/api/admin/sessions", headers=identity, json=session_body(course, **extra)).status_code == 422
    assert client.post("/api/admin/sessions", headers=identity, json=session_body(course, teacherId=data["users"]["student-a"]["id"])).status_code == 422
    classroom, body = create_session(data, course, teacherId=data["users"]["teacher-b"]["id"])
    assert classroom["teacherName"] == "teacher-b姓名"
    body.pop("teacherId")
    response = client.put(f"/api/admin/sessions/{classroom['id']}", headers=identity, json={**body, "room": "202"})
    assert response.status_code == 200
    assert response.json()["data"]["teacherId"] == data["users"]["teacher-b"]["id"]


def test_future_reassignment_preserves_roster_and_updates_scope(actors):
    data = actors
    course = create_course(data)
    classroom, body = create_session(data, course)
    assert schedule(data, classroom, ["student-a"]).status_code == 200
    response = data["client"].put(f"/api/admin/sessions/{classroom['id']}", headers=data["headers"]["admin"], json={**body, "teacherId": data["users"]["teacher-b"]["id"]})
    assert response.status_code == 200
    assert response.json()["data"]["scheduledUserIds"] == [data["users"]["student-a"]["id"]]
    assert visible(data, "teacher-a") == []
    assert [row["id"] for row in visible(data, "teacher-b")] == [classroom["id"]]


@pytest.mark.parametrize("has_record", [False, True])
def test_started_or_recorded_classroom_cannot_change_history_scope(actors, has_record):
    data = actors
    course = create_course(data)
    extra = {}
    if not has_record:
        start = datetime.now(timezone.utc) - timedelta(hours=1)
        extra = {"startsAt": start.isoformat(), "endsAt": (start + timedelta(hours=2)).isoformat()}
    classroom, body = create_session(data, course, **extra)
    if has_record:
        with data["factory"].begin() as session:
            session.add(EmojiRecord(user_id=UUID(data["users"]["student-a"]["id"]), session_id=UUID(classroom["id"]), emotion="HAPPY", source="MANUAL"))
    response = data["client"].put(f"/api/admin/sessions/{classroom['id']}", headers=data["headers"]["admin"], json={**body, "teacherId": data["users"]["teacher-b"]["id"]})
    assert response.status_code == 409 and response.json()["code"] == "CLASSROOM_LOCKED"
    correction = data["client"].put(f"/api/admin/sessions/{classroom['id']}", headers=data["headers"]["admin"], json={**body, "room": "新教室"})
    assert correction.status_code == 200
    assert correction.json()["data"]["teacherId"] == data["users"]["teacher-a"]["id"]


def test_schedule_replacement_is_deduplicated_and_preserves_records(actors):
    data = actors
    classroom, _ = create_session(data, create_course(data))
    assert schedule(data, classroom, ["student-a", "student-a", "student-b"]).status_code == 200
    with data["factory"].begin() as session:
        assert session.scalar(select(func.count()).select_from(ScheduleUser)) == 2
        session.add(EmojiRecord(user_id=UUID(data["users"]["student-a"]["id"]), session_id=UUID(classroom["id"]), emotion="HAPPY", source="MANUAL"))
    assert schedule(data, classroom, []).status_code == 200
    assert visible(data, "student-a") == []
    with data["factory"]() as session:
        assert session.scalar(select(func.count()).select_from(ScheduleUser)) == 0
        assert session.scalar(select(func.count()).select_from(EmojiRecord)) == 1


@pytest.mark.parametrize("invalid", ["teacher-a", "admin", "missing", "disabled", "pending"])
def test_invalid_schedule_cannot_partially_replace_roster(actors, invalid):
    data = actors
    client, identity = data["client"], data["headers"]["admin"]
    classroom, _ = create_session(data, create_course(data))
    assert schedule(data, classroom, ["student-a"]).status_code == 200
    if invalid == "pending":
        client.post("/api/auth/register", json={"username": "pending", "email": "pending@example.edu", "password": PASSWORD, "role": "TEACHER"})
        with data["factory"]() as session:
            invalid_id = str(session.scalar(select(AppUser).where(AppUser.username == "pending")).id)
    elif invalid == "disabled":
        invalid_id = data["users"]["student-b"]["id"]
        with data["factory"].begin() as session:
            session.get(AppUser, UUID(invalid_id)).status = UserStatus.DISABLED
    else:
        invalid_id = str(uuid4()) if invalid == "missing" else data["users"][invalid]["id"]
    response = client.post(f"/api/admin/sessions/{classroom['id']}/schedule", headers=identity, json={"userIds": [data["users"]["student-b"]["id"], invalid_id]})
    assert response.status_code == 422
    assert visible(data, "admin")[0]["scheduledUserIds"] == [data["users"]["student-a"]["id"]]


def test_profile_partial_updates_uniqueness_and_null_clear(actors):
    data = actors
    client, identity = data["client"], data["headers"]["admin"]
    student = data["users"]["student-a"]
    path = f"/api/admin/users/{student['id']}/student-profile"
    assert client.put(path, headers=identity, json={}).status_code == 422
    assert client.put(path, headers=identity, json={"role": "ADMIN"}).status_code == 422
    updated = client.put(path, headers=identity, json={"realName": "新姓名", "className": "新班级"})
    assert updated.status_code == 200
    assert updated.json()["data"]["studentNo"] == "20260001"
    assert updated.json()["data"]["email"] == student["email"]
    assert client.get("/api/users/me", headers=data["headers"]["student-a"]).json()["data"]["realName"] == "新姓名"
    conflict = client.put(path, headers=identity, json={"studentNo": "20260002", "realName": "不能部分保存"})
    assert conflict.status_code == 409 and conflict.json()["code"] == "STUDENT_NO_EXISTS"
    cleared = client.put(path, headers=identity, json={"studentNo": None}).json()["data"]
    assert cleared["studentNo"] is None and cleared["realName"] == "新姓名"
    assert visible(data, "student-a") == []
    assert client.put(f"/api/admin/users/{data['users']['teacher-a']['id']}/student-profile", headers=identity, json={"realName": "无效对象"}).status_code == 422


def test_schedule_audit_failure_rolls_back_complete_roster(actors):
    data = actors
    classroom, _ = create_session(data, create_course(data))
    schedule(data, classroom, ["student-a"])
    with data["database"].begin() as connection:
        connection.exec_driver_sql("CREATE FUNCTION reject_roster_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action = 'CLASS_SCHEDULE_REPLACE' THEN RAISE EXCEPTION 'private roster failure'; END IF; RETURN NEW; END $$; CREATE TRIGGER reject_roster_audit BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION reject_roster_audit();")
    response = schedule(data, classroom, ["student-b"])
    assert response.status_code == 500 and "private roster failure" not in response.text
    assert visible(data, "admin")[0]["scheduledUserIds"] == [data["users"]["student-a"]["id"]]


def test_concurrent_schedule_replacements_commit_whole_rosters(actors):
    data = actors
    classroom, _ = create_session(data, create_course(data))
    with data["factory"].begin() as session:
        session.add(AppUser(username="admin-b", email="admin-b@example.edu", password_hash=hash_password(PASSWORD), role=Role.ADMIN))
    other = data["client"].post("/api/auth/login", json={"username": "admin-b", "password": PASSWORD})
    second_admin = {"Authorization": "Bearer " + other.json()["data"]["token"]}
    def replace(item):
        identity, name = item
        return data["client"].post(f"/api/admin/sessions/{classroom['id']}/schedule", headers=identity, json={"userIds": [data["users"][name]["id"]]}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(replace, [(data["headers"]["admin"], "student-a"), (second_admin, "student-b")])) == [200, 200]
    final = visible(data, "admin")[0]["scheduledUserIds"]
    assert final in [[data["users"]["student-a"]["id"]], [data["users"]["student-b"]["id"]]]


@pytest.mark.parametrize("kind", ["course", "session"])
def test_concurrent_teacher_change_does_not_overwrite_new_assignment(actors, kind):
    data = actors
    course = create_course(data)
    classroom, body = create_session(data, course)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with data["database"].begin() as writer:
            table, object_id = ("course", course["id"]) if kind == "course" else ("class_session", classroom["id"])
            writer.execute(text(f"UPDATE {table} SET teacher_id = :teacher WHERE id = :id"), {"teacher": data["users"]["teacher-b"]["id"], "id": object_id})
            if kind == "course":
                request = pool.submit(data["client"].post, "/api/admin/sessions", headers=data["headers"]["admin"], json=body)
            else:
                request = pool.submit(data["client"].put, f"/api/admin/sessions/{classroom['id']}", headers=data["headers"]["admin"], json={**body, "room": "202"})
            blocked = False
            for _ in range(100):
                with data["database"].connect() as reader:
                    blocked = reader.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock')"))
                if blocked:
                    break
                time.sleep(0.01)
            assert blocked
        response = request.result(timeout=10)
        assert response.status_code == 409 and response.json()["code"] == "CONFLICT"
    finally:
        pool.shutdown(wait=True)


def test_profile_audit_failure_and_disabled_student_maintenance(actors):
    data = actors
    student_id = data["users"]["student-a"]["id"]
    path = f"/api/admin/users/{student_id}/student-profile"
    with data["factory"].begin() as session:
        session.get(AppUser, UUID(student_id)).status = UserStatus.DISABLED
    updated = data["client"].put(path, headers=data["headers"]["admin"], json={"realName": "可维护的资料"})
    assert updated.status_code == 200 and updated.json()["data"]["status"] == "DISABLED"
    with data["database"].begin() as connection:
        connection.exec_driver_sql("CREATE FUNCTION reject_profile_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action = 'STUDENT_PROFILE_UPDATE' THEN RAISE EXCEPTION 'private profile failure'; END IF; RETURN NEW; END $$; CREATE TRIGGER reject_profile_audit BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION reject_profile_audit();")
    response = data["client"].put(path, headers=data["headers"]["admin"], json={"realName": "不会保存"})
    assert response.status_code == 500 and "private profile failure" not in response.text
    with data["factory"]() as session:
        assert session.get(AppUser, UUID(student_id)).real_name == "可维护的资料"


def seed_body():
    start = datetime.now(timezone.utc) + timedelta(days=3)
    return {
        "importId": str(uuid4()),
        "courses": [
            {"key": "software", "name": "软件工程", "teacherUsername": "teacher-a"},
            {"key": "database", "name": "数据库", "teacherUsername": "teacher-b"},
        ],
        "sessions": [
            {"courseKey": "software", "startsAt": start.isoformat(), "endsAt": (start + timedelta(hours=1)).isoformat(), "room": "101", "className": "一班", "studentUsernames": ["student-a"]},
            {"courseKey": "database", "teacherUsername": "teacher-a", "startsAt": (start + timedelta(hours=2)).isoformat(), "endsAt": (start + timedelta(hours=3)).isoformat(), "room": "102", "className": "二班", "studentUsernames": ["student-a", "student-b"]},
        ],
    }


def test_atomic_import_uses_existing_accounts_and_rejects_repeat(actors):
    data = actors
    request = ClassroomSeedRequest.model_validate(seed_body())
    credentials = LoginRequest(username="admin", password=PASSWORD)
    result = classrooms.import_classrooms(credentials, request)
    assert len(result.course_ids) == len(result.session_ids) == 2
    assert len(visible(data, "teacher-a")) == 2
    assert visible(data, "teacher-b") == []
    with pytest.raises(ApiError) as error:
        classrooms.import_classrooms(credentials, request)
    assert error.value.code == "IMPORT_ALREADY_EXISTS"
    with data["factory"]() as session:
        assert session.scalar(select(func.count()).select_from(Course)) == 2
        assert session.scalar(select(func.count()).select_from(ClassSession)) == 2
        assert session.scalar(select(func.count()).select_from(ClassroomImport)) == 1
        assert session.scalar(select(func.count()).select_from(AppUser)) == 5
        assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "CLASSROOM_IMPORT")) == 1


@pytest.mark.parametrize("username,password", [("admin", "wrong-password"), ("teacher-a", PASSWORD), ("student-a", PASSWORD)])
def test_import_requires_real_admin_credentials(actors, username, password):
    with pytest.raises(ApiError) as error:
        classrooms.import_classrooms(LoginRequest(username=username, password=password), ClassroomSeedRequest.model_validate(seed_body()))
    assert error.value.status_code in {401, 403}
    with actors["factory"]() as session:
        assert session.scalar(select(func.count()).select_from(Course)) == 0


def test_import_failure_rolls_back_marker_courses_rosters_and_audits(actors):
    data = actors
    request = ClassroomSeedRequest.model_validate(seed_body())
    with data["database"].begin() as connection:
        connection.exec_driver_sql("CREATE FUNCTION reject_classroom_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action = 'CLASS_SESSION_CREATE' THEN RAISE EXCEPTION 'private classroom failure'; END IF; RETURN NEW; END $$; CREATE TRIGGER reject_classroom_audit BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION reject_classroom_audit();")
    with pytest.raises(DBAPIError):
        classrooms.import_classrooms(LoginRequest(username="admin", password=PASSWORD), request)
    with data["factory"]() as session:
        for model in (ClassroomImport, Course, ClassSession, ScheduleUser):
            assert session.scalar(select(func.count()).select_from(model)) == 0
    with data["database"].begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER reject_classroom_audit ON audit_log")
    assert len(classrooms.import_classrooms(LoginRequest(username="admin", password=PASSWORD), request).session_ids) == 2


def test_concurrent_imports_do_not_duplicate_classrooms(actors):
    request = ClassroomSeedRequest.model_validate(seed_body())
    def run(_):
        try:
            classrooms.import_classrooms(LoginRequest(username="admin", password=PASSWORD), request)
            return "CREATED"
        except ApiError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, range(2))) == ["CREATED", "IMPORT_ALREADY_EXISTS"]


def test_import_command_validates_files_and_does_not_echo_password(actors, tmp_path):
    data = actors
    source = tmp_path / "classrooms.json"
    source.write_text(json.dumps(seed_body(), ensure_ascii=False), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": "services/backend", "PYTHONIOENCODING": "utf-8", "MOOD_DATABASE_URL": data["database"].url.render_as_string(hide_password=False)}
    command = [sys.executable, "-m", "app.cli.import_classrooms", "--username", "admin", "--file", str(source), "--password-stdin"]
    result = subprocess.run(command, input=PASSWORD + "\n", env=env, cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert PASSWORD not in result.stdout + result.stderr
    repeated = subprocess.run(command, input=PASSWORD + "\n", env=env, cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=20)
    assert repeated.returncode == 1 and "IMPORT_ALREADY_EXISTS" in repeated.stderr
    source.write_text(json.dumps({"password": PASSWORD}), encoding="utf-8")
    invalid = subprocess.run(command, input=PASSWORD + "\n", env=env, cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=20)
    assert invalid.returncode == 1
    assert PASSWORD not in invalid.stdout + invalid.stderr


def test_session_order_uses_actual_timestamps(actors):
    data = actors
    course = create_course(data)
    start = datetime.now(timezone.utc) + timedelta(days=2)
    later, _ = create_session(data, course, startsAt=(start + timedelta(hours=2)).isoformat(), endsAt=(start + timedelta(hours=3)).isoformat())
    earlier, _ = create_session(data, course, startsAt=start.astimezone(timezone(timedelta(hours=8))).isoformat(), endsAt=(start + timedelta(hours=1)).astimezone(timezone(timedelta(hours=8))).isoformat())
    assert [row["id"] for row in visible(data, "admin")] == [earlier["id"], later["id"]]
