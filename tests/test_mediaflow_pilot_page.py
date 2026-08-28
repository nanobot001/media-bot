import json
from pathlib import Path

import pytest
from starlette.requests import Request

from moviebot.api import web_routes
from moviebot.config import settings


def _request(host: str = "127.0.0.1") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/mediaflow/pilot",
            "headers": [],
            "client": (host, 12345),
            "server": (host, 8000),
        }
    )


@pytest.mark.asyncio
async def test_pilot_page_api_is_disabled_until_explicitly_enabled(monkeypatch):
    monkeypatch.setattr(settings, "mediaflow_pilot_enabled", False)
    result = await web_routes.api_mediaflow_pilot_info(_request())
    assert result == {
        "ok": False,
        "code": "MEDIAFLOW_PILOT_DISABLED",
        "error": "The MediaFlow pilot is disabled. Set MEDIAFLOW_PILOT_ENABLED=true for local testing.",
    }


@pytest.mark.asyncio
async def test_pilot_page_exposes_fixed_fixture_metadata_and_opaque_playback(monkeypatch):
    monkeypatch.setattr(settings, "mediaflow_pilot_enabled", True)
    monkeypatch.setattr(settings, "mediaflow_api_password", "pilot-secret")

    class FakeMediaFlowClient:
        def __init__(self):
            pass

        async def generate_signed_playback_url(self, destination_url, **kwargs):
            assert destination_url == "http://host.docker.internal:18765/hevc10.mkv"
            assert kwargs["filename"] == "hevc10.mkv"
            return {
                "ok": True,
                "url": "http://127.0.0.1:8888/_opaque/proxy/stream",
                "endpoint": "/proxy/stream",
                "mode": "transcode_stream",
                "expires_in_seconds": 300,
                "requested_mode": "transcode_hls",
                "fallback_reason": "HLS_MANIFEST_UNSAFE",
            }

        async def health(self):
            return {"ok": True, "status": "healthy"}

    monkeypatch.setattr(web_routes, "MediaFlowClient", FakeMediaFlowClient)
    info = await web_routes.api_mediaflow_pilot_info(_request())
    assert info["ok"] is True
    assert {fixture["id"] for fixture in info["fixtures"]} == {
        "compatible",
        "surround",
        "hevc",
        "text-subtitle",
    }

    result = await web_routes.api_mediaflow_pilot_playback(
        web_routes.MediaFlowPilotPlaybackRequest(fixture="hevc"),
        _request(),
    )
    assert result["ok"] is True
    assert result["expected_decision"] == "full_transcode"
    assert result["playback"]["fallback_reason"] == "HLS_MANIFEST_UNSAFE"
    assert "host.docker.internal" not in json.dumps(result)
    assert "pilot-secret" not in json.dumps(result)


@pytest.mark.asyncio
async def test_pilot_page_rejects_non_local_requests(monkeypatch):
    monkeypatch.setattr(settings, "mediaflow_pilot_enabled", True)
    result = await web_routes.api_mediaflow_pilot_info(_request("192.0.2.10"))
    assert result["code"] == "MEDIAFLOW_PILOT_LOCAL_ONLY"


def test_pilot_page_is_static_and_does_not_accept_provider_urls():
    page = Path("src/moviebot/web/mediaflow-pilot.html").read_text(encoding="utf-8")
    assert "Generate &amp; play" in page
    assert "/api/mediaflow/pilot/playback" in page
    assert "/api/mediaflow/pilot/subtitle" in page
    assert "Seek −1s" in page
    assert "const seekStepSeconds = 1;" in page
    assert "Seek −10s" not in page
    assert "provider URL" in page
