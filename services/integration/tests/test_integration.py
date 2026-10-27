from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from integration_app.main import create_app


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setenv("MOOD_AI_SERVICE_TOKEN", "only-service")
    app = create_app(str(tmp_path / "records.sqlite"), testing=True)
    with TestClient(app) as client:

        def login(name):
            response = client.post(
                "/api/auth/login",
                json={"username": name, "password": "integration-only"},
            )
            assert response.status_code == 200
            return {"Authorization": "Bearer " + response.json()["data"]["token"]}

        yield client, login("admin"), login("teacher"), app


def payload(session_id, **kwargs):
    return {
        "sessionId": session_id,
        "emotion": "HAPPY",
        "confidence": 0.9,
        "source": "AI",
        "recordedAt": datetime.now(timezone.utc).isoformat(),
        "deviceId": "simulation-0",
        "simulated": True,
        **kwargs,
    }


def ingest(client, body, key=None):
    return client.post(
        "/api/ai/emoji-results",
        headers={
            "Authorization": "Bearer only-service",
            "Idempotency-Key": key or str(uuid4()),
        },
        json=body,
    )


def test_admin_and_teacher_scope_and_logout(clients):
    client, admin, teacher, _ = clients
    assert client.get("/api/admin/users").status_code == 401
    assert client.get("/api/admin/users", headers=admin).status_code == 200
    assert client.get("/api/admin/users", headers=teacher).status_code == 403
    all_sessions = client.get("/api/sessions", headers=admin).json()["data"]
    teacher_sessions = client.get("/api/sessions", headers=teacher).json()["data"]
    assert len(all_sessions) == 2 and len(teacher_sessions) == 1
    foreign = next(
        item
        for item in all_sessions
        if item["id"] not in {item["id"] for item in teacher_sessions}
    )
    assert (
        client.get(
            "/api/emoji/history", params={"sessionId": foreign["id"]}, headers=teacher
        ).status_code
        == 403
    )
    assert client.post("/api/admin/ai/stop", headers=teacher).status_code == 403
    assert client.get("/api/admin/emoji/export", headers=teacher).status_code == 403
    client.post("/api/auth/logout", headers=teacher)
    assert client.get("/api/users/me", headers=teacher).status_code == 401


def test_ai_ingest_filter_validation_and_idempotency(clients):
    client, admin, _, _ = clients
    session = client.get("/api/sessions", headers=admin).json()["data"][0]
    body = payload(session["id"])
    assert (
        client.post(
            "/api/ai/emoji-results",
            headers={**admin, "Idempotency-Key": "bad-auth"},
            json=body,
        ).status_code
        == 401
    )
    assert (
        ingest(client, payload(session["id"], confidence=0.2)).json()["data"][
            "accepted"
        ]
        is False
    )
    first = ingest(client, body, "same-event").json()["data"]
    repeated = ingest(client, body, "same-event").json()["data"]
    assert first["created"] and not repeated["created"]
    assert first["record"]["id"] == repeated["record"]["id"]
    assert ingest(client, {**body, "emotion": "SAD"}, "same-event").status_code == 409
    assert ingest(client, {**body, "rawImage": "must-not-store"}).status_code == 422
    assert (
        ingest(client, {**body, "recordedAt": "2026-10-27T10:00:00"}).status_code == 422
    )
    assert ingest(client, {**body, "emotion": "unknown"}).status_code == 422
    assert len(client.get("/api/emoji/history", headers=admin).json()["data"]) == 1


