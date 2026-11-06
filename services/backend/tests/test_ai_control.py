import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models import AuditLog
from app.services import ai_control


def status(config=None, **changes):
    return {"running": bool(config), "mode": config["mode"] if config else None,
        "modelLoaded": False, "sessionId": config["sessionId"] if config else None,
        "sampled": 0, "submitted": 0, "filtered": 0, "failed": 0, "pending": 0,
        "lastError": None, "lastSubmittedAt": None, "config": config, "apiCalls": 0,
        "lastInferenceMs": None, "lastInferenceAt": None, "lastFaces": [], "stopReason": None, **changes}


def vision(**changes):
    return {"provider": "DeepSeek", "model": "deepseek-flash", "configured": True,
        "confidenceKind": "self_reported", "calibrated": False, "samples": [{"id": "portrait-01",
            "title": "公开样本", "sourceUrl": "https://example.edu/sample", "credit": "公开样本作者",
            "license": "Public domain", "kind": "portrait", "available": True}], **changes}


@pytest.fixture
def classroom(actors):
    admin = actors["headers"]["admin"]
    course = actors["client"].post("/api/admin/courses", headers=admin,
        json={"name": "AI 控制课程", "teacherId": actors["users"]["teacher-a"]["id"]}).json()["data"]
    now = datetime.now(timezone.utc)
    result = actors["client"].post("/api/admin/sessions", headers=admin, json={
        "courseId": course["id"], "startsAt": (now - timedelta(minutes=5)).isoformat(),
        "endsAt": (now + timedelta(minutes=30)).isoformat(), "room": "101", "className": "测试班"})
    assert result.status_code == 200
    return result.json()["data"]


@pytest.fixture
def upstream(monkeypatch):
    calls = []
    state = {"status": status(), "vision": vision(), "handler": None}
    def handler(request):
        calls.append(request)
        if state["handler"]:
            return state["handler"](request)
        path = request.url.path
        if path == "/control/status":
            data = state["status"]
        elif path == "/control/vision":
            data = state["vision"]
        elif path == "/control/start":
            state["status"] = status(json.loads(request.content))
            data = state["status"]
        elif path == "/control/stop":
            state["status"] = status()
            data = state["status"]
        else:
            data = {"imageId": json.loads(request.content)["imageId"], "provider": "DeepSeek",
                "model": "deepseek-flash", "confidenceKind": "self_reported", "calibrated": False,
                "sampleOnly": True, "persisted": False, "elapsedMs": 12,
                "faces": [{"label": "happy", "score": 0.8, "emotion": "HAPPY"}]}
        return httpx.Response(200, json={"code": "OK", "data": data})
    monkeypatch.setattr(ai_control, "control_client", lambda timeout:
        httpx.Client(timeout=timeout, transport=httpx.MockTransport(handler)))
    return state, calls


def request(data, path, *, who="admin", body=None):
    method = "GET" if path in ("status", "vision") else "POST"
    return data["client"].request(method, "/api/admin/ai/" + path, headers=data["headers"][who],
        **({"json": body} if body is not None else {}))


def test_proxy_contract_authentication_and_safe_status(actors, upstream):
    state, calls = upstream
    state["status"]["lastError"] = "private synthetic-ai-control /private/server/path"
    state["status"]["deepseekApiKey"] = "private-deepseek-key"
    response = request(actors, "status")
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert "private" not in response.text and "synthetic-ai-control" not in response.text
    assert response.json()["data"]["lastError"].startswith("AI 任务报告错误")
    assert calls[0].headers["Authorization"] == "Bearer synthetic-ai-control"
    assert "synthetic-ai-service" not in str(calls[0].headers)
    for who in ("teacher-a", "student-a"):
        for path in ("status", "vision", "stop"):
            assert request(actors, path, who=who).status_code == 403
    assert actors["client"].get("/api/admin/ai/status", headers={"Authorization": "Bearer synthetic-ai-control"}).status_code == 401
    assert len(calls) == 1


