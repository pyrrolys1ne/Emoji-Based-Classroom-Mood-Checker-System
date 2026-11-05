import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool


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
