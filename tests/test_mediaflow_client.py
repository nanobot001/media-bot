import json

import httpx
import pytest

from moviebot.adapters.mediaflow_client import MediaFlowClient, MediaFlowError


@pytest.mark.asyncio
async def test_health_and_encrypted_url_contract_are_sanitized():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "internal": "not returned"})
        if request.method == "GET":
            return httpx.Response(200, text="#EXTM3U\n#EXT-X-ENDLIST\n")
        payload = json.loads(request.content)
        assert payload["mediaflow_proxy_url"] == "http://127.0.0.1:8888"
        assert payload["api_password"] == "pilot-secret"
        assert payload["destination_url"] == "https://provider.example/video.mp4?token=upstream"
        assert payload["endpoint"] == "/proxy/transcode/playlist.m3u8"
        assert payload["expiration"] == 900
        return httpx.Response(
            200,
            json={"url": "http://127.0.0.1:8888/proxy/transcode/playlist.m3u8?token=opaque-session"},
        )

    client = MediaFlowClient(
        base_url="http://127.0.0.1:8888",
        api_password="pilot-secret",
        transport=httpx.MockTransport(handler),
    )

    health = await client.health()
    result = await client.generate_signed_playback_url(
        "https://provider.example/video.mp4?token=upstream",
        expiration_seconds=900,
    )

    assert health == {
        "ok": True,
        "code": "MEDIAFLOW_HEALTHY",
        "service": "mediaflow-proxy",
        "status": "ok",
        "capabilities": {"force_audio_stereo": False},
    }
    assert result["ok"] is True
    assert result["mode"] == "transcode_hls"
    assert "provider.example" not in json.dumps(result)
    assert "upstream" not in json.dumps(result)
    assert "pilot-secret" not in json.dumps(result)
    assert [request.method for request in requests] == ["GET", "POST", "GET"]


@pytest.mark.asyncio
async def test_unsafe_hls_manifest_falls_back_to_encrypted_direct_transcode():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                text=(
                    "#EXTM3U\n"
                    '#EXT-X-MAP:URI="/proxy/transcode/init.mp4?d=https%3A%2F%2Fprovider.example%2Fvideo.mp4&'
                    'api_password=pilot-secret"\n'
                ),
            )
        payload = json.loads(request.content)
        if payload["endpoint"] == "/proxy/transcode/playlist.m3u8":
            return httpx.Response(
                200,
                json={"url": "http://127.0.0.1:8888/_token_hls/proxy/transcode/playlist.m3u8"},
            )
        assert payload["endpoint"] == "/proxy/stream"
        assert payload["query_params"] == {"transcode": "true"}
        return httpx.Response(200, json={"url": "http://127.0.0.1:8888/_token_direct/proxy/stream"})

    client = MediaFlowClient(
        base_url="http://127.0.0.1:8888",
        api_password="pilot-secret",
        transport=httpx.MockTransport(handler),
    )
    result = await client.generate_signed_playback_url(
        "https://provider.example/video.mp4",
        expiration_seconds=900,
    )

    assert result["mode"] == "transcode_stream"
    assert result["requested_mode"] == "transcode_hls"
    assert result["fallback_reason"] == "HLS_MANIFEST_UNSAFE"
    assert result["endpoint"] == "/proxy/stream"
    assert "provider.example" not in json.dumps(result)
    assert "pilot-secret" not in json.dumps(result)
    assert [request.method for request in requests] == ["POST", "GET", "POST"]


@pytest.mark.asyncio
async def test_hls_validation_failure_falls_back_to_direct_transcode():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(404, text="not found")
        payload = json.loads(request.content)
        if payload["endpoint"] == "/proxy/transcode/playlist.m3u8":
            return httpx.Response(
                200,
                json={"url": "http://127.0.0.1:8888/_token_hls/proxy/transcode/playlist.m3u8"},
            )
        return httpx.Response(200, json={"url": "http://127.0.0.1:8888/_token_direct/proxy/stream"})

    client = MediaFlowClient(
        base_url="http://127.0.0.1:8888",
        api_password="pilot-secret",
        transport=httpx.MockTransport(handler),
    )
    result = await client.generate_signed_playback_url(
        "https://provider.example/video.mp4",
        expiration_seconds=900,
    )

    assert result["mode"] == "transcode_stream"
    assert result["fallback_reason"] == "MEDIAFLOW_HLS_VALIDATION_FAILED"
    assert [request.method for request in requests] == ["POST", "GET", "POST"]


