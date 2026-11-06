from concurrent.futures import ThreadPoolExecutor
import json
import os
import socket as network_socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import httpx
from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosedError, InvalidStatus
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app.core.config import get_settings
from app.core.errors import ApiError
from app.db.models import AppUser, ClassSession, Course, EmojiRecord, WsTicket
from app.services import accounts, realtime
from app.services.accounts import token_digest

ORIGIN = {"Origin": "http://127.0.0.1:5173"}


@pytest.fixture
def classrooms(actors, monkeypatch):
    monkeypatch.setattr(get_settings(), "realtime_poll_seconds", 0.02)
    result = []
    for teacher in ("teacher-a", "teacher-b"):
        course = actors["client"].post("/api/admin/courses", headers=actors["headers"]["admin"],
            json={"name": teacher + "课程", "teacherId": actors["users"][teacher]["id"]}).json()["data"]
        now = datetime.now(timezone.utc)
        response = actors["client"].post("/api/admin/sessions", headers=actors["headers"]["admin"], json={
            "courseId": course["id"], "startsAt": (now - timedelta(minutes=5)).isoformat(),
            "endsAt": (now + timedelta(minutes=30)).isoformat(), "room": "101", "className": "测试班"})
        assert response.status_code == 200, response.text
        result.append(response.json()["data"])
    return result


def ticket(data, name="teacher-a"):
    response = data["client"].post("/api/auth/ws-ticket", headers=data["headers"][name])
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    return response.json()["data"]["ticket"]


def principal(data, name="teacher-a"):
    return accounts.authenticate(data["headers"][name]["Authorization"].split()[1])


def add_record(data, classroom, *, simulated=False, source="MANUAL", recorded_at=None):
    with data["factory"].begin() as session:
        record = EmojiRecord(session_id=UUID(classroom["id"]),
            user_id=UUID(data["users"]["student-a"]["id"]) if source == "MANUAL" else None,
            emotion="HAPPY", source=source, recorded_at=recorded_at or datetime.now(timezone.utc),
            confidence=0.9 if source == "AI" else None, device_id="synthetic-camera" if source == "AI" else None,
            simulated=simulated)
        session.add(record)
        session.flush()
        return str(record.id)


def test_ticket_is_short_lived_hashed_and_single_use(actors):
    value = ticket(actors)
    assert value.startswith("wst_") and len(value) == 47
    with actors["factory"]() as session:
        saved = session.scalar(select(WsTicket).where(WsTicket.token_hash == token_digest(value)))
        assert saved.token_hash != value and saved.consumed_at is None
        assert timedelta(0) < saved.expires_at - saved.created_at <= timedelta(seconds=30)
    assert realtime.consume_ticket(value).user.id == UUID(actors["users"]["teacher-a"]["id"])
    with pytest.raises(ApiError):
        realtime.consume_ticket(value)


def test_ticket_role_authentication_and_expiry_boundary(actors, monkeypatch):
    for who in ("student-a", "student-b"):
        assert actors["client"].post("/api/auth/ws-ticket", headers=actors["headers"][who]).status_code == 403
    assert actors["client"].post("/api/auth/ws-ticket").status_code == 401
    value = ticket(actors)
    with actors["factory"]() as session:
        saved = session.scalar(select(WsTicket).where(WsTicket.token_hash == token_digest(value)))
        expiry = saved.expires_at
    monkeypatch.setattr(realtime, "utc_now", lambda: expiry)
    with pytest.raises(ApiError):
        realtime.consume_ticket(value)


def test_concurrent_consumption_accepts_once(actors):
    value = ticket(actors)
    def consume(_):
        try:
            realtime.consume_ticket(value)
            return True
        except ApiError:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(consume, range(6))) == 1


@pytest.mark.parametrize("origin", [None, "null", "https://untrusted.example", "http://127.0.0.1:5173/"])
def test_origin_rejection_does_not_consume_ticket(actors, origin):
    value = ticket(actors)
    with pytest.raises(WebSocketDisconnect) as error:
        with actors["client"].websocket_connect("/ws/dashboard?ticket=" + value, headers={"Origin": origin} if origin else {}):
            pass
    assert error.value.code == 1008
    assert realtime.consume_ticket(value).user.role == "TEACHER"