def test_start_stop_and_remote_camera_parameters_are_forwarded(actors, classroom, upstream):
    state, calls = upstream
    config = {"sessionId": classroom["id"], "mode": "camera-api", "sampleIntervalSeconds": 5,
        "allowRemoteUpload": True, "maxSamples": 2, "maxDurationSeconds": 10}
    response = request(actors, "start", body=config)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["running"] is True
    sent = json.loads(calls[-1].content)
    assert sent["maxSamples"] == 2 and sent["maxDurationSeconds"] == 10 and sent["allowRemoteUpload"] is True
    assert sent["confidenceThreshold"] == 0.75 and sent["cameraIndex"] == 0
    assert request(actors, "stop").json()["data"]["running"] is False
    with actors["factory"]() as session:
        actions = session.scalars(select(AuditLog.action).where(AuditLog.action.like("AI_%"))).all()
        assert sorted(actions) == ["AI_START_REQUEST", "AI_START_SUCCESS", "AI_STOP_REQUEST", "AI_STOP_SUCCESS"]


@pytest.mark.parametrize("changes", [{"allowRemoteUpload": False}, {"allowRemoteUpload": "true"},
    {"sampleIntervalSeconds": 2}, {"maxSamples": 0}, {"maxSamples": 61}, {"maxDurationSeconds": 601},
    {"cameraIndex": -1}, {"confidenceThreshold": True}, {"confidenceThreshold": 1.1},
    {"image": "private-frame"}, {"url": "https://forbidden.example"}])
def test_invalid_remote_configuration_never_calls_upstream(actors, classroom, upstream, changes):
    _, calls = upstream
    config = {"sessionId": classroom["id"], "mode": "camera-api", "allowRemoteUpload": True,
        "sampleIntervalSeconds": 5, **changes}
    response = request(actors, "start", body=config)
    assert response.status_code == 422 and not calls
    assert "private-frame" not in response.text


def test_simulation_and_classroom_scope_are_checked_before_dispatch(actors, classroom, upstream, monkeypatch):
    _, calls = upstream
    assert request(actors, "start", body={"sessionId": classroom["id"]}).status_code == 403
    from uuid import uuid4
    assert request(actors, "start", body={"sessionId": str(uuid4()), "mode": "camera"}).status_code == 404
    monkeypatch.setattr(get_settings(), "allow_simulated_ai", True)
    assert request(actors, "start", body={"sessionId": classroom["id"]}).status_code == 200
    assert len(calls) == 1
    assert request(actors, "stop", body={"image": "forbidden"}).status_code == 422


def test_image_consent_manifest_and_non_persistence(actors, upstream):
    state, calls = upstream
    for body in ({"imageId": "portrait-01", "allowRemoteUpload": False},
        {"imageId": "../private", "allowRemoteUpload": True},
        {"imageId": "portrait-01", "allowRemoteUpload": True, "image": "private"}):
        assert request(actors, "analyze-image", body=body).status_code == 422
    assert not calls
    response = request(actors, "analyze-image", body={"imageId": "portrait-01", "allowRemoteUpload": True})
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["sampleOnly"] is True and result["persisted"] is False and result["calibrated"] is False
    assert result["confidenceKind"] == "self_reported" and result["faces"][0]["emotion"] == "HAPPY"
    assert [call.url.path for call in calls] == ["/control/vision", "/control/analyze-image"]
    calls.clear()
    assert request(actors, "analyze-image", body={"imageId": "unknown", "allowRemoteUpload": True}).status_code == 404
    assert len(calls) == 1
    calls.clear()
    state["vision"]["configured"] = False
    assert request(actors, "analyze-image", body={"imageId": "portrait-01", "allowRemoteUpload": True}).status_code == 503
    assert len(calls) == 1


@pytest.mark.parametrize("status_code,expected", [(401, 502), (403, 502), (409, 409), (422, 422), (429, 429), (503, 502), (302, 502)])
def test_upstream_failures_do_not_expose_private_messages(actors, upstream, status_code, expected):
    state, calls = upstream
    state["handler"] = lambda _: httpx.Response(status_code, json={"code": "ERROR", "message": "private-api-key /private/path"})
    response = request(actors, "status")
    assert response.status_code == expected and "private" not in response.text
    assert len(calls) == 1


