import json
from uuid import uuid4

import app.runner as runner_module
import httpx
import pytest
from app.main import create_app
from app.pipeline import Prediction
from app.runner import Runner
from app.vision import VisionError
from fastapi.testclient import TestClient


def config(**changes):
    return {
        "sessionId": str(uuid4()),
        "mode": "camera-api",
        "cameraIndex": 0,
        "sampleIntervalSeconds": 5,
        "confidenceThreshold": 0.75,
        "allowRemoteUpload": True,
        "maxSamples": 1,
        "maxDurationSeconds": 30,
        **changes,
    }


@pytest.fixture
def camera_runtime(tmp_path, monkeypatch):
    events = []
    payloads = []
    runner = Runner(str(tmp_path / "outbox.sqlite"))

    class Camera:
        def __init__(self, index):
            events.append("opened")

        def read(self):
            events.append("read")
            return object()

        def close(self):
            events.append("closed")

    class Model:
        loaded = True
        elapsed_ms = 23

        def predict(self, frame):
            assert events[-1] == "closed"
            events.append("inference")
            return [
                Prediction("happy", 0.95, "DeepSeek", "self_reported"),
                Prediction("uncertain", 0.8, "DeepSeek", "self_reported"),
                Prediction("sad", 0.2, "DeepSeek", "self_reported"),
            ]

    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"code": "OK", "data": {"accepted": True}})

    original_client = httpx.Client
    monkeypatch.setattr(runner_module, "Camera", Camera)
    monkeypatch.setattr(runner_module, "DeepSeekCameraModel", Model)
    monkeypatch.setattr(
        runner_module.httpx,
        "Client",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )
    return runner, events, payloads, Model


def test_real_camera_payload_budget_and_release_before_upload(camera_runtime):
    runner, events, payloads, _ = camera_runtime
    runner.run(config())
    status = runner.status()
    assert events == ["opened", "read", "closed", "inference"]
    assert status["sampled"] == status["apiCalls"] == status["submitted"] == 1
    assert status["filtered"] == 2 and status["stopReason"] == "MAX_SAMPLES"
    assert not status["running"] and status["pending"] == 0
    assert status["lastInferenceMs"] == 23
    assert payloads[0]["simulated"] is False and payloads[0]["source"] == "AI"
    assert payloads[0]["inferenceProvider"] == "DeepSeek"
    assert payloads[0]["confidenceKind"] == "self_reported"
    assert payloads[0]["recordedAt"] == status["lastInferenceAt"]
    assert not {"image", "rawImage", "frame", "userId"} & payloads[0].keys()


def test_stop_during_api_call_discards_result(camera_runtime, monkeypatch):
    runner, events, payloads, Model = camera_runtime
    original = Model.predict

    def predict(self, frame):
        runner.stop_event.set()
        return original(self, frame)

    monkeypatch.setattr(Model, "predict", predict)
    runner.run(config())
    assert "closed" in events and not payloads and runner.outbox.count() == 0
    assert runner.status()["stopReason"] == "REQUESTED"


def test_api_failure_stops_without_automatic_paid_retry(camera_runtime, monkeypatch):
    runner, events, payloads, Model = camera_runtime

    def fail(self, frame):
        raise VisionError("DeepSeek API 密钥无效")

    monkeypatch.setattr(Model, "predict", fail)
    runner.run(config(maxSamples=5))
    status = runner.status()
    assert events[-1] == "closed" and not payloads
    assert status["apiCalls"] == 1 and status["failed"] == 1
    assert status["stopReason"] == "ERROR" and "密钥无效" in status["lastError"]


def test_wall_clock_limit_does_not_open_camera(camera_runtime):
    runner, events, payloads, _ = camera_runtime
    runner.run(config(maxDurationSeconds=0))
    assert not events and not payloads
    assert runner.status()["stopReason"] == "TIME_LIMIT"


def test_camera_start_requires_remote_consent_rate_and_finite_budget(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AI_CONTROL_TOKEN", "camera-control")
    monkeypatch.setenv("AI_SERVICE_TOKEN", "service-test")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with TestClient(create_app(str(tmp_path / "api.sqlite"))) as client:
        headers = {"Authorization": "Bearer camera-control"}
        for changes in [
            {"allowRemoteUpload": False},
            {"sampleIntervalSeconds": 1},
            {"maxSamples": 0},
            {"maxSamples": 61},
            {"maxDurationSeconds": 601},
        ]:
            assert (
                client.post(
                    "/control/start", headers=headers, json=config(**changes)
                ).status_code
                == 422
            )
        assert (
            client.post("/control/start", headers=headers, json=config()).status_code
            == 409
        )
        assert not client.app.state.runner.status()["running"]


def test_running_capture_cannot_be_started_twice(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_SERVICE_TOKEN", "service-test")
    runner = Runner(str(tmp_path / "locked.sqlite"))

    class Thread:
        def is_alive(self):
            return True

    runner.thread = Thread()
    with pytest.raises(RuntimeError, match="已在运行"):
        runner.start(config())