def test_socket_rejects_bearer_urls_extra_parameters_and_client_messages(actors):
    for query in ("", "token=" + actors["headers"]["admin"]["Authorization"].split()[1],
        "ticket=" + ticket(actors) + "&token=forbidden", "ticket=" + ticket(actors) + "&ticket=" + ticket(actors),
        "ticket=" + ticket(actors) + "&session_id=" + str(uuid4())):
        with pytest.raises(WebSocketDisconnect):
            with actors["client"].websocket_connect("/ws/dashboard?" + query, headers=ORIGIN):
                pass
    with actors["client"].websocket_connect("/ws/dashboard?ticket=" + ticket(actors), headers=ORIGIN) as socket:
        socket.receive_json()
        socket.send_text('{"role":"ADMIN"}')
        with pytest.raises(WebSocketDisconnect) as error:
            while True:
                socket.receive_json()
        assert error.value.code == 1008


def test_scoped_events_metadata_and_rollback(actors, classrooms):
    teacher_a, teacher_b = principal(actors), principal(actors, "teacher-b")
    before_a, before_b = realtime.snapshot(teacher_a), realtime.snapshot(teacher_b)
    first = add_record(actors, classrooms[0])
    changed = realtime.snapshot(teacher_a)
    assert changed.total == 1 and str(changed.latest_id) == first and changed.version != before_a.version
    assert realtime.snapshot(teacher_b) == before_b
    with actors["factory"].begin() as session:
        session.get(ClassSession, UUID(classrooms[0]["id"])).room = "202"
    metadata = realtime.snapshot(teacher_a)
    assert metadata.total == changed.total and metadata.latest_id == changed.latest_id and metadata.version != changed.version
    with pytest.raises(RuntimeError):
        with actors["factory"].begin() as session:
            session.get(ClassSession, UUID(classrooms[0]["id"])).room = "回滚教室"
            session.flush()
            raise RuntimeError("rollback")
    assert realtime.snapshot(teacher_a) == metadata
    assert realtime.snapshot(teacher_b) == before_b


def test_course_roster_and_removed_student_profile_change_versions(actors, classrooms):
    who = principal(actors)
    previous = realtime.snapshot(who)
    with actors["factory"].begin() as session:
        session.get(Course, UUID(classrooms[0]["courseId"])).name = "更正课程"
    assert realtime.snapshot(who).version != previous.version
    previous = realtime.snapshot(who)
    response = actors["client"].post(f"/api/admin/sessions/{classrooms[0]['id']}/schedule",
        headers=actors["headers"]["admin"], json={"userIds": [actors["users"]["student-a"]["id"]]})
    assert response.status_code == 200
    assert realtime.snapshot(who).version != previous.version
    add_record(actors, classrooms[0])
    actors["client"].post(f"/api/admin/sessions/{classrooms[0]['id']}/schedule", headers=actors["headers"]["admin"], json={"userIds": []})
    previous = realtime.snapshot(who)
    with actors["factory"].begin() as session:
        session.get(AppUser, UUID(actors["users"]["student-a"]["id"])).real_name = "历史学生更名"
    assert realtime.snapshot(who).version != previous.version


def test_simulation_is_hidden_and_latest_uses_record_time(actors, classrooms, monkeypatch):
    who = principal(actors)
    before = realtime.snapshot(who)
    add_record(actors, classrooms[0], simulated=True, source="AI")
    assert realtime.snapshot(who) == before
    now = datetime.now(timezone.utc)
    newer = add_record(actors, classrooms[0], recorded_at=now)
    add_record(actors, classrooms[0], recorded_at=now - timedelta(minutes=1))
    assert str(realtime.snapshot(who).latest_id) == newer
    monkeypatch.setattr(get_settings(), "allow_simulated_ai", True)
    assert realtime.snapshot(who).total == 3


