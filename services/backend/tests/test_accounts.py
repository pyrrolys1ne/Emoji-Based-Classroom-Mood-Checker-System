import io
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.core.domain import Role, UserStatus
from app.core.errors import ApiError
from app.core.passwords import hash_password, verify_password
from app.db.models import AppUser, AuditLog, TeacherApplication, UserSession, WsTicket
from app.db.session import close_database
from app.main import app
from app.schemas.contracts import AdminBootstrapRequest, LoginRequest, PasswordRequest
from app.services import accounts

PASSWORD = "synthetic-password-2026"
NEW_PASSWORD = "synthetic-new-password-2026"
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def auth(api):
    return api


def register(client, username="student", **extra):
    body = {"username": username, "email": f"{username}@example.edu", "password": PASSWORD, **extra}
    return client.post("/api/auth/register", json=body)


def login(client, username="student", password=PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def headers(response):
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["data"]["token"]}


def administrator(client):
    user = accounts.bootstrap_admin(AdminBootstrapRequest(username="admin", email="admin@example.edu", password=PASSWORD))
    return user, headers(login(client, "admin"))


def test_registration_login_me_and_password_storage(auth):
    client, factory, _ = auth
    response = register(client, studentNo="20260001", realName="测试学生", className="测试班")
    assert response.status_code == 200 and response.json()["data"] is None
    assert response.headers["Cache-Control"] == "no-store"
    first = login(client)
    data = first.json()["data"]
    assert data["user"]["role"] == "STUDENT"
    assert data["user"]["studentNo"] == "20260001"
    assert data["token"].startswith("usr_") and len(data["token"]) == 47
    identity = client.get("/api/users/me", headers=headers(first))
    assert identity.json()["data"] == data["user"]
    assert identity.headers["Cache-Control"] == "no-store"
    with factory() as session:
        user = session.scalar(select(AppUser).where(AppUser.username == "student"))
        assert user.password_hash.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
        assert PASSWORD not in user.password_hash
        assert verify_password(PASSWORD, user.password_hash)
        stored = session.scalar(select(UserSession))
        assert stored.token_hash == accounts.token_digest(data["token"])
        assert stored.token_hash != data["token"]
        assert stored.expires_at - stored.created_at == timedelta(hours=8)
    assert "password" not in identity.text.lower() and "token" not in identity.text.lower()


@pytest.mark.parametrize("extra", [{"role": "ADMIN"}, {"status": "ACTIVE"}, {"userId": str(uuid4())}, {"passwordHash": "fake"}, {"role": "TEACHER", "studentNo": "20260001"}])
def test_public_registration_cannot_grant_permissions(auth, extra):
    client, factory, _ = auth
    response = register(client, **extra)
    assert response.status_code == 422
    assert PASSWORD not in response.text
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AppUser)) == 0
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 0


def test_duplicate_registration_is_atomic_and_has_specific_errors(auth):
    client, factory, _ = auth
    assert register(client, studentNo="20260001").status_code == 200
    assert register(client, email="other@example.edu").json()["code"] == "ACCOUNT_EXISTS"
    assert register(client, "other", email="student@example.edu").status_code == 409
    number = register(client, "other", studentNo="20260001")
    assert number.status_code == 409 and number.json()["code"] == "STUDENT_NO_EXISTS"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AppUser)) == 1
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 1


def test_wrong_credentials_and_malformed_or_wrong_namespace_tokens(auth):
    client, _, _ = auth
    register(client)
    missing = login(client, "unknown")
    wrong = login(client, password="wrong-password")
    assert missing.status_code == wrong.status_code == 401
    assert missing.json() == wrong.json()
    for value in ("fake-token", "usr_" + "a" * 43, "synthetic-ai-service", "synthetic-ai-control", "usr_短令牌"):
        response = client.get("/api/users/me", headers={"Authorization": "Bearer " + value}) if value.isascii() else accounts_invalid_unicode(value)
        assert response.status_code == 401
    assert client.get("/api/users/me").headers["WWW-Authenticate"] == "Bearer"
    valid = login(client).json()["data"]["token"]
    ai_body = {"sessionId": str(uuid4()), "emotion": "HAPPY", "confidence": 0.9, "recordedAt": datetime.now(timezone.utc).isoformat(), "deviceId": "test-camera"}
    assert client.post("/api/ai/emoji-results", json=ai_body, headers={"Authorization": "Bearer " + valid, "Idempotency-Key": "test-event"}).status_code == 401


