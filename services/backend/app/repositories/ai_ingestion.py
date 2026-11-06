import hashlib
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.domain import RecordSource
from app.db.models import AIIngestion, AppUser, AuditLog, ClassSession, Course, EmojiRecord


class AIIngestionRepository:
    def __init__(self, session: Session):
        self.session = session

    def lock_key(self, key: str) -> None:
        # 所有进程按同一键串行，事务完成或回滚自动释放；摘要碰撞只增加等待。
        lock_id = int.from_bytes(hashlib.sha256(("ai-ingestion:" + key).encode()).digest()[:8], signed=True)
        self.session.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})

    def receipt(self, key: str) -> AIIngestion | None:
        return self.session.get(AIIngestion, key)

    def save_receipt(self, key: str, request_hash: str, *, record_id: UUID | None = None) -> AIIngestion:
        result = AIIngestion(
            idempotency_key=key, request_hash=request_hash, record_id=record_id,
            reason="LOW_CONFIDENCE" if record_id is None else None,
        )
        self.session.add(result)
        self.session.flush()
        return result

    def add_record(self, **values) -> EmojiRecord:
        record = EmojiRecord(user_id=None, source=RecordSource.AI, **values)
        self.session.add(record)
        self.session.flush()
        self.session.add(AuditLog(actor_id=None, action="AI_RESULT_ACCEPT", target_id=record.id))
        return record

    def record_row(self, record_id: UUID):
        row = self.session.execute(
            select(EmojiRecord, ClassSession, Course.name, AppUser)
            .join(ClassSession, ClassSession.id == EmojiRecord.session_id)
            .join(Course, Course.id == ClassSession.course_id)
            .join(AppUser, AppUser.id == ClassSession.teacher_id)
            .where(EmojiRecord.id == record_id, EmojiRecord.source == RecordSource.AI)
        ).one()
        return (*row, None)