@pytest.mark.parametrize("change", ["logout", "password", "disabled", "role", "promoted", "expired"])
def test_active_socket_closes_on_session_or_role_revocation(actors, classrooms, change):
    with actors["client"].websocket_connect("/ws/dashboard?ticket=" + ticket(actors), headers=ORIGIN) as socket:
        event = socket.receive_json()
        assert set(event) == {"type", "total", "latestId", "version"}
        if change == "logout":
            assert actors["client"].post("/api/auth/logout", headers=actors["headers"]["teacher-a"]).status_code == 200
        elif change == "password":
            assert actors["client"].put("/api/auth/password", headers=actors["headers"]["teacher-a"],
                json={"oldPassword": "synthetic-password-2026", "newPassword": "synthetic-new-password"}).status_code == 200
        else:
            who = principal(actors)
            with actors["factory"].begin() as session:
                if change == "disabled":
                    session.get(AppUser, who.user.id).status = "DISABLED"
                elif change == "role":
                    session.get(AppUser, who.user.id).role = "STUDENT"
                elif change == "promoted":
                    session.get(AppUser, who.user.id).role = "ADMIN"
                else:
                    from app.db.models import UserSession
                    session.get(UserSession, who.session_id).expires_at = datetime.now(timezone.utc) - timedelta(microseconds=1)
        with pytest.raises(WebSocketDisconnect) as error:
            while True:
                socket.receive_json()
        assert error.value.code == 1008


def test_logout_only_revokes_current_device_and_unused_ticket(actors):
    first = ticket(actors)
    response = actors["client"].post("/api/auth/login", json={"username": "teacher-a", "password": "synthetic-password-2026"}).json()["data"]
    second_principal = accounts.authenticate(response["token"])
    second = realtime.issue_ticket(second_principal).ticket
    actors["client"].post("/api/auth/logout", headers=actors["headers"]["teacher-a"])
    with pytest.raises(ApiError):
        realtime.consume_ticket(first)
    assert realtime.consume_ticket(second).session_id == second_principal.session_id


def test_http_dashboard_and_explicit_classroom_permission(actors, classrooms):
    first = add_record(actors, classrooms[0])
    add_record(actors, classrooms[1])
    response = actors["client"].get("/api/admin/dashboard/realtime", headers=actors["headers"]["teacher-a"])
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 1 and data["latestId"] == first and len(data["records"]) == 1
    assert actors["client"].get("/api/admin/dashboard/realtime", headers=actors["headers"]["student-a"]).status_code == 403
    assert actors["client"].get("/api/admin/dashboard/realtime", headers=actors["headers"]["teacher-a"], params={"sessionId": classrooms[1]["id"]}).status_code == 403
    assert actors["client"].get("/api/admin/dashboard/realtime", headers=actors["headers"]["admin"], params={"sessionId": str(uuid4())}).status_code == 404
    with pytest.raises(WebSocketDisconnect):
        with actors["client"].websocket_connect("/ws/dashboard?ticket=" + ticket(actors) + "&sessionId=" + classrooms[1]["id"], headers=ORIGIN):
            pass


