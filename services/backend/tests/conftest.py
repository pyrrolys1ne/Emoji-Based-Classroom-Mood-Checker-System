import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.migrate import migrate
from app.db.session import close_database
from app.main import app
from app.schemas.contracts import AdminBootstrapRequest
from app.services import accounts

PASSWORD = "synthetic-password-2026"


@pytest.fixture
def database():
    """在测试服务器创建独立临时库，不清空环境变量指向的数据库。"""
    database_url = os.getenv("MOOD_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("未设置 MOOD_TEST_DATABASE_URL，跳过真实 PostgreSQL 测试")
    url = make_url(database_url)
    name = f"mood_test_{uuid4().hex}"
    admin = create_engine(url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE template0')
    engine = create_engine(url.set(database=name), pool_pre_ping=True, hide_parameters=True)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


@pytest.fixture
def api(database, monkeypatch):
    migrate(database)
    close_database()
    get_settings.cache_clear()
    monkeypatch.setenv("MOOD_DATABASE_URL", database.url.render_as_string(hide_password=False))
    monkeypatch.setenv("MOOD_AI_SERVICE_TOKEN", "synthetic-ai-service")
    monkeypatch.setenv("MOOD_AI_CONTROL_TOKEN", "synthetic-ai-control")
    monkeypatch.setenv("MOOD_USER_SESSION_TTL_SECONDS", "28800")
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, sessionmaker(bind=database, expire_on_commit=False), database
    close_database()
    get_settings.cache_clear()


@pytest.fixture
def actors(api):
    client, factory, database = api
    accounts.bootstrap_admin(AdminBootstrapRequest(username="admin", email="admin@example.edu", password=PASSWORD))
    headers, users = {}, {}

    def login(name):
        response = client.post("/api/auth/login", json={"username": name, "password": PASSWORD})
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        headers[name] = {"Authorization": "Bearer " + data["token"]}
        users[name] = data["user"]

    login("admin")
    for name, role in [("teacher-a", "TEACHER"), ("teacher-b", "TEACHER"), ("student-a", "STUDENT"), ("student-b", "STUDENT")]:
        body = {"username": name, "email": name + "@example.edu", "password": PASSWORD, "role": role, "realName": name + "姓名"}
        if role == "STUDENT":
            body.update(studentNo="20260001" if name.endswith("a") else "20260002", className="测试班")
        assert client.post("/api/auth/register", json=body).status_code == 200
    applications = client.get("/api/admin/teacher-applications", headers=headers["admin"]).json()["data"]
    for application in applications:
        assert client.put(f"/api/admin/teacher-applications/{application['id']}", headers=headers["admin"], json={"decision": "APPROVED"}).status_code == 200
    for name in ("teacher-a", "teacher-b", "student-a", "student-b"):
        login(name)
    return {"client": client, "factory": factory, "database": database, "headers": headers, "users": users}
