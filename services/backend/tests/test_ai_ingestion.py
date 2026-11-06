import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.db.migrate import load_migrations, migrate
from app.db.models import AIIngestion, AuditLog, EmojiRecord
from app.services import ai_ingestion

ROOT = Path(__file__).resolve().parents[3]
AI_HEADERS = {"Authorization": "Bearer synthetic-ai-service", "Idempotency-Key": "ai-event"}


@pytest.fixture
def classroom(actors):
    client, headers = actors["client"], actors["headers"]["admin"]
    course = client.post("/api/admin/courses", headers=headers, json={
        "name": "AI 入库测试课程", "teacherId": actors["users"]["teacher-a"]["id"],
    }).json()["data"]
    now = datetime.now(timezone.utc)
    response = client.post("/api/admin/sessions", headers=headers, json={
        "courseId": course["id"], "startsAt": (now - timedelta(hours=2)).isoformat(),
        "endsAt": (now + timedelta(hours=1)).isoformat(), "room": "101", "className": "测试班",
    })
    assert response.status_code == 200, response.text
    return response.json()["data"]


def payload(classroom, **changes):
    return {"sessionId": classroom["id"], "emotion": "HAPPY", "confidence": 0.9,
        "recordedAt": (datetime.fromisoformat(classroom["startsAt"]) + timedelta(minutes=30)).isoformat(),
        "deviceId": "test-camera", **changes}


def ingest(data, body, key="ai-event", headers=None):
    return data["client"].post("/api/ai/emoji-results", json=body,
        headers={**(headers if headers is not None else AI_HEADERS), "Idempotency-Key": key})


def counts(data):
    with data["factory"]() as session:
        return tuple(session.scalar(select(func.count()).select_from(model)) for model in (EmojiRecord, AIIngestion))


def test_seven_emotions_anonymous_persistence_metadata_and_history(actors, classroom):
    for emotion in ("HAPPY", "NEUTRAL", "SAD", "ANGRY", "SURPRISED", "FEAR", "DISGUST"):
        body = payload(classroom, emotion=emotion, inferenceProvider="DeepSeek", confidenceKind="self_reported")
        response = ingest(actors, body, key=emotion)
        assert response.status_code == 200, response.text
        assert response.headers["Cache-Control"] == "no-store"
        result = response.json()["data"]
        assert result["accepted"] is True and result["created"] is True
        record = result["record"]
        assert record["userId"] is None and record["student"] is None and record["source"] == "AI"
        assert record["confidenceKind"] == "self_reported" and record["inferenceProvider"] == "DeepSeek"
        assert datetime.fromisoformat(record["recordedAt"]) == datetime.fromisoformat(body["recordedAt"])
        assert record["classroom"]["teacherId"] == actors["users"]["teacher-a"]["id"]
        assert not {"requestHash", "idempotencyKey", "passwordHash", "token"}.intersection(record)
    assert counts(actors) == (7, 7)
    for who, expected in (("teacher-a", 7), ("teacher-b", 0), ("admin", 7), ("student-a", 0), ("student-b", 0)):
        rows = actors["client"].get("/api/emoji/history", headers=actors["headers"][who]).json()["data"]
        assert len(rows) == expected
    with actors["factory"]() as session:
        assert all(row.device_id == "test-camera" and row.user_id is None for row in session.scalars(select(EmojiRecord)))
        audits = session.scalars(select(AuditLog).where(AuditLog.action == "AI_RESULT_ACCEPT")).all()
        assert len(audits) == 7 and all(row.actor_id is None for row in audits)


def test_ai_token_isolated_from_users_and_control(actors, classroom, monkeypatch):
    for who in actors["headers"]:
        assert ingest(actors, payload(classroom), headers=actors["headers"][who]).status_code == 401
    for token in ("synthetic-ai-control", "fake-token", ""):
        assert ingest(actors, payload(classroom), headers={"Authorization": "Bearer " + token}).status_code == 401
    assert ingest(actors, payload(classroom), headers={}).status_code == 401
    assert actors["client"].get("/api/emoji/history", headers=AI_HEADERS).status_code == 401
    monkeypatch.setattr(get_settings(), "ai_service_token", SecretStr(""))
    response = ingest(actors, payload(classroom))
    assert response.status_code == 503 and counts(actors) == (0, 0)