def accounts_invalid_unicode(value):
    with pytest.raises(ApiError) as error:
        accounts.authenticate(value)
    return error.value


def test_multidevice_logout_revokes_only_current_session_and_ticket(auth):
    client, factory, _ = auth
    register(client)
    first, second = login(client), login(client)
    first_token, second_token = (item.json()["data"]["token"] for item in (first, second))
    with factory.begin() as session:
        identities = {row.token_hash: row for row in session.scalars(select(UserSession)).all()}
        now = datetime.now(timezone.utc)
        session.add_all([
            WsTicket(session_id=identities[accounts.token_digest(first_token)].id, token_hash="a" * 64, created_at=now, expires_at=now + timedelta(seconds=30)),
            WsTicket(session_id=identities[accounts.token_digest(second_token)].id, token_hash="b" * 64, created_at=now, expires_at=now + timedelta(seconds=30)),
        ])
    assert client.post("/api/auth/logout", headers=headers(first)).status_code == 200
    assert client.get("/api/users/me", headers=headers(first)).status_code == 401
    assert client.get("/api/users/me", headers=headers(second)).status_code == 200
    with factory() as session:
        tickets = {row.token_hash: row for row in session.scalars(select(WsTicket))}
        assert tickets["a" * 64].consumed_at is not None
        assert tickets["b" * 64].consumed_at is None


def test_password_change_revokes_all_sessions_and_tickets(auth):
    client, factory, _ = auth
    register(client)
    first, second = login(client), login(client)
    with factory.begin() as session:
        now = datetime.now(timezone.utc)
        for index, identity in enumerate(session.scalars(select(UserSession)).all()):
            session.add(WsTicket(session_id=identity.id, token_hash=str(index) * 64, created_at=now, expires_at=now + timedelta(seconds=30)))
    wrong = client.put("/api/auth/password", headers=headers(first), json={"oldPassword": "wrong-password", "newPassword": NEW_PASSWORD})
    assert wrong.status_code == 403 and wrong.json()["code"] == "INVALID_PASSWORD"
    assert client.get("/api/users/me", headers=headers(first)).status_code == 200
    response = client.put("/api/auth/password", headers=headers(first), json={"oldPassword": PASSWORD, "newPassword": NEW_PASSWORD})
    assert response.status_code == 200
    for identity in (first, second):
        assert client.get("/api/users/me", headers=headers(identity)).status_code == 401
    assert login(client).status_code == 401
    assert login(client, password=NEW_PASSWORD).status_code == 200
    with factory() as session:
        assert all(ticket.consumed_at is not None for ticket in session.scalars(select(WsTicket)))
        assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "AUTH_PASSWORD_CHANGE")) == 1


def test_expiry_disabled_account_and_teacher_role_without_approval(auth):
    client, factory, _ = auth
    register(client)
    identity = login(client)
    with factory.begin() as session:
        stored = session.scalar(select(UserSession))
        stored.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
        stored.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    assert client.get("/api/users/me", headers=headers(identity)).status_code == 401
    active = login(client)
    with factory.begin() as session:
        session.scalar(select(AppUser)).status = UserStatus.DISABLED
    assert client.get("/api/users/me", headers=headers(active)).status_code == 401
    assert login(client).json()["code"] == "ACCOUNT_DISABLED"
    with factory.begin() as session:
        user = session.scalar(select(AppUser))
        user.status = UserStatus.ACTIVE
        user.role = Role.TEACHER
    assert login(client).json()["code"] == "TEACHER_APPROVAL_REQUIRED"


