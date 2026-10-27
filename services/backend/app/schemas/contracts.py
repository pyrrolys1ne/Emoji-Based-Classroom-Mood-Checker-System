from datetime import datetime
from enum import StrEnum
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel


class Contract(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )


class Emotion(StrEnum):
    HAPPY = "HAPPY"
    FOCUSED = "FOCUSED"
    NEUTRAL = "NEUTRAL"
    CONFUSED = "CONFUSED"
    SAD = "SAD"
    ANGRY = "ANGRY"
    SURPRISED = "SURPRISED"
    FEAR = "FEAR"
    DISGUST = "DISGUST"


class RegisterRequest(Contract):
    username: str = Field(min_length=2, max_length=50)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    # 管理员创建走后续受控流程，禁止公开注册时自选管理员。
    role: Literal["STUDENT", "TEACHER"] = "STUDENT"


class LoginRequest(Contract):
    username: str
    password: str


class PasswordRequest(Contract):
    old_password: str
    new_password: str = Field(min_length=8, max_length=128)


class EmojiSubmission(Contract):
    session_id: UUID
    emotion: Emotion


class ScheduleRequest(Contract):
    user_ids: list[UUID] = Field(max_length=500)


class AIResult(Contract):
    session_id: UUID
    emotion: Emotion
    confidence: float = Field(ge=0, le=1)
    recorded_at: datetime
    device_id: str = Field(min_length=1, max_length=100)
    source: Literal["AI"] = "AI"
    simulated: bool = False
    inference_provider: Literal["DeepSeek", "DeepFace"] | None = None
    confidence_kind: Literal["self_reported", "model_score"] | None = None

    @model_validator(mode="after")
    def score_metadata(self):
        if (
            self.inference_provider == "DeepSeek"
            and self.confidence_kind != "self_reported"
        ):
            raise ValueError("DeepSeek 分数必须标为模型自评分")
        return self

    @field_validator("recorded_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("时间戳必须带时区")
        return value


T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    code: str = "OK"
    message: str = "成功"
    data: T