@pytest.mark.parametrize("change", [
    {"emotion": "FOCUSED"}, {"emotion": "CONFUSED"}, {"emotion": "UNKNOWN"},
    {"confidence": -0.1}, {"confidence": 1.1}, {"confidence": True}, {"confidence": "0.9"},
    {"simulated": "false"}, {"source": "MANUAL"}, {"deviceId": " "},
    {"userId": str(uuid4())}, {"image": "private-frame"}, {"faceEmbedding": [0.1]},
    {"recordedAt": "2026-11-06T00:00:00"}, {"inferenceProvider": "Unknown"},
    {"inferenceProvider": "DeepSeek", "confidenceKind": "model_score"},
])
def test_invalid_or_sensitive_payload_is_rejected_without_receipt(actors, classroom, change):
    response = ingest(actors, payload(classroom, **change))
    assert response.status_code == 422, response.text
    assert "private-frame" not in response.text
    assert counts(actors) == (0, 0)


def test_invalid_key_and_nonfinite_score(actors, classroom):
    body = payload(classroom)
    for key in ("", "bad key", "a" * 101):
        assert ingest(actors, body, key=key).status_code == 422
    assert actors["client"].post("/api/ai/emoji-results", json=body, headers={"Authorization": AI_HEADERS["Authorization"]}).status_code == 422
    for value in ("NaN", "Infinity", "-Infinity", "1e309"):
        raw = json.dumps({**body, "confidence": "SCORE"}).replace('"SCORE"', value)
        response = actors["client"].post("/api/ai/emoji-results", content=raw, headers={**AI_HEADERS, "Content-Type": "application/json"})
        assert response.status_code == 422
    assert counts(actors) == (0, 0)


def test_classroom_and_sample_time_are_validated_before_filtering(actors, classroom, monkeypatch):
    for score in (0.1, 0.9):
        assert ingest(actors, payload(classroom, sessionId=str(uuid4()), confidence=score)).status_code == 404
    start, end = datetime.fromisoformat(classroom["startsAt"]), datetime.fromisoformat(classroom["endsAt"])
    # 有效采样可以课后补传；时间区间仍为起点包含、终点不包含。
    monkeypatch.setattr(ai_ingestion, "utc_now", lambda: end + timedelta(days=1))
    for index, (sample, expected) in enumerate(((start - timedelta(microseconds=1), 409), (start, 200), (end - timedelta(microseconds=1), 200), (end, 409))):
        assert ingest(actors, payload(classroom, recordedAt=sample.isoformat()), key=f"boundary-{index}").status_code == expected
    monkeypatch.setattr(ai_ingestion, "utc_now", lambda: start)
    assert ingest(actors, payload(classroom), key="future").json()["code"] == "INVALID_RECORD_TIME"
    assert counts(actors) == (2, 2)


def test_threshold_boundary_and_durable_filtered_receipt(actors, classroom, monkeypatch):
    body = payload(classroom, confidence=0.499999)
    result = ingest(actors, body).json()["data"]
    assert result == {"accepted": False, "reason": "LOW_CONFIDENCE"}
    assert counts(actors) == (0, 1)
    monkeypatch.setattr(get_settings(), "ai_min_confidence", 0.1)
    assert ingest(actors, body).json()["data"] == result
    assert ingest(actors, {**body, "confidence": 0.9}).status_code == 409
    monkeypatch.setattr(get_settings(), "ai_min_confidence", 0.5)
    for score in (0.5, 1):
        result = ingest(actors, payload(classroom, confidence=score), key=str(score)).json()["data"]
        assert result["accepted"] is True and result["created"] is True
    monkeypatch.setattr(get_settings(), "ai_min_confidence", 1)
    assert ingest(actors, payload(classroom, confidence=0.5), key="0.5").json()["data"]["created"] is False
    assert counts(actors) == (2, 3)


