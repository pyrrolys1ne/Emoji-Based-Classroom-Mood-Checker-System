from sqlalchemy import create_engine, text

from app.core.config import get_settings


def database_available() -> bool:
    engine = create_engine(get_settings().database_url, connect_args={"connect_timeout": 2})
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()