def test_two_backend_workers_real_ai_service_websocket_and_restart(actors, classrooms, tmp_path):
    root = Path(__file__).resolve().parents[3]
    processes = []

    def port():
        with network_socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            return reserved.getsockname()[1]

    first_port, second_port, ai_port = port(), port(), port()
    backend_env = {**os.environ, "PYTHONPATH": str(root / "services/backend"),
        "MOOD_DATABASE_URL": actors["database"].url.render_as_string(hide_password=False),
        "MOOD_AI_BASE_URL": f"http://127.0.0.1:{ai_port}", "MOOD_ALLOW_SIMULATED_AI": "true",
        "MOOD_REALTIME_POLL_SECONDS": "0.1"}
    ai_env = {**os.environ, "PYTHONPATH": str(root / "services/ai"), "AI_CONTROL_TOKEN": "synthetic-ai-control",
        "AI_SERVICE_TOKEN": "synthetic-ai-service", "AI_BACKEND_URL": f"http://127.0.0.1:{second_port}",
        "AI_OUTBOX_PATH": str(tmp_path / "outbox.sqlite"), "AI_DATA_DIR": str(tmp_path / "samples"), "DEEPSEEK_API_KEY": ""}

    def start(selected_port, env, directory, health):
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(selected_port), "--no-access-log"],
            cwd=directory, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(process)
        for _ in range(120):
            if process.poll() is not None:
                pytest.fail("真实联通测试服务提前退出")
            try:
                if httpx.get(f"http://127.0.0.1:{selected_port}" + health, timeout=0.2).status_code == 200:
                    return process
            except httpx.TransportError:
                pass
            time.sleep(0.05)
        pytest.fail("真实联通测试服务启动超时")

    def stop(process):
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)

    try:
        first = start(first_port, backend_env, root / "services/backend", "/api/ready")
        start(second_port, backend_env, root / "services/backend", "/api/ready")
        start(ai_port, ai_env, root / "services/ai", "/health")
        with httpx.Client(base_url=f"http://127.0.0.1:{first_port}/api", timeout=10) as client, \
            httpx.Client(base_url=f"http://127.0.0.1:{second_port}/api", timeout=10) as writer:
            value = writer.post("/auth/ws-ticket", headers=actors["headers"]["teacher-a"]).json()["data"]["ticket"]
            other = writer.post("/auth/ws-ticket", headers=actors["headers"]["teacher-b"]).json()["data"]["ticket"]
            with connect(f"ws://127.0.0.1:{first_port}/ws/dashboard?ticket={value}", origin=ORIGIN["Origin"], proxy=None) as live, \
                connect(f"ws://127.0.0.1:{first_port}/ws/dashboard?ticket={other}", origin=ORIGIN["Origin"], proxy=None) as restricted:
                assert json.loads(live.recv(timeout=3))["total"] == 0
                initial = json.loads(restricted.recv(timeout=3))
                with pytest.raises(InvalidStatus):
                    with connect(f"ws://127.0.0.1:{second_port}/ws/dashboard?ticket={value}", origin=ORIGIN["Origin"], proxy=None):
                        pass
                inactive = client.get("/admin/ai/status", headers=actors["headers"]["admin"])
                assert inactive.status_code == 200 and inactive.json()["data"]["running"] is False
                response = client.post("/admin/ai/start", headers=actors["headers"]["admin"], json={
                    "sessionId": classrooms[0]["id"], "mode": "simulation", "sampleIntervalSeconds": 0.5})
                assert response.status_code == 200, response.text
                deadline = time.monotonic() + 8
                while True:
                    event = json.loads(live.recv(timeout=3))
                    if event["total"] > 0:
                        break
                    assert time.monotonic() < deadline
                assert json.loads(restricted.recv(timeout=3)) == initial
                assert client.post("/admin/ai/stop", headers=actors["headers"]["admin"]).status_code == 200
                rows = writer.get("/admin/dashboard/realtime", headers=actors["headers"]["teacher-a"]).json()["data"]
                assert rows["total"] >= 1 and all(row["simulated"] and row["userId"] is None for row in rows["records"])
                metadata = client.get("/admin/ai/vision", headers=actors["headers"]["admin"])
                assert metadata.status_code == 200 and metadata.json()["data"]["configured"] is False
                assert "synthetic-ai-control" not in metadata.text and "DEEPSEEK_API_KEY" not in metadata.text
                assert writer.post("/auth/logout", headers=actors["headers"]["teacher-a"]).status_code == 200
                with pytest.raises(ConnectionClosedError) as error:
                    while True:
                        live.recv(timeout=3)
                assert error.value.rcvd.code == 1008
                assert json.loads(restricted.recv(timeout=3)) == initial
            saved = client.post("/auth/ws-ticket", headers=actors["headers"]["teacher-b"]).json()["data"]["ticket"]
            stop(first)
            start(first_port, backend_env, root / "services/backend", "/api/ready")
            with connect(f"ws://127.0.0.1:{first_port}/ws/dashboard?ticket={saved}", origin=ORIGIN["Origin"], proxy=None) as reopened:
                assert json.loads(reopened.recv(timeout=3))["total"] == 0
    finally:
        for process in reversed(processes):
            stop(process)
