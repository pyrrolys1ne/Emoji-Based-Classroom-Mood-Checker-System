from enum import StrEnum


class Role(StrEnum):
    STUDENT = "STUDENT"
    TEACHER = "TEACHER"
    ADMIN = "ADMIN"


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class TeacherApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RecordSource(StrEnum):
    MANUAL = "MANUAL"
    AI = "AI"


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
