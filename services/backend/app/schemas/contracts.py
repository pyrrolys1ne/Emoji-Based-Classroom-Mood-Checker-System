from enum import StrEnum
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel

from app.core.domain import Emotion, RecordSource, Role, TeacherApprovalStatus, UserStatus


class Contract(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
StudentNo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Username = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=50)]
IdempotencyKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,100}$")]
AIEmotion = Literal[
    Emotion.HAPPY, Emotion.NEUTRAL, Emotion.SAD, Emotion.ANGRY,
    Emotion.SURPRISED, Emotion.FEAR, Emotion.DISGUST,
]


class SourceFilter(StrEnum):
    MANUAL = "MANUAL"
    AI = "AI"
    ALL = "ALL"


class RegisterRequest(Contract):
    username: Username
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128, repr=False, json_schema_extra={"format": "password", "writeOnly": True})
    # 管理员创建走后续受控流程，禁止公开注册时自选管理员。
    role: Literal["STUDENT", "TEACHER"] = "STUDENT"
    student_no: StudentNo | None = None
    real_name: Name | None = None
    class_name: Name | None = None

    @model_validator(mode="after")
    def student_fields(self):
        if self.role == "TEACHER" and (self.student_no is not None or self.class_name is not None):
            raise ValueError("教师申请不能包含学生学号或学生班级")
        return self


class LoginRequest(Contract):
    username: Username
    password: str = Field(min_length=1, max_length=128, repr=False, json_schema_extra={"format": "password", "writeOnly": True})


class PasswordRequest(Contract):
    old_password: str = Field(min_length=1, max_length=128, repr=False, json_schema_extra={"format": "password", "writeOnly": True})
    new_password: str = Field(min_length=8, max_length=128, repr=False, json_schema_extra={"format": "password", "writeOnly": True})

    @model_validator(mode="after")
    def changed_password(self):
        if self.old_password == self.new_password:
            raise ValueError("新密码不能与原密码相同")
        return self


class AdminBootstrapRequest(Contract):
    username: Username
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128, repr=False)
    real_name: Name | None = None


class EmojiSubmission(Contract):
    session_id: UUID
    emotion: Emotion


class ScheduleRequest(Contract):
    user_ids: list[UUID] = Field(max_length=500)


class StudentProfileRequest(Contract):
    student_no: StudentNo | None = None
    real_name: Name | None = None
    class_name: Name | None = None

    @model_validator(mode="after")
    def specified_fields(self):
        if not self.model_fields_set:
            raise ValueError("至少提供一个学生资料字段")
        return self


class TeacherReviewRequest(Contract):
    decision: Literal["APPROVED", "REJECTED"]
    reason: str | None = Field(default=None, max_length=500)


class CourseRequest(Contract):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
    teacher_id: UUID


class Course(CourseRequest):
    id: UUID


class TeacherApplication(Contract):
    id: UUID
    user_id: UUID
    status: TeacherApprovalStatus
    submitted_at: AwareDatetime
    reviewed_at: AwareDatetime | None
    reviewed_by: UUID | None
    reason: str | None


class SessionRequest(Contract):
    course_id: UUID
    teacher_id: UUID | None = None
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    room: Name
    class_name: Name

    @model_validator(mode="after")
    def time_order(self):
        if "teacher_id" in self.model_fields_set and self.teacher_id is None:
            raise ValueError("任课教师不能显式设为空")
        if self.ends_at <= self.starts_at:
            raise ValueError("课堂结束时间必须晚于开始时间")
        return self


class ClassroomSeedCourse(Contract):
    key: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._-]{1,50}$")]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
    teacher_username: Username


class ClassroomSeedSession(Contract):
    course_key: str
    teacher_username: Username | None = None
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    room: Name
    class_name: Name
    student_usernames: list[Username] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def time_order(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("课堂结束时间必须晚于开始时间")
        return self


class ClassroomSeedRequest(Contract):
    import_id: UUID
    courses: list[ClassroomSeedCourse] = Field(min_length=1, max_length=100)
    sessions: list[ClassroomSeedSession] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def references(self):
        keys = {course.key for course in self.courses}
        if len(keys) != len(self.courses) or any(item.course_key not in keys for item in self.sessions):
            raise ValueError("课程引用必须存在且键不能重复")
        names = {course.teacher_username for course in self.courses}
        for item in self.sessions:
            names.update(item.student_usernames)
            if item.teacher_username:
                names.add(item.teacher_username)
        if len(names) > 2000:
            raise ValueError("单个批次引用的账号不能超过 2000 个")
        return self


class ClassroomSeedResult(Contract):
    import_id: UUID
    course_ids: list[UUID]
    session_ids: list[UUID]


class RecordFilters(Contract):
    session_id: UUID | None = None
    user_id: UUID | None = None
    course: UUID | None = None
    class_name: str | None = Field(default=None, alias="class", min_length=1, max_length=100)
    from_time: AwareDatetime | None = Field(default=None, alias="from")
    to_time: AwareDatetime | None = Field(default=None, alias="to")
    source: SourceFilter = SourceFilter.ALL

    @model_validator(mode="after")
    def time_order(self):
        if self.from_time and self.to_time and self.from_time >= self.to_time:
            raise ValueError("结束时间必须晚于开始时间")
        return self


class StatisticsFilters(RecordFilters):
    source: SourceFilter = SourceFilter.MANUAL


class ExportFilters(StatisticsFilters):
    format: Literal["csv"] = "csv"


class AIResult(Contract):
    session_id: UUID
    emotion: AIEmotion
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    recorded_at: AwareDatetime
    device_id: Name
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


class User(Contract):
    id: UUID
    username: str
    email: str
    role: Role
    status: UserStatus
    student_no: str | None = None
    real_name: str | None = None
    class_name: str | None = None
    teacher_approval_status: TeacherApprovalStatus | None = None


class AuthSession(Contract):
    token: str = Field(repr=False)
    user: User


class ClassroomStudent(Contract):
    id: UUID
    username: str
    student_no: str | None
    real_name: str | None
    class_name: str | None
    status: UserStatus


class ClassSession(Contract):
    id: UUID
    course_id: UUID
    course_name: str
    teacher_name: str
    teacher_id: UUID
    class_name: str
    room: str
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    scheduled_user_ids: list[UUID]
    scheduled_students: list[ClassroomStudent] = Field(default_factory=list)


class EmojiRecord(Contract):
    id: UUID
    user_id: UUID | None
    session_id: UUID
    emotion: Emotion
    source: RecordSource
    confidence: float | None = Field(ge=0, le=1, allow_inf_nan=False)
    recorded_at: AwareDatetime
    simulated: bool = False
    inference_provider: Literal["DeepSeek", "DeepFace"] | None = None
    confidence_kind: Literal["self_reported", "model_score"] | None = None


class EmotionStatistics(Contract):
    total: int = Field(ge=0)
    distribution: dict[Emotion, int]
    source: SourceFilter = SourceFilter.MANUAL

    @model_validator(mode="after")
    def complete_distribution(self):
        if set(self.distribution) != set(Emotion) or any(value < 0 for value in self.distribution.values()) or sum(self.distribution.values()) != self.total:
            raise ValueError("统计必须包含九种情绪，且分布之和等于总记录数")
        return self


class AIAccepted(Contract):
    accepted: Literal[True]
    created: bool
    record: EmojiRecord


class AIFiltered(Contract):
    accepted: Literal[False]
    reason: Literal["LOW_CONFIDENCE"]


T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    code: str = "OK"
    message: str = "成功"
    data: T
