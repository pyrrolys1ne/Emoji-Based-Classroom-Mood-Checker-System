from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest
from sqlalchemy import func, select

from app.db.models import AdminInvitation, AppUser, AuditLog
from app.repositories.accounts import AccountsRepository
from app.schemas.contracts import AdminInvitationRequest
from app.services import accounts

PASSWORD = "synthetic-admin-password"


def invitation():
    return accounts.issue_admin_invitation(AdminInvitationRequest()).code


def body(code, username="new-admin"):
    return {"username": username, "email": username + "@example.edu", "password": PASSWORD, "invitationCode": code}


def test_admin_registration_hashes_secrets_consumes_invite_and_can_login(api):
    client, factory, _ = api
    code = invitation()
    response = client.post("/api/auth/admin-register", json=body(code))
    assert response.status_code == 200 and response.json()["data"] is None
    assert response.headers["Cache-Control"] == "no-store"
    assert code not in response.text and PASSWORD not in response.text
    token = client.post("/api/auth/login", json={"username": "new-admin", "password": PASSWORD}).json()["data"]
    assert token["user"]["role"] == "ADMIN"
    assert client.get("/api/admin/users", headers={"Authorization": "Bearer " + token["token"]}).status_code == 200
    with factory() as session:
        invite = session.scalar(select(AdminInvitation))
        user = session.scalar(select(AppUser))
        assert invite.token_hash == accounts.token_digest(code) and invite.token_hash != code
        assert invite.used_at is not None and invite.used_by == user.id
        assert user.password_hash != PASSWORD and accounts.verify_password(PASSWORD, user.password_hash)
        assert set(session.scalars(select(AuditLog.action))) == {"ADMIN_INVITATION_CREATE", "ADMIN_REGISTER", "ADMIN_INVITATION_USE", "AUTH_LOGIN"}
    reused = client.post("/api/auth/admin-register", json=body(code, "another-admin"))
    assert reused.status_code == 403 and reused.json()["code"] == "INVALID_ADMIN_INVITATION"


def test_invalid_and_expired_invites_create_no_accounts(api):
    client, factory, _ = api
    invalid = "adm_" + "x" * 43
    assert client.post("/api/auth/admin-register", json=body(invalid)).status_code == 403
    code = invitation()
    with factory.begin() as session:
        invite = session.scalar(select(AdminInvitation))
        invite.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
        invite.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    expired = client.post("/api/auth/admin-register", json=body(code))
    assert expired.status_code == 403 and code not in expired.text
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AppUser)) == 0
        assert session.scalar(select(AdminInvitation)).used_at is None


def test_duplicate_account_does_not_promote_or_consume_invite(api):
    client, factory, _ = api
    assert client.post("/api/auth/register", json={"username": "student", "email": "student@example.edu", "password": PASSWORD}).status_code == 200
    code = invitation()
    assert client.post("/api/auth/admin-register", json=body(code, "student")).status_code == 409
    with factory() as session:
        assert session.scalar(select(AppUser)).role == "STUDENT"
        assert session.scalar(select(AdminInvitation)).used_at is None
    assert client.post("/api/auth/admin-register", json=body(code)).status_code == 200


def test_concurrent_invite_redemption_creates_exactly_one_admin(api):
    client, factory, _ = api
    code = invitation()
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda n: client.post("/api/auth/admin-register", json=body(code, f"admin-{n}")).status_code, range(2)))
    assert sorted(statuses) == [200, 403]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AppUser)) == 1
        assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "ADMIN_REGISTER")) == 1


def test_audit_failure_rolls_back_account_and_invite(api, monkeypatch):
    client, factory, _ = api
    code = invitation()
    original = AccountsRepository.audit

    def fail(self, action, actor_id, target_id):
        if action == "ADMIN_REGISTER":
            raise RuntimeError("synthetic-audit-failure")
        original(self, action, actor_id, target_id)

    with monkeypatch.context() as patch:
        patch.setattr(AccountsRepository, "audit", fail)
        failed = client.post("/api/auth/admin-register", json=body(code))
        assert failed.status_code == 500 and code not in failed.text and PASSWORD not in failed.text
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AppUser)) == 0
        assert session.scalar(select(AdminInvitation)).used_at is None
    assert client.post("/api/auth/admin-register", json=body(code)).status_code == 200


def test_invitation_issuance_checks_server_role_and_expiration(actors):
    client = actors["client"]
    assert client.post("/api/admin/invitations", json={}).status_code == 401
    for name in ("student-a", "teacher-a"):
        assert client.post("/api/admin/invitations", json={}, headers=actors["headers"][name]).status_code == 403
    headers = actors["headers"]["admin"]
    for hours in (0, 169):
        assert client.post("/api/admin/invitations", json={"expiresInHours": hours}, headers=headers).status_code == 422
    response = client.post("/api/admin/invitations", json={"expiresInHours": 1}, headers=headers)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    data = response.json()["data"]
    assert data["code"].startswith("adm_") and len(data["code"]) == 47
    with actors["factory"]() as session:
        invite = session.scalar(select(AdminInvitation))
        assert str(invite.created_by) == actors["users"]["admin"]["id"]
        assert invite.expires_at - invite.created_at == timedelta(hours=1)


@pytest.mark.parametrize("change", [{"role": "ADMIN"}, {"status": "ACTIVE"}, {"invitationCode": "short"}, {"password": "short"}])
def test_registration_validates_without_echoing_secrets(api, change):
    client, factory, _ = api
    code = invitation()
    response = client.post("/api/auth/admin-register", json={**body(code), **change})
    assert response.status_code == 422 and code not in response.text and PASSWORD not in response.text
    with factory() as session:
        assert session.scalar(select(AdminInvitation)).used_at is None
        assert session.scalar(select(func.count()).select_from(AppUser)) == 0


def test_cli_invitation_can_register_first_admin_and_rejects_invalid_expiry(api):
    client, _, database = api
    root = Path(__file__).resolve().parents[3]
    env = {**os.environ, "PYTHONPATH": "services/backend", "PYTHONIOENCODING": "utf-8",
           "MOOD_DATABASE_URL": database.url.render_as_string(hide_password=False)}
    command = [sys.executable, "-m", "app.cli.create_admin_invite", "--expires-in-hours"]
    issued = subprocess.run([*command, "1"], env=env, cwd=root, text=True, encoding="utf-8", capture_output=True, timeout=20)
    assert issued.returncode == 0
    code = re.search(r"adm_[A-Za-z0-9_-]{43}", issued.stdout).group()
    assert client.post("/api/auth/admin-register", json=body(code)).status_code == 200
    invalid = subprocess.run([*command, "0"], env=env, cwd=root, text=True, encoding="utf-8", capture_output=True, timeout=20)
    assert invalid.returncode == 1 and "1—168" in invalid.stderr