def test_normalized_payload_replays_and_every_content_change_conflicts(actors, classroom):
    body = payload(classroom)
    original = ingest(actors, body).json()["data"]["record"]
    normalized = {**body, "sessionId": body["sessionId"].upper(), "source": "AI", "simulated": False,
        "inferenceProvider": None, "confidenceKind": None, "deviceId": " test-camera ",
        "recordedAt": datetime.fromisoformat(body["recordedAt"]).astimezone(timezone(timedelta(hours=8))).isoformat()}
    replay = ingest(actors, normalized).json()["data"]
    assert replay == {"accepted": True, "created": False, "record": original}
    for change in ({"sessionId": str(uuid4())}, {"emotion": "SAD"}, {"confidence": 0.8},
        {"confidence": 0.1}, {"deviceId": "other-camera"}, {"recordedAt": classroom["startsAt"]},
        {"inferenceProvider": "DeepFace", "confidenceKind": "model_score"}, {"confidenceKind": "model_score"}):
        response = ingest(actors, {**body, **change})
        assert response.status_code == 409 and response.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert counts(actors) == (1, 1)


def test_simulation_default_rejection_and_history_isolation(actors, classroom, monkeypatch):
    body = payload(classroom, simulated=True)
    response = ingest(actors, body)
    assert response.status_code == 403 and response.json()["code"] == "SIMULATED_AI_DISABLED"
    assert counts(actors) == (0, 0)
    monkeypatch.setattr(get_settings(), "allow_simulated_ai", True)
    assert ingest(actors, body).json()["data"]["record"]["simulated"] is True
    assert ingest(actors, {**body, "simulated": False}).status_code == 409
    monkeypatch.setattr(get_settings(), "allow_simulated_ai", False)
    assert ingest(actors, body).status_code == 403
    assert actors["client"].get("/api/emoji/history", headers=actors["headers"]["teacher-a"]).json()["data"] == []
    monkeypatch.setattr(get_settings(), "allow_simulated_ai", True)
    assert len(actors["client"].get("/api/emoji/history", headers=actors["headers"]["teacher-a"]).json()["data"]) == 1


@pytest.mark.parametrize("filtered,different", [(False, False), (False, True), (True, False), (True, True)])
def test_concurrent_idempotency_for_accepted_and_filtered(actors, classroom, filtered, different):
    def send(index):
        return ingest(actors, payload(classroom, confidence=0.1 if filtered else 0.9,
            emotion="SAD" if different and index % 2 else "HAPPY"))
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(send, range(8)))
    assert all(r.status_code in (200, 409) for r in responses)
    assert sum(r.status_code == 409 for r in responses) == (4 if different else 0)
    results = [r.json()["data"] for r in responses if r.status_code == 200]
    assert counts(actors) == (0 if filtered else 1, 1)
    if not filtered:
        assert sum(r["created"] for r in results) == 1
        assert len({r["record"]["id"] for r in results}) == 1


def test_audit_and_receipt_failures_roll_back_and_release_key(actors, classroom):
    with actors["database"].begin() as connection:
        connection.exec_driver_sql("CREATE FUNCTION reject_ai_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action = 'AI_RESULT_ACCEPT' THEN RAISE EXCEPTION 'private-ai-audit'; END IF; RETURN NEW; END $$; CREATE TRIGGER reject_ai_audit BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION reject_ai_audit();")
    response = ingest(actors, payload(classroom))
    assert response.status_code == 500 and "private-ai-audit" not in response.text
    assert counts(actors) == (0, 0)
    with actors["database"].begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER reject_ai_audit ON audit_log; CREATE FUNCTION reject_ai_receipt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private-ai-receipt'; END $$; CREATE TRIGGER reject_ai_receipt BEFORE INSERT ON ai_ingestion FOR EACH ROW EXECUTE FUNCTION reject_ai_receipt();")
    for score in (0.1, 0.9):
        response = ingest(actors, payload(classroom, confidence=score))
        assert response.status_code == 500 and "private-ai-receipt" not in response.text
        assert counts(actors) == (0, 0)
    with actors["database"].begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER reject_ai_receipt ON ai_ingestion")
    assert ingest(actors, payload(classroom)).json()["data"]["created"] is True
    assert counts(actors) == (1, 1)


