"""摄像头 → 采样 → 检测 → 分类 → 过滤 → 映射 → 后端。尚未加载模型。"""
from dataclasses import dataclass
from datetime import datetime


EMOTION_MAP = {"happy": "HAPPY", "neutral": "NEUTRAL", "sad": "SAD", "focused": "FOCUSED", "confused": "CONFUSED"}


@dataclass(frozen=True)
class InferenceResult:
    session_id: str
    emotion: str
    confidence: float
    recorded_at: datetime
    device_id: str


def infer_frame(frame: object) -> list[InferenceResult]:
    raise NotImplementedError("待接入人脸检测与情绪模型；禁止生成虚假的推理结果。")
