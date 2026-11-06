import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from uuid import UUID, uuid4

import pytest
import httpx
from sqlalchemy import delete, func, select

from app.core.config import get_settings
from app.core.domain import Emotion, RecordSource, Role
from app.db.models import AppUser, AuditLog, ClassSession, EmojiRecord, ScheduleUser
from app.repositories.accounts import AccountsRepository
from app.repositories.classrooms import ClassroomsRepository
from app.services import feedback


def classroom(data, *, teacher="teacher-a", students=("student-a", "student-b"), start=None, end=None):
    client, admin = data["client"], data["headers"]["admin"]
    course = client.post("/api/admin/courses", headers=admin, json={
        "name": "反馈测试课程", "teacherId": data["users"][teacher]["id"],
    }).json()["data"]
    now = datetime.now(timezone.utc)
    response = client.post("/api/admin/sessions", headers=admin, json={
        "courseId": course["id"], "startsAt": (start or now - timedelta(minutes=10)).isoformat(),
        "endsAt": (end or now + timedelta(minutes=30)).isoformat(), "room": "101", "className": "反馈测试班",
    })
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert set_roster(data, result, students).status_code == 200
    return result


def set_roster(data, target, students):
    return data["client"].post(f"/api/admin/sessions/{target['id']}/schedule", headers=data["headers"]["admin"],
        json={"userIds": [data["users"][name]["id"] for name in students]})


def submit(data, target, *, who="student-a", key="event", emotion="HAPPY", **extra):
    return data["client"].post("/api/emoji", headers={**data["headers"][who], "Idempotency-Key": key},
        json={"sessionId": target["id"], "emotion": emotion, **extra})


def history(data, who="student-a", **filters):
    return data["client"].get("/api/emoji/history", headers=data["headers"][who], params=filters)


def count(data, model=EmojiRecord):
    with data["factory"]() as session:
        return session.scalar(select(func.count()).select_from(model))


def test_manual_emotions_identity_and_safe_summaries(actors):
    target = classroom(actors)
    for emotion in Emotion:
        response = submit(actors, target, key=emotion, emotion=emotion)
        assert response.status_code == 200, response.text
        assert response.headers["Cache-Control"] == "no-store"
        row = response.json()["data"]
        assert (row["userId"], row["sessionId"], row["source"], row["emotion"]) == (actors["users"]["student-a"]["id"], target["id"], "MANUAL", emotion)
        assert row["confidence"] is None and row["simulated"] is False
        assert row["inferenceProvider"] is None and row["confidenceKind"] is None
        assert row["classroom"]["courseName"] == "反馈测试课程"
        assert row["student"]["realName"] == "student-a姓名"
        assert datetime.fromisoformat(target["startsAt"]) <= datetime.fromisoformat(row["recordedAt"]) < datetime.fromisoformat(target["endsAt"])
        assert not {"idempotencyKey", "requestHash", "deviceId", "email", "passwordHash", "scheduledUserIds"}.intersection(row)
        assert "email" not in json.dumps(row) and "scheduledUserIds" not in json.dumps(row)
    assert count(actors) == len(Emotion)
    with actors["factory"]() as session:
        audits = session.scalars(select(AuditLog).where(AuditLog.action == "EMOJI_MANUAL_SUBMIT")).all()
        assert len(audits) == len(Emotion)
        assert all(a.actor_id == UUID(actors["users"]["student-a"]["id"]) for a in audits)


def test_idempotent_replay_conflicts_new_actions_and_user_namespace(actors, monkeypatch):
    target = classroom(actors)
    first = submit(actors, target).json()["data"]
    assert submit(actors, target).json()["data"] == first
    assert submit(actors, target, emotion="SAD").json()["code"] == "IDEMPOTENCY_CONFLICT"
    other = classroom(actors)
    assert submit(actors, other).status_code == 409
    assert submit(actors, target, key="new-action").json()["data"]["id"] != first["id"]
    assert submit(actors, target, who="student-b").json()["data"]["id"] != first["id"]
    monkeypatch.setattr(feedback, "utc_now", lambda: datetime.fromisoformat(target["endsAt"]))
    assert submit(actors, target).json()["data"] == first
    assert submit(actors, target, key="after-end").json()["code"] == "CLASSROOM_NOT_OPEN"
    assert count(actors) == 3


