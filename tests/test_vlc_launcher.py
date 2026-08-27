from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from moviebot.api import web_routes


def _local_request():
    return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))


@pytest.mark.asyncio
async def test_vlc_launcher_starts_local_process_with_https_url(monkeypatch):
    executable = r"C:\Program Files\VideoLAN\VLC\vlc.exe"
    stream_url = "https://cdn.example.test/video.mkv?token=temporary"
    process = SimpleNamespace(pid=4321)
    popen = Mock(return_value=process)

    monkeypatch.setattr(web_routes, "_find_vlc_executable", lambda: executable)
    monkeypatch.setattr(web_routes.subprocess, "Popen", popen)

    result = await web_routes.api_open_vlc(
        web_routes.VlcLaunchRequest(stream_url=stream_url),
        _local_request(),
    )

    assert result == {"ok": True, "player": "vlc", "status": "started", "pid": 4321}
    args, kwargs = popen.call_args
    assert args[0] == [executable, stream_url]
    assert kwargs["shell"] is False
    assert kwargs["close_fds"] is True


@pytest.mark.asyncio
async def test_vlc_launcher_rejects_non_https_before_process_lookup(monkeypatch):
    find_vlc = Mock(side_effect=AssertionError("VLC lookup should not run"))
    popen = Mock(side_effect=AssertionError("VLC should not start"))
    monkeypatch.setattr(web_routes, "_find_vlc_executable", find_vlc)
    monkeypatch.setattr(web_routes.subprocess, "Popen", popen)

    result = await web_routes.api_open_vlc(
        web_routes.VlcLaunchRequest(stream_url="vlc://https://cdn.example.test/video.mkv"),
        _local_request(),
    )

    assert result["ok"] is False
    assert result["code"] == "INVALID_STREAM_URL"
    find_vlc.assert_not_called()
    popen.assert_not_called()


@pytest.mark.asyncio
async def test_vlc_launcher_reports_missing_vlc_without_exposing_path(monkeypatch):
    monkeypatch.setattr(web_routes, "_find_vlc_executable", lambda: None)
    stream_url = "https://cdn.example.test/video.mkv"

    result = await web_routes.api_open_vlc(
        web_routes.VlcLaunchRequest(stream_url=stream_url),
        _local_request(),
    )

    assert result["ok"] is False
    assert result["code"] == "VLC_NOT_FOUND"
    assert stream_url not in result["error"]


@pytest.mark.asyncio
async def test_vlc_launcher_is_local_only(monkeypatch):
    find_vlc = Mock(side_effect=AssertionError("VLC lookup should not run"))
    monkeypatch.setattr(web_routes, "_find_vlc_executable", find_vlc)

    result = await web_routes.api_open_vlc(
        web_routes.VlcLaunchRequest(stream_url="https://cdn.example.test/video.mkv"),
        SimpleNamespace(client=SimpleNamespace(host="192.168.1.20")),
    )

    assert result["ok"] is False
    assert result["code"] == "LOCAL_PLAYER_ONLY"
    find_vlc.assert_not_called()


def test_web_vlc_action_uses_local_api_instead_of_custom_protocol():
    app_js = Path("src/moviebot/web/app.js").read_text(encoding="utf-8")

    assert "fetch('/api/player/vlc'" in app_js
    assert "window.location.href = `vlc://${url}`" not in app_js
