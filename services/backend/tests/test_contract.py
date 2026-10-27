from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app

client = TestClient(app)


def test_health_and_openapi():
    assert client.get("/api/health").json()["data"]["status"] == "ok"
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/admin/dashboard/realtime" in paths
    assert "/api/ai/emoji-results" in paths


def test_protected_api_rejects_missing_and_unverified_identity():
    assert client.get("/api/admin/users").status_code == 401
    response = client.get("/api/admin/users", headers={"Authorization": "Bearer fake-token"})
    assert response.status_code == 501
    assert response.json()["code"] == "NOT_IMPLEMENTED"


def test_public_register_cannot_create_admin_and_never_echoes_password():
    response = client.post("/api/auth/register", json={"username": "student", "email": "student@example.edu", "password": "private-password", "role": "ADMIN"})
    assert response.status_code == 422
    assert "private-password" not in response.text


def test_valid_login_is_explicitly_unimplemented():
    assert client.post("/api/auth/login", json={"username": "student", "password": "private-password"}).status_code == 501


def test_ai_token_and_payload_validation(monkeypatch):
    monkeypatch.setenv("MOOD_AI_SERVICE_TOKEN", "test-service-only")
    get_settings.cache_clear()
    payload = {"sessionId": str(uuid4()), "emotion": "HAPPY", "confidence": 0.9, "recordedAt": "2026-10-27T09:00:00+08:00", "deviceId": "test-camera"}
    try:
        assert client.post("/api/ai/emoji-results", json=payload).status_code == 401
        headers = {"Authorization": "Bearer test-service-only"}
        assert client.post("/api/ai/emoji-results", headers=headers, json=payload).status_code == 501
        assert client.post("/api/ai/emoji-results", headers=headers, json={**payload, "confidence": 1.1}).status_code == 422
        assert client.post("/api/ai/emoji-results", headers=headers, json={**payload, "recordedAt": "2026-10-27T09:00:00"}).status_code == 422
    finally:
        monkeypatch.delenv("MOOD_AI_SERVICE_TOKEN")
        get_settings.cache_clear()