@pytest.mark.parametrize("offset,expected", [(-1, 409), (0, 200), (599999999, 200), (600000000, 409)])
def test_classroom_half_open_window(actors, monkeypatch, offset, expected):
    start = datetime.now(timezone.utc)
    target = classroom(actors, start=start, end=start + timedelta(minutes=10))
    monkeypatch.setattr(feedback, "utc_now", lambda: start + timedelta(microseconds=offset))
    response = submit(actors, target)
    assert response.status_code == expected, response.text
    assert count(actors) == (1 if expected == 200 else 0)


@pytest.mark.parametrize("field,value", [
    ("userId", str(uuid4())), ("source", "AI"), ("confidence", 0.9), ("deviceId", "camera"),
    ("recordedAt", "2026-11-06T00:00:00Z"), ("simulated", True), ("emotion", "UNKNOWN"),
])
def test_manual_rejects_forged_and_invalid_fields(actors, field, value):
    target = classroom(actors)
    assert submit(actors, target, **{field: value}).status_code == 422
    assert count(actors) == 0


def test_role_membership_and_unknown_classroom(actors):
    target = classroom(actors, students=("student-a",))
    for who in ("admin", "teacher-a", "teacher-b", "student-b"):
        assert submit(actors, target, who=who).status_code == 403
    assert submit(actors, {"id": str(uuid4())}).status_code == 404
    assert actors["client"].post("/api/emoji", json={"sessionId": target["id"], "emotion": "HAPPY"}, headers={"Idempotency-Key": "x"}).status_code == 401
    assert count(actors) == 0


def test_removed_student_keeps_history_and_replay_but_cannot_add(actors):
    target = classroom(actors)
    first = submit(actors, target).json()["data"]
    assert set_roster(actors, target, ()).status_code == 200
    assert actors["client"].get("/api/sessions", headers=actors["headers"]["student-a"]).json()["data"] == []
    assert submit(actors, target).json()["data"] == first
    assert submit(actors, target, key="new").status_code == 403
    for who in ("student-a", "teacher-a", "admin"):
        response = history(actors, who, sessionId=target["id"])
        assert response.status_code == 200 and response.json()["data"] == [first]
    assert history(actors).json()["data"] == [first]
    assert history(actors, "student-b", sessionId=target["id"]).status_code == 403


def test_history_role_scope_and_intersecting_filters(actors):
    a = classroom(actors)
    b = classroom(actors, teacher="teacher-b", students=("student-b",))
    ra = submit(actors, a).json()["data"]
    rb = submit(actors, a, who="student-b").json()["data"]
    rc = submit(actors, b, who="student-b", key="other").json()["data"]
    assert history(actors).json()["data"] == [ra]
    assert {r["id"] for r in history(actors, "student-b").json()["data"]} == {rb["id"], rc["id"]}
    assert {r["id"] for r in history(actors, "teacher-a").json()["data"]} == {ra["id"], rb["id"]}
    assert history(actors, "teacher-b").json()["data"] == [rc]
    assert len(history(actors, "admin").json()["data"]) == 3
    assert history(actors, "teacher-a", sessionId=b["id"]).status_code == 403
    assert history(actors, sessionId=b["id"]).status_code == 403
    assert history(actors, sessionId=str(uuid4())).status_code == 404
    assert history(actors, userId=actors["users"]["student-b"]["id"]).status_code == 403
    assert history(actors, source="AI").status_code == 403
    assert history(actors, "teacher-a", userId=actors["users"]["student-b"]["id"]).json()["data"] == [rb]
    assert history(actors, "teacher-a", course=b["courseId"]).json()["data"] == []
    assert history(actors, course=a["courseId"], **{"class": "反馈测试班"}).json()["data"] == [ra]
    assert history(actors, **{"class": "其他班"}).json()["data"] == []