def test_manual_and_ai_request_keys_have_separate_namespaces(actors, classroom):
    assert actors["client"].post(f"/api/admin/sessions/{classroom['id']}/schedule", headers=actors["headers"]["admin"], json={"userIds": [actors["users"]["student-a"]["id"]]}).status_code == 200
    manual = actors["client"].post("/api/emoji", headers={**actors["headers"]["student-a"], "Idempotency-Key": "ai-event"}, json={"sessionId": classroom["id"], "emotion": "FOCUSED"})
    assert manual.status_code == 200
    assert ingest(actors, payload(classroom)).status_code == 200
    assert counts(actors) == (2, 1)


def test_upgrade_backfills_only_existing_keyed_ai_records(database, tmp_path):
    directory = ROOT / "infra/database"
    for item in load_migrations(directory)[:5]:
        (tmp_path / item.name).write_text(item.sql)
    migrate(database, tmp_path)
    with database.begin() as connection:
        teacher = connection.scalar(text("INSERT INTO app_user(username,password_hash,email,role) VALUES ('teacher','synthetic-hash','teacher@example.edu','TEACHER') RETURNING id"))
        course = connection.scalar(text("INSERT INTO course(name,teacher_id) VALUES ('AI 课程',:teacher) RETURNING id"), {"teacher": teacher})
        classroom = connection.scalar(text("INSERT INTO class_session(course_id,teacher_id,starts_at,ends_at,room,class_name) VALUES (:course,:teacher,now(),now()+interval '1 hour','101','测试班') RETURNING id"), {"course": course, "teacher": teacher})
        record = connection.scalar(text("INSERT INTO emoji_record(session_id,emotion,source,confidence,device_id,idempotency_key,request_hash) VALUES (:classroom,'HAPPY','AI',0.9,'test-camera','existing-key',:hash) RETURNING id"), {"classroom": classroom, "hash": "a" * 64})
        connection.execute(text("INSERT INTO emoji_record(session_id,user_id,emotion,source,idempotency_key,request_hash) VALUES (:classroom,:teacher,'HAPPY','MANUAL','existing-key',:hash)"), {"classroom": classroom, "teacher": teacher, "hash": "b" * 64})
        connection.execute(text("INSERT INTO emoji_record(session_id,emotion,source,confidence,device_id) VALUES (:classroom,'SAD','AI',0.8,'legacy-camera')"), {"classroom": classroom})
    assert migrate(database, directory) == ["006"]
    with database.connect() as connection:
        assert connection.execute(text("SELECT idempotency_key,request_hash,record_id,reason FROM ai_ingestion")).one() == ("existing-key", "a" * 64, record, None)
        assert connection.scalar(text("SELECT count(*) FROM emoji_record")) == 3
    assert migrate(database, directory) == []


def test_same_key_across_classrooms_is_serialized(actors, classroom):
    second = actors["client"].post("/api/admin/sessions", headers=actors["headers"]["admin"], json={
        "courseId": classroom["courseId"], "teacherId": actors["users"]["teacher-b"]["id"],
        "startsAt": classroom["startsAt"], "endsAt": classroom["endsAt"], "room": "102", "className": "其他班",
    }).json()["data"]
    def send(index):
        return ingest(actors, payload(second if index % 2 else classroom))
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(send, range(8)))
    assert sorted(r.status_code for r in results) == [200] * 4 + [409] * 4
    assert counts(actors) == (1, 1)


