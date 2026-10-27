from app.repositories.health import database_available


def readiness() -> bool:
    return database_available()
