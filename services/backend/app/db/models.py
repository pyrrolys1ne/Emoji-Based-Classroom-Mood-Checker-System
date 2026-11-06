from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, Double, Enum, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.domain import Emotion, RecordSource, Role, UserStatus


class Base(DeclarativeBase):
    pass


class Identity:
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


class AppUser(Identity, Base):
    __tablename__ = "app_user"
    __table_args__ = (
        CheckConstraint("student_no IS NULL OR length(btrim(student_no)) > 0", name="student_no_nonempty"),
        CheckConstraint("real_name IS NULL OR length(btrim(real_name)) > 0", name="real_name_nonempty"),
        CheckConstraint("class_name IS NULL OR length(btrim(class_name)) > 0", name="user_class_nonempty"),
    )
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[Role] = mapped_column(Enum(Role, name="user_role"), server_default=text("'STUDENT'"))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    status: Mapped[UserStatus] = mapped_column(Enum(UserStatus, name="user_status"), server_default=text("'ACTIVE'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    student_no: Mapped[str | None] = mapped_column(String(50), unique=True)
    real_name: Mapped[str | None] = mapped_column(String(100))
    class_name: Mapped[str | None] = mapped_column(String(100))


class Course(Identity, Base):
    __tablename__ = "course"
    name: Mapped[str] = mapped_column(String(150))
    teacher_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))


class ClassSession(Identity, Base):
    __tablename__ = "class_session"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="session_time_order"),
        Index("session_course_time_idx", "course_id", "starts_at"),
        Index("session_teacher_time_idx", "teacher_id", "starts_at"),
    )
    course_id: Mapped[UUID] = mapped_column(ForeignKey("course.id"))
    teacher_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    room: Mapped[str] = mapped_column(String(100))
    class_name: Mapped[str] = mapped_column(String(100))


class ScheduleUser(Identity, Base):
    __tablename__ = "schedule_user"
    __table_args__ = (UniqueConstraint("session_id", "user_id"),)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("class_session.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class ClassroomImport(Identity, Base):
    __tablename__ = "classroom_import"
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class EmojiRecord(Identity, Base):
    __tablename__ = "emoji_record"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint("source <> 'AI' OR confidence IS NOT NULL", name="ai_confidence_required"),
        CheckConstraint("source <> 'MANUAL' OR user_id IS NOT NULL", name="manual_user_required"),
        CheckConstraint("confidence_kind IN ('self_reported', 'model_score')", name="emoji_record_confidence_kind_check"),
        CheckConstraint("inference_provider IS DISTINCT FROM 'DeepSeek' OR confidence_kind IS NOT DISTINCT FROM 'self_reported'", name="deepseek_score_kind"),
        CheckConstraint("(idempotency_key IS NULL AND request_hash IS NULL) OR (idempotency_key IS NOT NULL AND length(btrim(idempotency_key)) > 0 AND request_hash IS NOT NULL AND request_hash ~ '^[0-9a-f]{64}$')", name="record_idempotency_pair"),
        CheckConstraint("source <> 'AI' OR user_id IS NULL", name="ai_anonymous"),
        CheckConstraint("source <> 'AI' OR emotion NOT IN ('FOCUSED', 'CONFUSED')", name="ai_basic_emotion"),
        CheckConstraint("source <> 'AI' OR (device_id IS NOT NULL AND length(btrim(device_id)) > 0)", name="ai_device_required"),
        CheckConstraint("NOT simulated OR source = 'AI'", name="simulated_ai_only"),
        CheckConstraint("inference_provider IS NULL OR inference_provider IN ('DeepSeek', 'DeepFace')", name="inference_provider_known"),
        Index("emoji_ai_idempotency_idx", "idempotency_key", unique=True, postgresql_where=text("source = 'AI' AND idempotency_key IS NOT NULL")),
        Index("emoji_manual_idempotency_idx", "user_id", "idempotency_key", unique=True, postgresql_where=text("source = 'MANUAL' AND idempotency_key IS NOT NULL")),
    )
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("app_user.id"))
    session_id: Mapped[UUID] = mapped_column(ForeignKey("class_session.id"))
    emotion: Mapped[Emotion] = mapped_column(Enum(Emotion, name="emotion_type"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    source: Mapped[RecordSource] = mapped_column(Enum(RecordSource, name="record_source"))
    confidence: Mapped[float | None] = mapped_column(Double)
    device_id: Mapped[str | None] = mapped_column(String(100))
    inference_provider: Mapped[str | None] = mapped_column(String(30))
    confidence_kind: Mapped[str | None] = mapped_column(String(30))
    simulated: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    request_hash: Mapped[str | None] = mapped_column(String(64))


Index("emoji_session_time_idx", EmojiRecord.session_id, EmojiRecord.recorded_at.desc())
Index("emoji_user_time_idx", EmojiRecord.user_id, EmojiRecord.recorded_at.desc())


class AIIngestion(Base):
    __tablename__ = "ai_ingestion"
    __table_args__ = (
        CheckConstraint("idempotency_key ~ '^[A-Za-z0-9._:-]{1,100}$'", name="ai_ingestion_key_check"),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="ai_ingestion_hash_check"),
        CheckConstraint("(record_id IS NOT NULL AND reason IS NULL) OR (record_id IS NULL AND reason IS NOT NULL AND reason = 'LOW_CONFIDENCE')", name="ai_ingestion_outcome_check"),
    )
    idempotency_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    record_id: Mapped[UUID | None] = mapped_column(ForeignKey("emoji_record.id"), unique=True)
    reason: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class AuditLog(Identity, Base):
    __tablename__ = "audit_log"
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("app_user.id"))
    action: Mapped[str] = mapped_column(String(100))
    target_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class TeacherApplication(Identity, Base):
    __tablename__ = "teacher_application"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED')", name="teacher_application_status_check"),
        CheckConstraint("(status = 'PENDING' AND reviewed_at IS NULL AND reviewed_by IS NULL) OR (status <> 'PENDING' AND reviewed_at IS NOT NULL)", name="teacher_review_state"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"), unique=True)
    status: Mapped[str] = mapped_column(String(10), server_default=text("'PENDING'"))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("app_user.id"))
    reason: Mapped[str | None] = mapped_column(String(500))


class UserSession(Identity, Base):
    __tablename__ = "user_session"
    __table_args__ = (
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="user_session_token_hash_check"),
        CheckConstraint("expires_at > created_at", name="user_session_time_order"),
        Index("user_session_user_idx", "user_id"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WsTicket(Identity, Base):
    __tablename__ = "ws_ticket"
    __table_args__ = (
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="ws_ticket_token_hash_check"),
        CheckConstraint("expires_at > created_at AND expires_at <= created_at + INTERVAL '30 seconds'", name="ws_ticket_time_order"),
        Index("ws_ticket_session_idx", "session_id"),
    )
    session_id: Mapped[UUID] = mapped_column(ForeignKey("user_session.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