def test_durable_store_schedule_and_csv_injection(clients, tmp_path):
    client, admin, teacher, app = clients
    session = client.get("/api/sessions", headers=admin).json()["data"][0]
    assert (
        client.post(
            f"/api/admin/sessions/{session['id']}/schedule",
            headers=teacher,
            json={"userIds": []},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/admin/sessions/{session['id']}/schedule",
            headers=admin,
            json={"userIds": [str(uuid4())]},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/admin/sessions/{session['id']}/schedule",
            headers=admin,
            json={"userIds": []},
        ).status_code
        == 200
    )
    body = payload(session["id"], deviceId='=HYPERLINK("https://example.invalid")')
    assert ingest(client, body).status_code == 200
    csv = client.get("/api/admin/emoji/export", headers=admin)
    assert csv.status_code == 200
    assert "'=HYPERLINK" in csv.text
    app2 = create_app(app.state.store.path, testing=True)
    with TestClient(app2) as second:
        token = second.post(
            "/api/auth/login",
            json={"username": "admin", "password": "integration-only"},
        ).json()["data"]["token"]
        headers = {"Authorization": "Bearer " + token}
        assert (
            len(second.get("/api/emoji/history", headers=headers).json()["data"]) == 1
        )
        assert (
            second.get("/api/sessions", headers=headers).json()["data"][0][
                "scheduledUserIds"
            ]
            == []
        )


def test_statistics_time_bounds_and_websocket_scope(clients):
    client, admin, teacher, _ = clients
    all_sessions = client.get("/api/sessions", headers=admin).json()["data"]
    for session in all_sessions:
        ingest(client, payload(session["id"]))
    assert (
        client.get("/api/admin/statistics", headers=admin).json()["data"]["total"] == 2
    )
    assert (
        client.get("/api/admin/statistics", headers=teacher).json()["data"]["total"]
        == 1
    )
    assert (
        client.get(
            "/api/admin/statistics",
            headers=admin,
            params={"from": "2026-10-27T10:00:00"},
        ).status_code
        == 422
    )
    ticket = client.post("/api/auth/ws-ticket", headers=teacher).json()["data"][
        "ticket"
    ]
    with client.websocket_connect(f"/ws/dashboard?ticket={ticket}") as socket:
        assert socket.receive_json()["total"] == 1
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/dashboard?ticket={ticket}"):
            pass


def test_websocket_rejects_wrong_origin_and_revoked_session(clients):
    from starlette.websockets import WebSocketDisconnect

    client, admin, _, _ = clients
    ticket = client.post("/api/auth/ws-ticket", headers=admin).json()["data"]["ticket"]
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/ws/dashboard?ticket={ticket}",
            headers={"origin": "https://untrusted.invalid"},
        ):
            pass
    ticket = client.post("/api/auth/ws-ticket", headers=admin).json()["data"]["ticket"]
    client.post("/api/auth/logout", headers=admin)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/dashboard?ticket={ticket}"):
            pass


def test_image_analysis_admin_proxy_and_consent(clients, monkeypatch):
    import httpx

    client, admin, teacher, _ = clients
    assert client.get("/api/admin/ai/vision").status_code == 401
    assert client.get("/api/admin/ai/vision", headers=teacher).status_code == 403
    assert (
        client.post(
            "/api/admin/ai/analyze-image",
            headers=teacher,
            json={
                "imageId": "portrait-01",
                "allowRemoteUpload": True,
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/admin/ai/analyze-image",
            headers=admin,
            json={
                "imageId": "portrait-01",
                "allowRemoteUpload": False,
            },
        ).status_code
        == 422
    )
    monkeypatch.setenv("AI_CONTROL_TOKEN", "internal-control")

    async def fake_request(self, method, url, **kwargs):
        assert kwargs["headers"]["Authorization"] == "Bearer internal-control"
        assert self.timeout.read == 40
        assert kwargs["json"] == {"imageId": "portrait-01", "allowRemoteUpload": True}
        return httpx.Response(
            200, json={"code": "OK", "message": "成功", "data": {"faces": []}}
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    response = client.post(
        "/api/admin/ai/analyze-image",
        headers=admin,
        json={
            "imageId": "portrait-01",
            "allowRemoteUpload": True,
        },
    )
    assert response.status_code == 200 and response.json()["data"]["faces"] == []
    assert "internal-control" not in response.text