def test_real_ai_outbox_delivery_lost_response_and_backend_restart(actors, classroom, tmp_path):
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    backend_env = {**os.environ, "MOOD_DATABASE_URL": actors["database"].url.render_as_string(hide_password=False),
        "MOOD_ALLOW_SIMULATED_AI": "true"}
    base = f"http://127.0.0.1:{port}"

    def start():
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--no-access-log"],
            env=backend_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    pytest.fail("测试后端提前退出")
                try:
                    if httpx.get(base + "/api/ready", timeout=0.2).status_code == 200:
                        return process
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            pytest.fail("测试后端启动超时")
        except BaseException:
            process.terminate()
            process.wait(timeout=10)
            raise

    def stop(process):
        process.terminate()
        process.wait(timeout=10)

    # 独立 AI 进程使用真实队列和 HTTP，只替换采样输入，不运行模型或摄像头。
    script = '''
import json, os
import httpx
from app.pipeline import Prediction, map_predictions
from app.runner import Runner
runner = Runner(os.environ["AI_OUTBOX_PATH"])
if os.environ["AI_TEST_PHASE"] == "lost":
    config = json.loads(os.environ["AI_TEST_PAYLOAD"])
    results, filtered = map_predictions([Prediction("happy", 0.9, "DeepSeek", "self_reported")],
        session_id=config["sessionId"], device_id=config["deviceId"], threshold=0.5,
        recorded_at=config["recordedAt"], simulated=True)
    assert filtered == 0 and len(results) == 1
    runner.outbox.put(results[0])
    with httpx.Client(timeout=10, trust_env=False) as client:
        class LostResponse:
            def post(self, *args, **kwargs):
                response = client.post(*args, **kwargs)
                assert response.status_code == 200
                assert response.json()["data"]["created"] is True
                raise httpx.ReadError("synthetic-lost-response")
        assert runner.send_one(LostResponse()) is False
    assert runner.outbox.count() == 1
else:
    assert runner.outbox.count() == 1
    with httpx.Client(timeout=10, trust_env=False) as client:
        assert runner.send_one(client) is True
    assert runner.outbox.count() == 0 and runner.status()["submitted"] == 1
'''
    ai_env = {**os.environ, "PYTHONPATH": str(ROOT / "services/ai"), "AI_BACKEND_URL": base,
        "AI_SERVICE_TOKEN": "synthetic-ai-service", "AI_OUTBOX_PATH": str(tmp_path / "outbox.sqlite"),
        "AI_TEST_PAYLOAD": json.dumps(payload(classroom)), "AI_TEST_PHASE": "lost"}
    process = start()
    try:
        first = subprocess.run([sys.executable, "-c", script], cwd=ROOT / "services/ai", env=ai_env, text=True, capture_output=True, timeout=20)
        assert first.returncode == 0, first.stderr
        assert counts(actors) == (1, 1)
        with httpx.Client(base_url=base + "/api", timeout=10) as client:
            rows = client.get("/emoji/history", headers=actors["headers"]["teacher-a"]).json()["data"]
            assert len(rows) == 1 and rows[0]["simulated"] is True and rows[0]["confidenceKind"] == "self_reported"
            assert client.get("/emoji/history", headers=actors["headers"]["teacher-b"]).json()["data"] == []
            low = client.post("/ai/emoji-results", headers={**AI_HEADERS, "Idempotency-Key": "filtered-restart"}, json=payload(classroom, confidence=0.1))
            assert low.json()["data"] == {"accepted": False, "reason": "LOW_CONFIDENCE"}
            stop(process)
            process = None
            backend_env["MOOD_AI_MIN_CONFIDENCE"] = "0"
            process = start()
            second = subprocess.run([sys.executable, "-c", script], cwd=ROOT / "services/ai", env={**ai_env, "AI_TEST_PHASE": "retry"}, text=True, capture_output=True, timeout=20)
            assert second.returncode == 0, second.stderr
            assert counts(actors) == (1, 2)
            assert client.get("/emoji/history", headers=actors["headers"]["teacher-a"]).json()["data"] == rows
            replay = client.post("/ai/emoji-results", headers={**AI_HEADERS, "Idempotency-Key": "filtered-restart"}, json=payload(classroom, confidence=0.1))
            assert replay.json()["data"] == low.json()["data"]
            assert client.get("/emoji/statistics", headers=actors["headers"]["teacher-a"]).status_code == 501
    finally:
        if process is not None:
            stop(process)
    with actors["factory"]() as session:
        assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "AI_RESULT_ACCEPT")) == 1