@pytest.mark.asyncio
async def test_direct_transcode_mode_preserves_start_and_filename():
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["endpoint"] == "/proxy/stream"
        assert payload["query_params"] == {"transcode": "true", "start": "120.5"}
        assert payload["filename"] == "pilot.mp4"
        return httpx.Response(200, json={"url": "http://localhost:8888/proxy/stream?token=opaque"})

    client = MediaFlowClient(
        base_url="http://localhost:8888",
        api_password="pilot-secret",
        transport=httpx.MockTransport(handler),
    )
    result = await client.generate_signed_playback_url(
        "https://provider.example/video.mkv",
        mode="transcode_stream",
        start_seconds=120.5,
        filename="pilot.mp4",
    )
    assert result["endpoint"] == "/proxy/stream"
    assert result["url"].startswith("http://localhost:8888/")


@pytest.mark.asyncio
async def test_force_audio_stereo_is_signed_into_direct_transcode_request():
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["endpoint"] == "/proxy/stream"
        assert payload["query_params"] == {
            "transcode": "true",
            "force_audio_stereo": "true",
        }
        return httpx.Response(200, json={"url": "http://127.0.0.1:8888/proxy/stream?token=opaque"})

    client = MediaFlowClient(
        base_url="http://127.0.0.1:8888",
        api_password="pilot-secret",
        transport=httpx.MockTransport(handler),
    )
    result = await client.generate_signed_playback_url(
        "https://provider.example/video.mkv",
        mode="transcode_stream",
        force_audio_stereo=True,
    )

    assert result["mode"] == "transcode_stream"


@pytest.mark.asyncio
async def test_force_audio_stereo_avoids_unpatched_hls_path():
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["endpoint"] == "/proxy/stream"
        assert payload["query_params"] == {
            "transcode": "true",
            "force_audio_stereo": "true",
        }
        return httpx.Response(200, json={"url": "http://127.0.0.1:8888/proxy/stream?token=opaque"})

    client = MediaFlowClient(
        base_url="http://127.0.0.1:8888",
        api_password="pilot-secret",
        transport=httpx.MockTransport(handler),
    )
    result = await client.generate_signed_playback_url(
        "https://provider.example/video.mkv",
        mode="transcode_hls",
        force_audio_stereo=True,
    )

    assert result["mode"] == "transcode_stream"
    assert result["requested_mode"] == "transcode_hls"
    assert result["fallback_reason"] == "AUDIO_STEREO_REQUIRES_DIRECT_TRANSCODE"


def test_client_requires_localhost_and_password():
    with pytest.raises(MediaFlowError) as non_local:
        MediaFlowClient(base_url="http://mediaflow.internal:8888", api_password="secret")
    assert non_local.value.code == "MEDIAFLOW_NON_LOCAL_URL"


@pytest.mark.asyncio
async def test_generation_requires_password_and_rejects_leaked_url():
    client = MediaFlowClient(base_url="http://127.0.0.1:8888", api_password="")
    with pytest.raises(MediaFlowError) as missing:
        await client.generate_signed_playback_url("https://provider.example/video.mp4")
    assert missing.value.code == "MEDIAFLOW_PASSWORD_MISSING"

    async def leaking_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"url": "http://127.0.0.1:8888/proxy/stream?d=https%3A%2F%2Fprovider.example%2Fvideo.mp4"},
        )

    leaking_client = MediaFlowClient(
        base_url="http://127.0.0.1:8888",
        api_password="pilot-secret",
        transport=httpx.MockTransport(leaking_handler),
    )
    with pytest.raises(MediaFlowError) as leaked:
        await leaking_client.generate_signed_playback_url("https://provider.example/video.mp4")
    assert leaked.value.code == "MEDIAFLOW_URL_SECURITY_FAILED"


@pytest.mark.asyncio
async def test_health_failure_does_not_return_provider_details():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream=https://private.example/token")

    client = MediaFlowClient(
        base_url="http://127.0.0.1:8888",
        api_password="pilot-secret",
        transport=httpx.MockTransport(handler),
    )
    result = await client.health()
    assert result["ok"] is False
    assert result["code"] == "MEDIAFLOW_HEALTH_FAILED"
    assert "private.example" not in json.dumps(result)