def test_teacher_pending_approval_grants_only_teacher_and_rejects_repeated_review(auth):
    client, factory, _ = auth
    admin, admin_headers = administrator(client)
    assert register(client, "applicant", role="TEACHER", realName="测试教师").status_code == 200
    pending = login(client, "applicant")
    assert pending.status_code == 403 and pending.json()["code"] == "TEACHER_APPROVAL_REQUIRED"
    with factory() as session:
        assert session.scalar(select(AppUser).where(AppUser.username == "applicant")).role == Role.STUDENT
    response = client.get("/api/admin/teacher-applications", headers=admin_headers)
    application = response.json()["data"][0]
    assert application["status"] == "PENDING"
    approved = client.put(f"/api/admin/teacher-applications/{application['id']}", headers=admin_headers, json={"decision": "APPROVED", "reason": "资料已核对"})
    assert approved.status_code == 200
    assert approved.json()["data"]["reviewedBy"] == str(admin.id)
    assert approved.json()["data"]["reviewedAt"].endswith(("Z", "+00:00"))
    teacher_login = login(client, "applicant")
    assert teacher_login.json()["data"]["user"]["role"] == "TEACHER"
    assert teacher_login.json()["data"]["user"]["teacherApprovalStatus"] == "APPROVED"
    teacher_headers = headers(teacher_login)
    assert client.get("/api/admin/users", headers=teacher_headers).status_code == 403
    assert client.get("/api/admin/emoji/export", headers=teacher_headers).status_code == 403
    assert client.post(f"/api/admin/sessions/{uuid4()}/schedule", headers=teacher_headers, json={"userIds": []}).status_code == 403
    assert client.post("/api/emoji", headers={**teacher_headers, "Idempotency-Key": "event"}, json={"sessionId": str(uuid4()), "emotion": "HAPPY"}).status_code == 403
    assert client.get("/api/admin/statistics", headers=teacher_headers).json()["data"]["total"] == 0
    assert client.get("/api/emoji/statistics", headers=teacher_headers).json()["data"]["total"] == 0
    assert client.get("/api/admin/teacher-applications", headers=teacher_headers).status_code == 403
    assert client.put(f"/api/admin/teacher-applications/{application['id']}", headers=teacher_headers, json={"decision": "REJECTED"}).status_code == 403
    assert client.put(f"/api/admin/teacher-applications/{application['id']}", headers=admin_headers, json={"decision": "REJECTED"}).status_code == 409
    directory = client.get("/api/admin/users", headers=admin_headers)
    assert directory.status_code == 200 and len(directory.json()["data"]) == 2
    assert "passwordHash" not in directory.text and "$argon2" not in directory.text


def test_teacher_rejection_and_review_input_validation(auth):
    client, _, _ = auth
    _, admin_headers = administrator(client)
    register(client, "applicant", role="TEACHER")
    application = client.get("/api/admin/teacher-applications", headers=admin_headers).json()["data"][0]
    path = f"/api/admin/teacher-applications/{application['id']}"
    assert client.put(path, headers=admin_headers, json={"decision": "ADMIN"}).status_code == 422
    assert client.put(path, headers=admin_headers, json={"decision": "APPROVED", "role": "ADMIN"}).status_code == 422
    assert client.put(path, headers=admin_headers, json={"decision": "REJECTED", "reason": "资料不完整"}).status_code == 200
    assert login(client, "applicant").status_code == 403
    assert client.put(f"/api/admin/teacher-applications/{uuid4()}", headers=admin_headers, json={"decision": "APPROVED"}).status_code == 404


def test_student_role_cannot_use_management_and_unimplemented_business_stays_pending(auth):
    client, _, _ = auth
    register(client)
    student = headers(login(client))
    for path in ("/api/admin/users", "/api/admin/teacher-applications", "/api/admin/emoji/export", "/api/admin/statistics", "/api/emoji/statistics"):
        assert client.get(path, headers=student).status_code == 403
    assert client.post(f"/api/admin/sessions/{uuid4()}/schedule", headers=student, json={"userIds": []}).status_code == 403
    response = client.get("/api/sessions", headers=student)
    assert response.status_code == 200 and response.json()["data"] == []
    assert client.post("/api/emoji", headers={**student, "Idempotency-Key": "event"}, json={"sessionId": str(uuid4()), "emotion": "HAPPY"}).status_code == 404
    assert client.get("/api/emoji/history", headers=student).json()["data"] == []


def test_session_persistence_across_client_lifespans(auth):
    client, _, _ = auth
    register(client)
    identity = headers(login(client))
    from app.main import app as same_app
    with TestClient(same_app) as restarted:
        assert restarted.get("/api/users/me", headers=identity).status_code == 200
        assert restarted.post("/api/auth/logout", headers=identity).status_code == 200
    assert client.get("/api/users/me", headers=identity).status_code == 401