def test_history_time_range_offset_order_and_no_truncation(actors):
    target = classroom(actors)
    base = datetime(2026, 11, 6, tzinfo=timezone.utc)
    user_id = UUID(actors["users"]["student-a"]["id"])
    # 超过常见页面上限，验证正式接口返回完整授权集合。
    with actors["factory"].begin() as session:
        session.add_all(EmojiRecord(id=UUID(int=i + 1), session_id=UUID(target["id"]), user_id=user_id,
            source=RecordSource.MANUAL, emotion=Emotion.HAPPY, recorded_at=base + timedelta(seconds=i // 2)) for i in range(1102))
    rows = history(actors).json()["data"]
    assert len(rows) == 1102
    assert [r["id"] for r in rows] == [str(UUID(int=i)) for i in range(1102, 0, -1)]
    rows = history(actors, **{"from": "2026-11-06T08:00:00+08:00", "to": "2026-11-06T00:00:01Z"}).json()["data"]
    assert [r["id"] for r in rows] == [str(UUID(int=2)), str(UUID(int=1))]
    for params in ({"from": "2026-11-06T00:00:00"}, {"from": base.isoformat(), "to": base.isoformat()}, {"source": "unknown"}, {"sessionId": "not-uuid"}, {"limit": 1}):
        assert history(actors, **params).status_code == 422


def test_ai_history_stays_anonymous_preserves_score_kind_and_isolates_simulation(actors, monkeypatch):
    target = classroom(actors)
    submit(actors, target)
    with actors["factory"].begin() as session:
        for simulated in (False, True):
            session.add(EmojiRecord(session_id=UUID(target["id"]), user_id=None, source=RecordSource.AI,
                emotion=Emotion.HAPPY, confidence=0.8, device_id="synthetic-camera", simulated=simulated,
                inference_provider="DeepSeek", confidence_kind="self_reported"))
    assert len(history(actors).json()["data"]) == 1
    rows = history(actors, "teacher-a", source="AI").json()["data"]
    assert len(rows) == 1
    assert rows[0]["userId"] is None and rows[0]["student"] is None
    assert rows[0]["confidenceKind"] == "self_reported" and rows[0]["confidence"] == 0.8
    assert len(history(actors, "admin", source="ALL").json()["data"]) == 2
    monkeypatch.setattr(get_settings(), "allow_simulated_ai", True)
    assert len(history(actors, "teacher-a", source="AI").json()["data"]) == 2
    assert len(history(actors).json()["data"]) == 1


@pytest.mark.parametrize("different_payload", [False, True])
def test_concurrent_same_key_creates_one_record_and_audit(actors, different_payload):
    target = classroom(actors)
    def send(index):
        return submit(actors, target, emotion="SAD" if different_payload and index % 2 else "HAPPY")
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(send, range(8)))
    assert all(r.status_code in (200, 409) for r in responses)
    assert len({r.json()["data"]["id"] for r in responses if r.status_code == 200}) == 1
    if different_payload:
        assert sum(r.status_code == 409 for r in responses) == 4
    assert count(actors) == 1
    with actors["factory"]() as session:
        assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "EMOJI_MANUAL_SUBMIT")) == 1


def test_audit_failure_rolls_back_record_and_key_can_retry(actors, monkeypatch):
    target = classroom(actors)
    original = AccountsRepository.audit
    def failed(self, action, *args):
        if action == "EMOJI_MANUAL_SUBMIT":
            raise RuntimeError("synthetic-audit-failure")
        return original(self, action, *args)
    monkeypatch.setattr(AccountsRepository, "audit", failed)
    response = submit(actors, target)
    assert response.status_code == 500 and "synthetic" not in response.text
    assert count(actors) == 0
    monkeypatch.setattr(AccountsRepository, "audit", original)
    assert submit(actors, target).status_code == 200
    assert count(actors) == 1


def test_time_is_sampled_after_classroom_lock_wait(actors, monkeypatch):
    target = classroom(actors)
    entered = Event()
    original = ClassroomsRepository.classroom
    now = [datetime.fromisoformat(target["endsAt"]) - timedelta(seconds=1)]
    monkeypatch.setattr(feedback, "utc_now", lambda: now[0])
    def blocked(self, session_id, *, lock=False):
        if lock:
            entered.set()
        return original(self, session_id, lock=lock)
    monkeypatch.setattr(ClassroomsRepository, "classroom", blocked)
    with actors["factory"].begin() as session:
        session.execute(select(ClassSession).where(ClassSession.id == UUID(target["id"])).with_for_update())
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(submit, actors, target)
            assert entered.wait(5)
            now[0] = datetime.fromisoformat(target["endsAt"])
            session.commit()
            response = future.result(timeout=10)
    assert response.status_code == 409 and count(actors) == 0


