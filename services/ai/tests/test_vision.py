import base64
import io
import json

import httpx
import pytest
from app.main import create_app
from app.vision import DeepSeekVision, VisionError, prepare_image
from fastapi.testclient import TestClient
from PIL import Image


def image_bytes():
    buffer = io.BytesIO()
    image = Image.new("RGB", (1500, 1000), (180, 180, 180))
    exif = Image.Exif()
    exif[270] = "metadata-must-be-removed"
    image.save(buffer, "JPEG", exif=exif)
    return buffer.getvalue()


def completion(content, finish="stop"):
    return httpx.Response(
        200,
        json={"choices": [{"finish_reason": finish, "message": {"content": content}}]},
    )


def test_remote_payload_and_stripped_metadata(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-credential")

    def handler(request):
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-credential"
        body = json.loads(request.content)
        assert body["model"] == "deepseek-flash"
        assert body["response_format"] == {"type": "json_object"}
        url = body["messages"][0]["content"][1]["image_url"]["url"]
        assert url.startswith("data:image/jpeg;base64,")
        with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as image:
            assert max(image.size) <= 1024
            assert not image.getexif() and not image.info.get("icc_profile")
        return completion('{"faces":[{"label":"happy","score":0.92}]}')

    result = DeepSeekVision(transport=httpx.MockTransport(handler)).analyze(
        image_bytes()
    )
    assert result["faces"][0]["emotion"] == "HAPPY"
    assert result["confidenceKind"] == "self_reported" and not result["calibrated"]
    assert not result["persisted"]


@pytest.mark.parametrize(
    "content,finish",
    [
        ('{"faces":[{"label":"focused","score":0.9}]}', "stop"),
        ('{"faces":[{"label":"happy","score":1.1}]}', "stop"),
        ('{"faces":[{"label":"happy","score":NaN}]}', "stop"),
        ('{"faces":[{"label":"happy","score":"0.9"}]}', "stop"),
        ('{"faces":[{"label":"happy","score":true}]}', "stop"),
        ('{"faces":[],"identity":"not-permitted"}', "stop"),
        ("", "stop"),
        ('{"faces":[]}', "length"),
    ],
)
def test_rejects_unreliable_provider_response(monkeypatch, content, finish):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-credential")
    adapter = DeepSeekVision(
        transport=httpx.MockTransport(lambda _request: completion(content, finish))
    )
    with pytest.raises(VisionError, match="契约"):
        adapter.analyze(image_bytes())


def test_empty_faces_and_uncertain_do_not_invent_emotion(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-credential")
    for content, expected in [
        ('{"faces":[]}', []),
        (
            '{"faces":[{"label":"uncertain","score":0.2}]}',
            [{"label": "uncertain", "score": 0.2, "emotion": None}],
        ),
    ]:
        result = DeepSeekVision(
            transport=httpx.MockTransport(
                lambda _request, content=content: completion(content)
            )
        ).analyze(image_bytes())
        assert result["faces"] == expected


@pytest.mark.parametrize("status", [401, 402, 429, 500, 302])
def test_upstream_errors_are_sanitized_without_retry(monkeypatch, status):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-credential")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="sensitive-upstream-error")

    with pytest.raises(VisionError) as error:
        DeepSeekVision(transport=httpx.MockTransport(handler)).analyze(image_bytes())
    assert "sensitive" not in str(error.value) and "credential" not in str(error.value)
    assert len(calls) == 1


def test_missing_key_and_invalid_image_fail_before_network(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(VisionError, match="未配置"):
        DeepSeekVision().analyze(image_bytes())
    for content in [b"", b"not-an-image", b"x" * (16 * 1024 * 1024 + 1)]:
        with pytest.raises(VisionError):
            prepare_image(content)


def test_protected_sample_whitelist_and_explicit_upload(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_CONTROL_TOKEN", "control-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "private-config-value")
    with TestClient(create_app(str(tmp_path / "outbox.sqlite"))) as client:
        headers = {"Authorization": "Bearer control-test"}
        assert client.get("/control/vision").status_code == 401
        response = client.get("/control/vision", headers=headers)
        assert response.json()["data"]["configured"]
        assert "private-config-value" not in response.text
        assert (
            client.post(
                "/control/analyze-image",
                headers=headers,
                json={
                    "imageId": "portrait-01",
                    "allowRemoteUpload": False,
                },
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/control/analyze-image",
                headers=headers,
                json={
                    "imageId": "../../.env",
                    "allowRemoteUpload": True,
                },
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/control/analyze-image",
                headers=headers,
                json={
                    "imageId": "portrait-01",
                    "allowRemoteUpload": True,
                    "url": "http://localhost",
                },
            ).status_code
            == 422
        )
        assert not client.app.state.runner.status()["running"]


def test_service_imports_in_flat_container_layout(tmp_path, monkeypatch):
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    service = Path(__file__).resolve().parents[1]
    target = tmp_path / "flat-service"
    shutil.copytree(
        service / "app", target / "app", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copytree(service / "data", target / "data")
    monkeypatch.setenv("AI_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("AI_OUTBOX_PATH", str(tmp_path / "outbox.sqlite"))
    code = (
        "from app.main import app; from app.vision import vision_status, DATA_DIR; "
        "assert len(vision_status()['samples']) == 4; "
        "assert DATA_DIR.name == 'runtime'"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=target,
        check=True,
        capture_output=True,
        timeout=15,
    )