def test_successful_login_rehashes_older_argon2_parameters(auth):
    client, factory, _ = auth
    register(client)
    with factory.begin() as session:
        user = session.scalar(select(AppUser))
        user.password_hash = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1).hash(PASSWORD)
    assert login(client).status_code == 200
    with factory() as session:
        assert "$m=19456,t=2,p=1$" in session.scalar(select(AppUser)).password_hash


def test_bootstrap_does_not_promote_existing_user_and_is_single_use(auth):
    client, factory, _ = auth
    register(client)
    with pytest.raises(ApiError) as existing:
        accounts.bootstrap_admin(AdminBootstrapRequest(username="student", email="different@example.edu", password=PASSWORD))
    assert existing.value.code == "ACCOUNT_EXISTS"
    with factory() as session:
        assert session.scalar(select(AppUser)).role == Role.STUDENT
    administrator(client)
    with pytest.raises(ApiError) as repeated:
        accounts.bootstrap_admin(AdminBootstrapRequest(username="other-admin", email="other-admin@example.edu", password=PASSWORD))
    assert repeated.value.code == "ADMIN_ALREADY_EXISTS"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AppUser).where(AppUser.role == Role.ADMIN)) == 1


def test_concurrent_bootstrap_creates_only_one_admin(auth):
    _, factory, _ = auth
    def create(index):
        try:
            accounts.bootstrap_admin(AdminBootstrapRequest(username=f"admin{index}", email=f"admin{index}@example.edu", password=PASSWORD))
            return True
        except ApiError as error:
            assert error.code == "ADMIN_ALREADY_EXISTS"
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(create, range(2))) == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "ADMIN_BOOTSTRAP")) == 1


def test_concurrent_review_allows_only_one_decision(auth):
    client, factory, _ = auth
    _, admin_headers = administrator(client)
    register(client, "applicant", role="TEACHER")
    application = client.get("/api/admin/teacher-applications", headers=admin_headers).json()["data"][0]
    def review(decision):
        return client.put(f"/api/admin/teacher-applications/{application['id']}", headers=admin_headers, json={"decision": decision}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(review, ["APPROVED", "REJECTED"])) == [200, 409]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action.like("TEACHER_APPLICATION_%"), AuditLog.action != "TEACHER_APPLICATION_SUBMIT")) == 1


def test_audit_failure_rolls_back_account_and_does_not_leak_credentials(auth):
    client, factory, database = auth
    with database.begin() as connection:
        connection.exec_driver_sql("CREATE FUNCTION reject_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private database failure'; END $$; CREATE TRIGGER reject_audit BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION reject_audit();")
    response = register(client)
    assert response.status_code == 500
    assert PASSWORD not in response.text and "private database failure" not in response.text
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AppUser)) == 0


