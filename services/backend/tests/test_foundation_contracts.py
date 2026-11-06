from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.security import require_student, require_user
from app.core.domain import Role, UserStatus
from app.db.migrate import MigrationError, load_migrations
from app.main import app
from app.schemas.contracts import AIResult, Emotion, EmotionStatistics, RegisterRequest, SessionRequest, StatisticsFilters, User
from app.services.accounts import Principal


@pytest.fixture
def authorized_contract_client():
    # 参数合同测试使用独立身份替身，真实认证与权限由 PostgreSQL 接口测试覆盖。
    user = User(id=uuid4(), username="admin", email="admin@example.edu", role=Role.ADMIN, status=UserStatus.ACTIVE)
    app.dependency_overrides[require_user] = lambda: Principal(user, uuid4())
    app.dependency_overrides[require_student] = lambda: Principal(user, uuid4())
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(require_user, None)
        app.dependency_overrides.pop(require_student, None)


def test_identity_fields_and_teacher_application_input():
    request = RegisterRequest(username=" student ", email="student@example.edu", password="private-password", studentNo=" 20260001 ", realName="测试学生", className="测试班")
    assert request.model_dump(by_alias=True)["studentNo"] == "20260001"
    assert request.username == "student"
    with pytest.raises(ValidationError):
        RegisterRequest(username="teacher", email="teacher@example.edu", password="private-password", role="TEACHER", studentNo="20260001")
    with pytest.raises(ValidationError):
        RegisterRequest(username="student", email="not-an-email", password="private-password")


def test_classroom_and_statistics_time_contract():
    common = {"courseId": str(uuid4()), "room": "101", "className": "测试班"}
    with pytest.raises(ValidationError):
        SessionRequest(**common, startsAt="2026-11-06T10:00:00", endsAt="2026-11-06T11:00:00+08:00")
    with pytest.raises(ValidationError):
        SessionRequest(**common, startsAt="2026-11-06T10:00:00+08:00", endsAt="2026-11-06T01:00:00Z")
    assert StatisticsFilters().source == "MANUAL"
    with pytest.raises(ValidationError):
        StatisticsFilters(**{"from": "2026-11-06T10:00:00+08:00", "to": "2026-11-06T02:00:00Z"})
    distribution = {emotion: 0 for emotion in Emotion}
    assert EmotionStatistics(total=0, distribution=distribution).source == "MANUAL"
    with pytest.raises(ValidationError):
        EmotionStatistics(total=1, distribution=distribution)


@pytest.mark.parametrize("path", ["/api/emoji/statistics", "/api/admin/statistics", "/api/admin/emoji/export"])
def test_statistics_and_export_query_validation(authorized_contract_client, path):
    for params in ({"source": "unknown"}, {"from": "2026-11-06T10:00:00"}, {"from": "2026-11-07T00:00:00Z", "to": "2026-11-06T00:00:00Z"}):
        assert authorized_contract_client.get(path, params=params).status_code == 422


def test_manual_idempotency_header_and_cors(authorized_contract_client):
    payload = {"sessionId": str(uuid4()), "emotion": "FOCUSED"}
    assert authorized_contract_client.post("/api/emoji", json=payload).status_code == 422
    parameters = authorized_contract_client.get("/openapi.json").json()["paths"]["/api/emoji"]["post"]["parameters"]
    assert any(item["name"] == "Idempotency-Key" and item["required"] for item in parameters)
    assert authorized_contract_client.post("/api/emoji", json=payload, headers={"Idempotency-Key": "bad key"}).status_code == 422
    response = authorized_contract_client.options("/api/emoji", headers={"Origin": "http://127.0.0.1:5174", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type,idempotency-key"})
    assert response.status_code == 200


def test_ai_payload_rejects_manual_emotions_and_raw_images():
    body = {"sessionId": uuid4(), "emotion": "HAPPY", "confidence": 0.9, "recordedAt": "2026-11-06T10:00:00+08:00", "deviceId": "test-camera"}
    for extra in ({"emotion": "FOCUSED"}, {"emotion": "CONFUSED"}, {"rawImage": "private"}, {"inferenceProvider": "DeepSeek", "confidenceKind": "model_score"}):
        with pytest.raises(ValidationError):
            AIResult(**{**body, **extra})
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()["components"]["schemas"]
        assert set(schema["AIResult"]["properties"]["emotion"]["enum"]) == {"HAPPY", "NEUTRAL", "SAD", "ANGRY", "SURPRISED", "FEAR", "DISGUST"}


def test_configuration_bounds_and_secret_representation():
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://user:private-password@127.0.0.1/test", ai_service_token="private-token")
    assert "private-password" not in repr(settings)
    assert "private-token" not in repr(settings)
    assert settings.allow_simulated_ai is False
    for values in ({"database_url": "sqlite:///local.db"}, {"ws_ticket_ttl_seconds": 31}, {"ai_min_confidence": float("nan")}, {"database_pool_size": 0}, {"ai_base_url": "http://user:password@127.0.0.1:8001"}, {"ai_service_token": "same-token", "ai_control_token": "same-token"}):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **values)


def test_migration_discovery_rejects_gaps(tmp_path):
    (tmp_path / "002_example.sql").write_text("SELECT 1;")
    with pytest.raises(MigrationError, match="版本编号不连续"):
        load_migrations(tmp_path)


def test_migration_checksum_is_portable_across_line_endings(tmp_path):
    path = tmp_path / "001_example.sql"
    path.write_bytes("-- 示例\nSELECT 1;\n".encode("utf-8"))
    unix = load_migrations(tmp_path)[0]
    path.write_bytes(b"\xef\xbb\xbf" + "-- 示例\r\nSELECT 1;\r\n".encode("utf-8"))
    windows = load_migrations(tmp_path)[0]
    assert unix.checksum == windows.checksum
    assert unix.sql == windows.sql