def test_logout_revokes_replay_and_history(actors):
    target = classroom(actors)
    assert submit(actors, target).status_code == 200
    assert actors["client"].post("/api/auth/logout", headers=actors["headers"]["student-a"]).status_code == 200
    assert submit(actors, target).status_code == 401
    assert history(actors).status_code == 401
    assert count(actors) == 1


def test_roster_removal_during_classroom_lock_wait_prevents_new_record(actors, monkeypatch):
    target = classroom(actors)
    entered = Event()
    original = ClassroomsRepository.classroom
    def waiting(self, session_id, *, lock=False):
        if lock:
            entered.set()
        return original(self, session_id, lock=lock)
    monkeypatch.setattr(ClassroomsRepository, "classroom", waiting)
    with actors["factory"].begin() as session:
        session.execute(select(ClassSession).where(ClassSession.id == UUID(target["id"])).with_for_update())
        session.execute(delete(ScheduleUser).where(ScheduleUser.session_id == UUID(target["id"])))
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(submit, actors, target)
            assert entered.wait(5)
            session.commit()
            assert pending.result(timeout=10).status_code == 403
    assert count(actors) == 0


@pytest.mark.parametrize("change", ["role", "status", "logout"])
def test_mutation_rechecks_identity_after_authentication(actors, monkeypatch, change):
    target = classroom(actors)
    original = feedback.authorize_actor
    def changed(repo, principal):
        # 身份依赖已通过后改变持久化身份，验证业务事务仍重新检查。
        with actors["factory"].begin() as session:
            if change == "logout":
                AccountsRepository(session).revoke(principal.user.id, datetime.now(timezone.utc))
            else:
                user = session.get(AppUser, principal.user.id)
                if change == "role":
                    user.role = Role.ADMIN
                else:
                    user.status = "DISABLED"
        return original(repo, principal)
    monkeypatch.setattr(feedback, "authorize_actor", changed)
    assert submit(actors, target).status_code == (403 if change == "role" else 401)
    assert count(actors) == 0


def test_http_login_submit_history_and_restart_persistence(actors):
    target = classroom(actors)
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    env = {**os.environ, "MOOD_DATABASE_URL": actors["database"].url.render_as_string(hide_password=False)}

    def start():
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--no-access-log"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    pytest.fail("测试 HTTP 服务提前退出")
                try:
                    if httpx.get(f"http://127.0.0.1:{port}/api/ready", timeout=0.2).status_code == 200:
                        return process
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            pytest.fail("测试 HTTP 服务启动超时")
        except BaseException:
            process.terminate()
            process.wait(timeout=10)
            raise

    def stop(process):
        process.terminate()
        process.wait(timeout=10)

    process = start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}/api", timeout=10) as client:
            login = client.post("/auth/login", json={"username": "student-a", "password": "synthetic-password-2026"})
            assert login.status_code == 200
            headers = {"Authorization": "Bearer " + login.json()["data"]["token"]}
            assert client.get("/sessions", headers=headers).json()["data"][0]["id"] == target["id"]
            body = {"sessionId": target["id"], "emotion": "CONFUSED"}
            write_headers = {**headers, "Idempotency-Key": "restart-feedback"}
            response = client.post("/emoji", headers=write_headers, json=body)
            assert response.status_code == 200
            saved = response.json()["data"]
            stop(process)
            process = None
            process = start()
            assert client.get("/users/me", headers=headers).status_code == 200
            assert client.get("/emoji/history", headers=headers).json()["data"] == [saved]
            assert client.post("/emoji", headers=write_headers, json=body).json()["data"] == saved
            assert client.get("/emoji/history", headers=actors["headers"]["teacher-a"]).json()["data"] == [saved]
            assert client.get("/emoji/history", headers=actors["headers"]["teacher-b"]).json()["data"] == []
            assert client.get("/emoji/statistics", headers=actors["headers"]["teacher-a"]).status_code == 501
            assert client.post("/auth/logout", headers=headers).status_code == 200
            assert client.get("/emoji/history", headers=headers).status_code == 401
    finally:
        if process is not None:
            stop(process)
    assert count(actors) == 1