def test_cli_initialization_and_repeated_failure_never_echo_password(auth):
    client, _, database = auth
    env = {**os.environ, "PYTHONPATH": "services/backend", "MOOD_DATABASE_URL": database.url.render_as_string(hide_password=False)}
    command = [sys.executable, "-m", "app.cli.bootstrap_admin", "--username", "admin", "--email", "admin@example.edu", "--password-stdin"]
    first = subprocess.run(command, input=PASSWORD + "\n", env=env, cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert first.returncode == 0, first.stderr
    assert PASSWORD not in first.stdout + first.stderr
    assert login(client, "admin").status_code == 200
    repeated = subprocess.run(command, input=PASSWORD + "\n", env=env, cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert repeated.returncode == 1 and "已存在管理员" in repeated.stderr
    assert PASSWORD not in repeated.stdout + repeated.stderr


def test_password_salts_and_malformed_hashes():
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)
    assert first != second
    assert verify_password(PASSWORD, first)
    assert not verify_password("wrong-password", first)
    assert not verify_password(PASSWORD, "legacy-placeholder")
    assert not verify_password(PASSWORD, None)


def test_login_racing_password_change_cannot_leave_old_password_session_active(auth, monkeypatch):
    client, _, database = auth
    register(client)
    current = login(client)
    principal = accounts.authenticate(current.json()["data"]["token"])
    verified, release = Event(), Event()
    original = accounts.verify_password

    def delayed_verification(password, password_hash):
        valid = original(password, password_hash)
        if not verified.is_set():
            verified.set()
            assert release.wait(5)
        return valid

    monkeypatch.setattr(accounts, "verify_password", delayed_verification)
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        old_login = pool.submit(accounts.login, LoginRequest(username="student", password=PASSWORD))
        assert verified.wait(5)
        changed = pool.submit(accounts.change_password, principal, PasswordRequest(oldPassword=PASSWORD, newPassword=NEW_PASSWORD))
        # 真实数据库应阻塞改密写入，直至在途登录事务提交，然后撤销该登录。
        blocked = False
        for _ in range(100):
            with database.connect() as connection:
                blocked = connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock')"))
            if blocked:
                break
            time.sleep(0.01)
        assert blocked
        release.set()
        issued = old_login.result(timeout=10)
        changed.result(timeout=10)
    finally:
        release.set()
        pool.shutdown(wait=True)
    assert client.get("/api/users/me", headers={"Authorization": "Bearer " + issued.token}).status_code == 401
    assert login(client).status_code == 401
    assert login(client, password=NEW_PASSWORD).status_code == 200


def test_approval_audit_failure_rolls_back_role_grant(auth):
    client, factory, database = auth
    _, admin_headers = administrator(client)
    register(client, "applicant", role="TEACHER")
    application = client.get("/api/admin/teacher-applications", headers=admin_headers).json()["data"][0]
    with database.begin() as connection:
        connection.exec_driver_sql("CREATE FUNCTION reject_approval_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action = 'TEACHER_APPLICATION_APPROVE' THEN RAISE EXCEPTION 'private approval failure'; END IF; RETURN NEW; END $$; CREATE TRIGGER reject_approval_audit BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION reject_approval_audit();")
    response = client.put(f"/api/admin/teacher-applications/{application['id']}", headers=admin_headers, json={"decision": "APPROVED"})
    assert response.status_code == 500
    assert "private approval failure" not in response.text
    with factory() as session:
        assert session.scalar(select(AppUser).where(AppUser.username == "applicant")).role == Role.STUDENT
        assert session.scalar(select(TeacherApplication)).status == "PENDING"
    assert login(client, "applicant").status_code == 403


def test_password_audit_failure_rolls_back_hash_and_revocation(auth):
    client, _, database = auth
    register(client)
    identity = login(client)
    with database.begin() as connection:
        connection.exec_driver_sql("CREATE FUNCTION reject_password_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action = 'AUTH_PASSWORD_CHANGE' THEN RAISE EXCEPTION 'private password failure'; END IF; RETURN NEW; END $$; CREATE TRIGGER reject_password_audit BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION reject_password_audit();")
    response = client.put("/api/auth/password", headers=headers(identity), json={"oldPassword": PASSWORD, "newPassword": NEW_PASSWORD})
    assert response.status_code == 500 and NEW_PASSWORD not in response.text
    assert client.get("/api/users/me", headers=headers(identity)).status_code == 200
    assert login(client).status_code == 200
    assert login(client, password=NEW_PASSWORD).status_code == 401


def test_cli_validates_input_and_hides_unrecognized_sensitive_arguments(auth, monkeypatch, capsys):
    _, factory, _ = auth
    from app.cli import bootstrap_admin
    base = ["--username", "admin", "--email", "admin@example.edu"]
    monkeypatch.setattr(sys, "stdin", io.StringIO("short\n"))
    assert bootstrap_admin.main([*base, "--password-stdin"]) == 1
    assert "short" not in capsys.readouterr().err
    monkeypatch.setattr(sys, "stdin", io.StringIO(PASSWORD + "\n"))
    assert bootstrap_admin.main(base) == 1
    assert "--password-stdin" in capsys.readouterr().err
    with pytest.raises(SystemExit) as error:
        bootstrap_admin.main([*base, "--password", PASSWORD])
    assert error.value.code == 2
    assert PASSWORD not in capsys.readouterr().err
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AppUser)) == 0


def test_invalid_password_change_and_database_unavailability(auth, monkeypatch):
    client, _, _ = auth
    register(client)
    identity = login(client)
    response = client.put("/api/auth/password", headers=headers(identity), json={"oldPassword": PASSWORD, "newPassword": PASSWORD})
    assert response.status_code == 422 and PASSWORD not in response.text
    close_database()
    get_settings.cache_clear()
    monkeypatch.setenv("MOOD_DATABASE_URL", "postgresql+psycopg://test:private-password@127.0.0.1:1/unavailable")
    unavailable = login(client)
    assert unavailable.status_code == 503
    assert "private-password" not in unavailable.text
