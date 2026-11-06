from typing import Literal
from uuid import UUID
from urllib.parse import urlsplit

from pydantic import AwareDatetime, ConfigDict, Field, field_validator, model_validator

from app.schemas.contracts import AIEmotion, Contract


class AIConfig(Contract):
    session_id: UUID
    mode: Literal["simulation", "camera", "camera-api"] = "simulation"
    sample_interval_seconds: float = Field(default=2, ge=0.5, le=60, allow_inf_nan=False, strict=True)
    confidence_threshold: float = Field(default=0.75, ge=0, le=1, allow_inf_nan=False, strict=True)
    camera_index: int = Field(default=0, ge=0, le=10, strict=True)
    allow_remote_upload: bool = Field(default=False, strict=True)
    max_samples: int = Field(default=5, ge=1, le=60, strict=True)
    max_duration_seconds: int = Field(default=120, ge=10, le=600, strict=True)

    @model_validator(mode="after")
    def remote_consent(self):
        if self.mode == "camera-api" and (not self.allow_remote_upload or self.sample_interval_seconds < 5):
            raise ValueError("远程摄像头需要明确允许发送，采样间隔至少 5 秒")
        return self


class ImageRequest(Contract):
    image_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
    allow_remote_upload: bool = Field(strict=True)

    @model_validator(mode="after")
    def consent(self):
        if not self.allow_remote_upload:
            raise ValueError("图片分析需要明确允许远程发送")
        return self


class EmptyRequest(Contract):
    pass


class Upstream(Contract):
    # 只返回已定义字段，上游扩展或错误信息不能把服务端凭据带入浏览器。
    model_config = ConfigDict(extra="ignore")


class FaceScore(Upstream):
    emotion: AIEmotion | None
    score: float = Field(ge=0, le=1, allow_inf_nan=False, strict=True)


class AIStatus(Upstream):
    running: bool = Field(strict=True)
    mode: Literal["simulation", "camera", "camera-api"] | None
    model_loaded: bool = Field(strict=True)
    session_id: UUID | None
    sampled: int = Field(ge=0, strict=True)
    submitted: int = Field(ge=0, strict=True)
    filtered: int = Field(ge=0, strict=True)
    failed: int = Field(ge=0, strict=True)
    pending: int = Field(ge=0, strict=True)
    last_error: str | None
    last_submitted_at: AwareDatetime | None
    config: AIConfig | None
    api_calls: int = Field(ge=0, strict=True)
    last_inference_ms: float | None = Field(ge=0, allow_inf_nan=False, strict=True)
    last_inference_at: AwareDatetime | None
    last_faces: list[FaceScore] = Field(max_length=100)
    stop_reason: Literal["REQUESTED", "MAX_SAMPLES", "TIME_LIMIT", "ERROR"] | None

    @field_validator("last_error", mode="before")
    @classmethod
    def safe_error(cls, value):
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValueError("错误状态无效")
        return "AI 任务报告错误，请在服务端核对配置与运行状态。"

    @model_validator(mode="after")
    def consistent_config(self):
        if self.config is not None and (self.config.session_id != self.session_id or self.config.mode != self.mode):
            raise ValueError("运行配置与任务不一致")
        if self.running and (self.config is None or self.session_id is None or self.mode is None):
            raise ValueError("运行中任务缺少配置")
        return self


class VisionSample(Upstream):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
    title: str = Field(min_length=1, max_length=200)
    source_url: str | None = Field(max_length=1000)
    credit: str = Field(max_length=500)
    license: str = Field(max_length=200)
    kind: Literal["portrait", "negative-control"]
    available: bool = Field(strict=True)

    @field_validator("source_url")
    @classmethod
    def public_url(cls, value):
        if value is not None:
            url = urlsplit(value)
            if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query:
                raise ValueError("样本来源必须为不含凭据和查询参数的公开 HTTP 地址")
        return value


class VisionStatus(Upstream):
    provider: Literal["DeepSeek"]
    model: Literal["deepseek-flash"]
    configured: bool = Field(strict=True)
    confidence_kind: Literal["self_reported"]
    calibrated: Literal[False]
    samples: list[VisionSample] = Field(max_length=100)

    @model_validator(mode="after")
    def distinct_samples(self):
        if len({sample.id for sample in self.samples}) != len(self.samples):
            raise ValueError("样本编号重复")
        return self


class VisionFace(FaceScore):
    label: Literal["happy", "neutral", "sad", "angry", "surprise", "fear", "disgust", "uncertain"]

    @model_validator(mode="after")
    def mapped_emotion(self):
        expected = {"happy": "HAPPY", "neutral": "NEUTRAL", "sad": "SAD", "angry": "ANGRY",
            "surprise": "SURPRISED", "fear": "FEAR", "disgust": "DISGUST", "uncertain": None}
        if self.emotion != expected[self.label]:
            raise ValueError("表情映射不一致")
        return self


class VisionResult(Upstream):
    image_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
    provider: Literal["DeepSeek"]
    model: Literal["deepseek-flash"]
    confidence_kind: Literal["self_reported"]
    calibrated: Literal[False]
    sample_only: Literal[True]
    persisted: Literal[False]
    elapsed_ms: float = Field(ge=0, allow_inf_nan=False, strict=True)
    faces: list[VisionFace] = Field(max_length=100)
