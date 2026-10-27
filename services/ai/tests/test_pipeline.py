from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.pipeline import DeepFaceModel, EMOTION_MAP, Prediction, map_predictions
from app.runner import Runner


def test_supported_emotions_and_low_confidence_filter():
    predictions = [Prediction(label, 0.9) for label in EMOTION_MAP] + [
        Prediction("happy", 0.2),
        Prediction("focused", 0.9),
        Prediction("happy", float("nan")),
    ]
    results, filtered = map_predictions(
        predictions, session_id=str(uuid4()), device_id="test", threshold=0.75
    )
    assert len(results) == 7 and filtered == 3
    assert {result["emotion"] for result in results} == set(EMOTION_MAP.values())
    assert all(
        result["source"] == "AI" and result["recordedAt"].endswith("+00:00")
        for result in results
    )
    assert all("userId" not in result and "image" not in result for result in results)


def test_retry_uses_same_key_and_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_SERVICE_TOKEN", "service-only")
    path = str(tmp_path / "outbox.sqlite")
    runner = Runner(path)
    runner.outbox.put(
        {"sessionId": str(uuid4()), "emotion": "HAPPY", "confidence": 0.9}
    )
    keys = []

    def handler(request):
        keys.append(request.headers["Idempotency-Key"])
        if len(keys) == 1:
            raise httpx.ConnectError("offline")
        return httpx.Response(200, json={"code": "OK", "data": {"accepted": True}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert not runner.send_one(client)
        assert runner.outbox.count() == 1
        restarted = Runner(path)
        assert restarted.send_one(client)
        assert restarted.outbox.count() == 0
        assert keys[0] == keys[1]


def test_permanent_failure_does_not_discard_payload(tmp_path):
    runner = Runner(str(tmp_path / "outbox.sqlite"))
    runner.outbox.put({"emotion": "HAPPY"})
    import pytest

    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(401))
    ) as client:
        with pytest.raises(RuntimeError):
            runner.send_one(client)
    assert runner.outbox.count() == 1


def test_control_auth_validation_and_no_automatic_camera(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_CONTROL_TOKEN", "control-only")
    app = create_app(str(tmp_path / "outbox.sqlite"))
    with TestClient(app) as client:
        assert client.get("/control/status").status_code == 401
        headers = {"Authorization": "Bearer control-only"}
        status = client.get("/control/status", headers=headers).json()["data"]
        assert not status["running"] and not status["modelLoaded"]
        assert (
            client.post(
                "/control/start",
                headers=headers,
                json={"sessionId": str(uuid4()), "sampleIntervalSeconds": 0},
            ).status_code
            == 422
        )


def test_deepface_adapter_passes_emotion_only_and_scales_scores():
    class Model:
        def analyze(self, **kwargs):
            assert kwargs["actions"] == ["emotion"]
            assert kwargs["enforce_detection"] is True
            assert kwargs["img_path"] is frame
            return [{"emotion": {"happy": 91, "sad": 9}}]

    frame = object()
    adapter = DeepFaceModel.__new__(DeepFaceModel)
    adapter.model, adapter.loaded = Model(), False
    assert adapter.predict(frame) == [Prediction("happy", 0.91)]
    assert adapter.loaded
