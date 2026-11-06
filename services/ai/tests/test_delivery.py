from uuid import uuid4

import httpx
import pytest

import app.runner as runner_module
from app.delivery import confirmed_result
from app.runner import Runner


def payload():
    return {"sessionId": str(uuid4()), "emotion": "HAPPY", "confidence": 0.9,
        "recordedAt": "2026-11-06T00:00:00Z", "source": "AI", "deviceId": "test-camera",
        "simulated": False, "inferenceProvider": "DeepSeek", "confidenceKind": "self_reported"}


def accepted(body, **record_changes):
    return {"code": "OK", "data": {"accepted": True, "created": True,
        "record": {**body, "id": str(uuid4()), "userId": None, **record_changes}}}


@pytest.mark.parametrize("body", [None, [], "OK", {"code": "OK"},
    {"code": "OK", "data": {"accepted": True}}, {"code": "OK", "data": {"accepted": "true"}},
    {"code": "OK", "data": {"accepted": False}},
    {"code": "OK", "data": {"accepted": False, "reason": "UNKNOWN"}}])
def test_malformed_success_never_discards_queued_result(tmp_path, body):
    runner = Runner(str(tmp_path / "outbox.sqlite"))
    runner.outbox.put(payload())
    original = runner.outbox.peek()
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
        assert runner.send_one(client) is False
    assert runner.outbox.peek() == original and runner.status()["failed"] == 1


@pytest.mark.parametrize("change", [
    {"id": "placeholder"}, {"sessionId": str(uuid4())}, {"userId": str(uuid4())},
    {"source": "MANUAL"}, {"emotion": "SAD"}, {"confidence": 0.8}, {"confidence": True}, {"confidence": 10 ** 400},
    {"simulated": True}, {"simulated": "false"}, {"deviceId": "different-camera"},
    {"recordedAt": "2026-11-06T00:00:00"}, {"recordedAt": "2026-11-06T00:00:01Z"},
    {"confidenceKind": "model_score"}, {"inferenceProvider": None},
])
def test_inconsistent_receipt_is_uncertain_and_keeps_same_key(tmp_path, change):
    body = payload()
    runner = Runner(str(tmp_path / "outbox.sqlite"))
    runner.outbox.put(body)
    original = runner.outbox.peek()
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=accepted(body, **change)))) as client:
        assert runner.send_one(client) is False
    assert runner.outbox.peek() == original


@pytest.mark.parametrize("created", [True, False])
def test_valid_acknowledgement_compares_absolute_time_and_removes_queue(tmp_path, created):
    body = payload()
    receipt = accepted(body, recordedAt="2026-11-06T08:00:00+08:00")
    receipt["data"]["created"] = created
    runner = Runner(str(tmp_path / "outbox.sqlite"))
    runner.outbox.put(body)
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=receipt))) as client:
        assert runner.send_one(client) is True
    assert runner.outbox.count() == 0 and runner.status()["submitted"] == 1


def test_confirmed_filter_removes_queue_and_counts_as_filtered(tmp_path):
    runner = Runner(str(tmp_path / "outbox.sqlite"))
    runner.outbox.put(payload())
    receipt = {"code": "OK", "data": {"accepted": False, "reason": "LOW_CONFIDENCE"}}
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=receipt))) as client:
        assert runner.send_one(client) is True
    assert runner.outbox.count() == 0
    assert runner.status()["filtered"] == 1 and runner.status()["submitted"] == 0


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_retryable_http_failure_preserves_payload(tmp_path, status):
    runner = Runner(str(tmp_path / "outbox.sqlite"))
    runner.outbox.put(payload())
    original = runner.outbox.peek()
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status))) as client:
        assert runner.send_one(client) is False
    assert runner.outbox.peek() == original


def test_created_flag_is_required_and_typed():
    body = payload()
    for value in (None, "true", 1):
        receipt = accepted(body)
        receipt["data"]["created"] = value
        with pytest.raises(ValueError):
            confirmed_result(receipt, body)


@pytest.mark.parametrize("status", [301, 401, 403, 409, 422])
def test_non_success_status_never_acknowledges_or_discards_result(tmp_path, status):
    body = payload()
    runner = Runner(str(tmp_path / "outbox.sqlite"))
    runner.outbox.put(body)
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status, json=accepted(body)))) as client:
        with pytest.raises(RuntimeError):
            runner.send_one(client)
    assert runner.outbox.count() == 1


def test_transport_failure_retries_with_bounded_backoff_and_same_key(tmp_path, monkeypatch):
    runner = Runner(str(tmp_path / "outbox.sqlite"))
    body = payload()
    runner.outbox.put(body)
    key, original = runner.outbox.peek()
    waits, keys = [], []

    class Stop:
        def is_set(self):
            return len(waits) >= 7

        def wait(self, delay):
            waits.append(delay)

    def handler(request):
        keys.append(request.headers["Idempotency-Key"])
        return httpx.Response(503)

    original_client = httpx.Client
    monkeypatch.setattr(runner_module.httpx, "Client", lambda **kwargs:
        original_client(transport=httpx.MockTransport(handler), **kwargs))
    runner.stop_event = Stop()
    runner.run({"mode": "simulation", "sessionId": body["sessionId"], "cameraIndex": 0,
        "confidenceThreshold": 0.75, "sampleIntervalSeconds": 3600})
    assert waits == [2, 4, 8, 16, 30, 30, 30]
    assert keys == [key] * 7 and runner.outbox.peek() == (key, original)
