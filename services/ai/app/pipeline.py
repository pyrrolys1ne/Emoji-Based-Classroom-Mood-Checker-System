"""帧及检测到的人脸仅存在内存，不保存原始影像。"""

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite

EMOTION_MAP = {
    "happy": "HAPPY",
    "neutral": "NEUTRAL",
    "sad": "SAD",
    "angry": "ANGRY",
    "surprise": "SURPRISED",
    "fear": "FEAR",
    "disgust": "DISGUST",
}


@dataclass(frozen=True)
class Prediction:
    label: str
    confidence: float
    inference_provider: str | None = None
    confidence_kind: str | None = None


def map_predictions(
    predictions: list[Prediction],
    *,
    session_id: str,
    device_id: str,
    threshold: float,
    simulated: bool = False,
    recorded_at: str | None = None,
) -> tuple[list[dict], int]:
    results = []
    filtered = 0
    for prediction in predictions:
        emotion = EMOTION_MAP.get(prediction.label)
        if (
            emotion is None
            or not isfinite(prediction.confidence)
            or not 0 <= prediction.confidence <= 1
            or prediction.confidence < threshold
        ):
            filtered += 1
            continue
        results.append(
            {
                "sessionId": session_id,
                "emotion": emotion,
                "confidence": prediction.confidence,
                "recordedAt": recorded_at or datetime.now(timezone.utc).isoformat(),
                "source": "AI",
                "deviceId": device_id,
                "simulated": simulated,
                **(
                    {"inferenceProvider": prediction.inference_provider}
                    if prediction.inference_provider
                    else {}
                ),
                **(
                    {"confidenceKind": prediction.confidence_kind}
                    if prediction.confidence_kind
                    else {}
                ),
            }
        )
    return results, filtered


class DeepFaceModel:
    def __init__(self):
        try:
            from deepface import DeepFace
        except ImportError as exc:
            raise RuntimeError(
                "未安装真实模型依赖，请按 AI 集成文档使用独立 Python 环境安装"
            ) from exc
        self.model = DeepFace
        self.loaded = False

    def predict(self, frame) -> list[Prediction]:
        try:
            results = self.model.analyze(
                img_path=frame,
                actions=["emotion"],
                detector_backend="opencv",
                enforce_detection=True,
                silent=True,
            )
        except ValueError as exc:
            if "Face could not be detected" in str(exc):
                return []
            raise
        self.loaded = True
        if isinstance(results, dict):
            results = [results]
        predictions = []
        for face in results:
            scores = face.get("emotion", {})
            if scores:
                label = max(scores, key=scores.get)
                predictions.append(Prediction(label, float(scores[label]) / 100))
        return predictions


class Camera:
    def __init__(self, index: int):
        import sys

        try:
            import cv2
        except ImportError:
            raise RuntimeError(
                "未安装摄像头依赖，请安装 services/ai/requirements-camera.txt"
            ) from None

        self.capture = cv2.VideoCapture(
            index, cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        )
        if not self.capture.isOpened():
            self.capture.release()
            raise RuntimeError("无法打开摄像头，请检查设备编号和系统权限")

    def read(self):
        success, frame = self.capture.read()
        if not success:
            raise RuntimeError("摄像头断线或读取失败")
        return frame

    def close(self):
        self.capture.release()
