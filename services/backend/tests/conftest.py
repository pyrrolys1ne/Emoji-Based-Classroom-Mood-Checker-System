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
