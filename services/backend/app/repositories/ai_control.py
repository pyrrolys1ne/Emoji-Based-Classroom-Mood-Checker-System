from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.repositories.accounts import AccountsRepository


class AIControlRepository:
    def __init__(self, session: Session):
        self.session = session

    def lock_control(self):
        self.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 742031167})

    def audit(self, action: str, actor_id: UUID, operation_id: UUID):
        AccountsRepository(self.session).audit(action, actor_id, operation_id)
