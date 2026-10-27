import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .outbox import Outbox
from .pipeline import Camera, DeepFaceModel, EMOTION_MAP, Prediction, map_predictions
from .vision import DeepSeekCameraModel, VisionError

logger = logging.getLogger(__name__)


class Runner:
    def __init__(self, path: str | None = None):
        self.outbox = Outbox(
            path
            or os.getenv(
                "AI_OUTBOX_PATH", str(Path.cwd() / ".local" / "ai-outbox.sqlite")
            )
        )
        self.stop_event = threading.Event()
        self.thread = None
        self.lock = threading.Lock()
        self.state = {
            "running": False,
            "mode": None,
            "modelLoaded": False,
            "sessionId": None,
            "sampled": 0,
            "submitted": 0,
            "filtered": 0,
            "failed": 0,
            "pending": self.outbox.count(),
            "lastError": None,
            "lastSubmittedAt": None,
            "config": None,
            "apiCalls": 0,
            "lastInferenceMs": None,
            "lastInferenceAt": None,
            "lastFaces": [],
            "stopReason": None,
        }

    def status(self):
        with self.lock:
            return {**self.state, "pending": self.outbox.count()}

    def update(self, **kwargs):
        with self.lock:
            self.state.update(kwargs)

    def start(self, config: dict):
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise RuntimeError("采集任务已在运行或正在停止")
            if not os.getenv("AI_SERVICE_TOKEN"):
                raise RuntimeError("未配置独立 AI 入库令牌")
            if config["mode"] == "camera-api":
                if (
                    not config.get("allowRemoteUpload")
                    or config["sampleIntervalSeconds"] < 5
                ):
                    raise RuntimeError("远程摄像头需要明确允许发送，采样间隔至少 5 秒")
                if not os.getenv("DEEPSEEK_API_KEY", "").strip():
                    raise RuntimeError("未配置 DEEPSEEK_API_KEY")
            self.stop_event.clear()
            self.state.update(
                running=True,
                mode=config["mode"],
                sessionId=config["sessionId"],
                config=config,
                modelLoaded=False,
                lastError=None,
                sampled=0,
                submitted=0,
                filtered=0,
                failed=0,
                apiCalls=0,
                lastInferenceMs=None,
                lastInferenceAt=None,
                lastFaces=[],
                stopReason=None,
            )
            self.thread = threading.Thread(
                target=self.run, args=(config,), daemon=True, name="mood-ai-worker"
            )
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)

    def send_one(self, client) -> bool:
        item = self.outbox.peek()
        if not item:
            return True
        key, payload = item
        try:
            response = client.post(
                os.getenv("AI_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
                + "/api/ai/emoji-results",
                headers={
                    "Authorization": "Bearer " + os.getenv("AI_SERVICE_TOKEN", ""),
                    "Idempotency-Key": key,
                },
                json=payload,
            )
            if response.status_code in {408, 429} or response.status_code >= 500:
                raise httpx.TransportError("可重试的服务端错误")
            if response.is_error:
                raise RuntimeError(
                    f"后端拒绝上报（HTTP {response.status_code}），已保留待上报结果"
                )
            body = response.json()
            if (
                body.get("code") != "OK"
                or not isinstance(body.get("data"), dict)
                or not isinstance(body["data"].get("accepted"), bool)
            ):
                raise RuntimeError("后端响应不符合 AI 接口契约，结果保留在队列")
            self.outbox.remove(key)
            with self.lock:
                if body["data"]["accepted"]:
                    self.state["submitted"] += 1
                else:
                    self.state["filtered"] += 1
                self.state.update(
                    lastSubmittedAt=datetime.now(timezone.utc).isoformat(),
                    lastError=None,
                )
            return True
        except (httpx.HTTPError, ValueError):
            with self.lock:
                self.state["failed"] += 1
                self.state["lastError"] = "后端连接失败，结果已排队，正在退避重试"
            logger.warning("AI result delivery failed; queued for retry")
            return False

    def run(self, config: dict):
        camera = None
        remote = config["mode"] == "camera-api"
        stop_reason = "REQUESTED"
        started = time.monotonic()
        try:
            model = None
            if config["mode"] == "camera":
                model = DeepFaceModel()
            elif remote:
                model = DeepSeekCameraModel()
            retries = 0
            sample_index = 0
            next_sample = 0.0
            with httpx.Client(timeout=5, trust_env=False) as client:
                while not self.stop_event.is_set():
                    if remote and time.monotonic() - started >= config.get(
                        "maxDurationSeconds", 120
                    ):
                        stop_reason = "TIME_LIMIT"
                        break
                    complete = remote and sample_index >= config.get("maxSamples", 5)
                    if not complete and time.monotonic() >= next_sample:
                        if config["mode"] in {"camera", "camera-api"}:
                            try:
                                if camera is None:
                                    camera = Camera(config["cameraIndex"])
                                frame = camera.read()
                            except RuntimeError:
                                if camera:
                                    camera.close()
                                    camera = None
                                with self.lock:
                                    self.state["failed"] += 1
                                    self.state["lastError"] = (
                                        "摄像头读取失败，正在重新连接；不会生成替代结果"
                                    )
                                self.stop_event.wait(3)
                                continue
                            finally:
                                # API 实验每次新开设备取帧，避免缓冲区积压；请求期间释放摄像头。
                                if remote and camera:
                                    camera.close()
                                    camera = None
                            recorded_at = datetime.now(timezone.utc).isoformat()
                            if self.stop_event.is_set():
                                break
                            if remote:
                                with self.lock:
                                    self.state["apiCalls"] += 1
                            sample_index += 1
                            with self.lock:
                                self.state["sampled"] += 1
                            try:
                                predictions = model.predict(frame)
                            finally:
                                del frame
                            self.update(
                                modelLoaded=model.loaded,
                                lastError=None,
                                lastInferenceAt=recorded_at,
                                lastInferenceMs=getattr(model, "elapsed_ms", None),
                                lastFaces=[
                                    {
                                        "emotion": EMOTION_MAP.get(item.label),
                                        "score": item.confidence,
                                    }
                                    for item in predictions
                                ],
                            )
                            if self.stop_event.is_set():
                                break
                        else:
                            recorded_at = datetime.now(timezone.utc).isoformat()
                            labels = list(EMOTION_MAP)
                            predictions = [
                                Prediction(
                                    labels[sample_index % len(labels)],
                                    0.92 if sample_index % 5 else 0.35,
                                )
                            ]
                            sample_index += 1
                            with self.lock:
                                self.state["sampled"] += 1
                        payloads, filtered = map_predictions(
                            predictions,
                            session_id=config["sessionId"],
                            device_id=f"{config['mode']}-{config['cameraIndex']}",
                            threshold=config["confidenceThreshold"],
                            simulated=config["mode"] == "simulation",
                            recorded_at=recorded_at,
                        )
                        for payload in payloads:
                            self.outbox.put(payload)
                        with self.lock:
                            self.state["filtered"] += filtered
                        next_sample = time.monotonic() + config["sampleIntervalSeconds"]
                    complete = remote and sample_index >= config.get("maxSamples", 5)
                    if self.send_one(client):
                        retries = 0
                        if complete and not self.outbox.count():
                            stop_reason = "MAX_SAMPLES"
                            break
                        self.stop_event.wait(
                            0.1
                            if self.outbox.count()
                            else min(0.5, max(0.01, next_sample - time.monotonic()))
                        )
                    else:
                        if complete:
                            stop_reason = "MAX_SAMPLES"
                            break
                        retries += 1
                        self.stop_event.wait(min(30, 2 ** min(retries, 5)))
        except Exception as exc:
            stop_reason = "ERROR"
            with self.lock:
                self.state["failed"] += 1
            message = (
                str(exc)
                if isinstance(exc, (RuntimeError, VisionError))
                else f"采集失败（{type(exc).__name__}），请检查模型及摄像头配置"
            )
            self.update(lastError=message[:200])
            logger.error("AI worker stopped: %s", type(exc).__name__)
        finally:
            if camera:
                camera.close()
            self.update(running=False, stopReason=stop_reason)