@pytest.mark.parametrize("body", [[], {"code": "OK", "data": None},
    {"code": "OK", "data": {**status(), "running": True}},
    {"code": "OK", "data": {**status(), "sampled": -1}},
    {"code": "OK", "data": {**status(), "lastFaces": [{"emotion": "FOCUSED", "score": 0.9}]}},
])
def test_malformed_status_is_rejected(actors, upstream, body):
    state, _ = upstream
    state["handler"] = lambda _: httpx.Response(200, json=body)
    assert request(actors, "status").status_code == 502


def test_control_timeout_retains_intent_and_reports_unknown_without_retry(actors, classroom, upstream):
    state, calls = upstream
    def timeout(_):
        raise httpx.ReadTimeout("private-upstream-details")
    state["handler"] = timeout
    response = request(actors, "start", body={"sessionId": classroom["id"], "mode": "camera"})
    assert response.status_code == 504 and response.json()["code"] == "AI_TIMEOUT"
    assert "private" not in response.text and len(calls) == 1
    with actors["factory"]() as session:
        actions = session.scalars(select(AuditLog.action).where(AuditLog.action.like("AI_START_%"))).all()
        assert sorted(actions) == ["AI_START_REQUEST", "AI_START_UNKNOWN"]


def test_audit_failures_before_and_after_external_operation(actors, classroom, upstream):
    _, calls = upstream
    with actors["database"].begin() as connection:
        connection.exec_driver_sql("CREATE FUNCTION reject_ai_control_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action = 'AI_START_REQUEST' THEN RAISE EXCEPTION 'private audit'; END IF; RETURN NEW; END $$; CREATE TRIGGER reject_ai_control_audit BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION reject_ai_control_audit();")
    assert request(actors, "start", body={"sessionId": classroom["id"], "mode": "camera"}).status_code == 500
    assert not calls
    with actors["database"].begin() as connection:
        connection.exec_driver_sql("CREATE OR REPLACE FUNCTION reject_ai_control_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action = 'AI_START_SUCCESS' THEN RAISE EXCEPTION 'private audit'; END IF; RETURN NEW; END $$;")
    response = request(actors, "start", body={"sessionId": classroom["id"], "mode": "camera"})
    assert response.status_code == 500 and "private" not in response.text and len(calls) == 1
    with actors["factory"]() as session:
        assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "AI_START_REQUEST")) == 1
        assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "AI_START_UNKNOWN")) == 1


@pytest.mark.parametrize("changes", [{"calibrated": True}, {"persisted": True}, {"sampleOnly": False},
    {"imageId": "other-sample"}, {"faces": [{"label": "happy", "score": 0.8, "emotion": "FOCUSED"}]},
    {"faces": [{"label": "sad", "score": 0.8, "emotion": "HAPPY"}]}])
def test_image_result_preserves_sample_and_uncalibrated_semantics(actors, upstream, changes):
    state, calls = upstream
    def handler(request):
        data = vision() if request.url.path == "/control/vision" else {
            "imageId": "portrait-01", "provider": "DeepSeek", "model": "deepseek-flash",
            "confidenceKind": "self_reported", "calibrated": False, "sampleOnly": True,
            "persisted": False, "elapsedMs": 12, "faces": [], **changes}
        return httpx.Response(200, json={"code": "OK", "data": data})
    state["handler"] = handler
    assert request(actors, "analyze-image", body={"imageId": "portrait-01", "allowRemoteUpload": True}).status_code == 502
    assert len(calls) == 2


@pytest.mark.parametrize("secret", ['synthetic-"control', 'synthetic-控制', 'synthetic-\\control'])
def test_nested_credentials_are_rejected_before_json_escaping(actors, upstream, monkeypatch, secret):
    state, _ = upstream
    monkeypatch.setattr(get_settings(), "ai_control_token", SecretStr(secret))
    state["vision"]["samples"][0]["credit"] = "private " + secret
    response = request(actors, "vision")
    assert response.status_code == 502 and "private" not in response.text
