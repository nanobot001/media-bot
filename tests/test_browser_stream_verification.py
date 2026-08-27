import json
from pathlib import Path

import pytest

from moviebot.adapters.alldebrid_client import AllDebridClient, AllDebridProbeCleanupError
from moviebot.api import web_routes
from moviebot.config import settings
from moviebot.core import browser_stream_verifier as verifier
from moviebot.db.cache_prewarm_repo import CachePrewarmRepository
from moviebot.db.connection import init_db


@pytest.fixture
def verification_db(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "movies.sqlite3"))
    monkeypatch.setattr(settings, "tv_database_path", str(tmp_path / "tv.sqlite3"))
    monkeypatch.setattr(settings, "tv_classic_database_path", str(tmp_path / "classic.sqlite3"))
    init_db("movies")
    init_db("tv")
    init_db("tv_classic")


@pytest.mark.asyncio
async def test_ambiguous_actual_file_uses_ffprobe_evidence(monkeypatch):
    async def fake_probe(stream_url, *, actual_filename, **kwargs):
        assert stream_url == "https://provider.test/direct"
        assert actual_filename.endswith(".mp4")
        return {
            "ok": True,
            "code": "BROWSER_CODEC_VERIFIED",
            "evidence_source": "ffprobe",
            "probe": {
                "format": {"format_name": "mov,mp4,m4a"},
                "streams": [
                    {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p"},
                    {"codec_type": "audio", "codec_name": "aac"},
                ],
            },
            "audio_track_present": True,
        }

    monkeypatch.setattr(verifier, "probe_unlocked_url", fake_probe)
    result = await verifier.verify_stream_payload({
        "stream_url": "https://provider.test/direct",
        "filename": "Scary.Movie.2026.1080p.WEBRip.mp4",
        "file_id": 7,
        "filesize": 123,
    })

    assert result["verified"] is True
    assert result["evidence_source"] == "ffprobe"
    assert result["file_id"] == 7
    assert result["audio_track_present"] is True


@pytest.mark.asyncio
async def test_ffprobe_success_keeps_url_out_of_evidence(monkeypatch):
    calls = []

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return (
                json.dumps({
                    "format": {
                        "format_name": "mov,mp4,m4a",
                        "filename": "https://private.example/should-not-persist",
                    },
                    "streams": [
                        {"codec_type": "video", "codec_name": "h264", "profile": "High", "pix_fmt": "yuv420p"},
                        {"codec_type": "audio", "codec_name": "aac"},
                    ],
                }).encode(),
                b"",
            )

    async def fake_create(*args, **kwargs):
        calls.append(args)
        return FakeProcess()

    monkeypatch.setattr(verifier.shutil, "which", lambda name: "ffprobe.exe")
    monkeypatch.setattr(verifier.asyncio, "create_subprocess_exec", fake_create)
    result = await verifier.probe_unlocked_url(
        "https://private.example/direct-token",
        actual_filename="Scary.Movie.2026.1080p.WEBRip.mp4",
    )

    assert result["ok"] is True
    assert result["probe"]["format"] == {"format_name": "mov,mp4,m4a"}
    assert "private.example" not in json.dumps(result)
    assert calls and calls[0][-1] == "https://private.example/direct-token"


@pytest.mark.asyncio
async def test_ffprobe_timeout_is_retryable(monkeypatch):
    class FakeProcess:
        returncode = None
        killed = False
        calls = 0

        async def communicate(self):
            self.calls += 1
            if self.calls == 1:
                raise verifier.asyncio.TimeoutError()
            return b"", b""

        def kill(self):
            self.killed = True

    process = FakeProcess()

    async def fake_create(*args, **kwargs):
        return process

    monkeypatch.setattr(verifier.shutil, "which", lambda name: "ffprobe.exe")
    monkeypatch.setattr(verifier.asyncio, "create_subprocess_exec", fake_create)
    result = await verifier.probe_unlocked_url(
        "https://provider.test/direct",
        actual_filename="Scary.Movie.2026.1080p.WEBRip.mp4",
        timeout_seconds=0.01,
    )

    assert result["code"] == "FFPROBE_TIMEOUT"
    assert result["retryable"] is True
    assert process.killed is True


def test_browser_proof_requires_durable_evidence(verification_db):
    CachePrewarmRepository.upsert(
        domain="movies",
        title="Scary Movie",
        year=2026,
        season=0,
        reference_id="download-ref",
        release_title="Scary.Movie.2026.1080p.WEBRip.x264.AAC.mp4",
        cached=True,
    )
    unverified = CachePrewarmRepository.get("movies", "Scary Movie", year=2026)
    assert unverified["browser_stream_ready"] is False

    CachePrewarmRepository.update_browser_stream_candidate(
        domain="movies",
        title="Scary Movie",
        year=2026,
        season=0,
        reference_id="browser-ref",
        release_title="Scary.Movie.2026.1080p.WEBRip.x264.AAC.mp4",
        browser_verification={
            "status": "verified_browser_ready",
            "reference_id": "browser-ref",
            "actual_filename": "Scary.Movie.2026.1080p.WEBRip.x264.AAC.mp4",
            "evidence_source": "actual_filename",
            "audio_track_present": True,
        },
    )
    verified = CachePrewarmRepository.get("movies", "Scary Movie", year=2026)
    assert verified["browser_stream_ready"] is True

    CachePrewarmRepository.upsert(
        domain="movies",
        title="Scary Movie",
        year=2026,
        season=0,
        reference_id="download-ref-2",
        release_title="Scary.Movie.2026.1080p.WEBRip.x264.AAC.mp4",
        cached=True,
        data={"purpose": "generic_cloud_cache"},
    )
    preserved = CachePrewarmRepository.get("movies", "Scary Movie", year=2026)
    assert preserved["browser_stream_ready"] is True
    assert preserved["data"]["browser_verification"]["reference_id"] == "browser-ref"

    CachePrewarmRepository.batch_update_cache_status([{
        "id": "movies:scarymovie:0:2026",
        "cached": False,
        "was_cached": True,
    }])
    dropped = CachePrewarmRepository.get("movies", "Scary Movie", year=2026)
    assert dropped["browser_stream_ready"] is False


def test_discovery_promotes_release_label_browser_copy_and_exposes_both_candidates(verification_db):
    CachePrewarmRepository.upsert(
        domain="movies",
        title="Scary Movie",
        year=2026,
        season=0,
        reference_id="download-ref",
        release_title="Scary Movie Extended Cut 2026 1080p WEB-DL HEVC x265 10Bit DDP5.1",
        cached=True,
        size_bytes=5_000_000_000,
    )
    CachePrewarmRepository.upsert(
        domain="movies",
        title="Scary Movie (2026) [1080p] [WEBRip] [5.1]",
        year=2026,
        season=0,
        reference_id="browser-ref",
        release_title="Scary.Movie.2026.1080p.WEBRip.x264.AAC5.1-[YTS.GG - YTS.BZ].mp4",
        cached=True,
        size_bytes=1_800_000_000,
        browser_stream_reference_id="browser-ref",
        browser_stream_release_title="Scary.Movie.2026.1080p.WEBRip.x264.AAC5.1-[YTS.GG - YTS.BZ].mp4",
        browser_verification={
            "verified": True,
            "verification_code": "BROWSER_FILENAME_VERIFIED",
            "evidence_source": "actual_filename",
            "actual_filename": "Scary.Movie.2026.1080p.WEBRip.x264.AAC5.1-[YTS.GG - YTS.BZ].mp4",
            "audio_track_present": True,
        },
    )

    state = web_routes._movie_stream_state({"title": "Scary Movie", "year": 2026})

    assert state["browser_stream_ready"] is True
    assert state["instant_stream_status"] == "browser_ready"
    assert state["stream_reference_id"] == "browser-ref"
    assert state["download_reference_id"] == "download-ref"
    assert state["browser_stream_candidate"]["release_title"].endswith(".mp4")
    assert state["browser_stream_candidate"]["video_codec"] == "x264"
    assert state["browser_stream_candidate"]["audio_codec"].startswith("AAC")
    assert state["download_candidate"]["video_codec"] == "HEVC (x265)"
    assert state["selected_stream_candidate"]["role"] == "browser"


def test_direct_browser_update_normalizes_legacy_verifier_status(verification_db):
    CachePrewarmRepository.update_browser_stream_candidate(
        domain="movies",
        title="Scary Movie",
        year=2026,
        season=0,
        reference_id="browser-ref",
        release_title="Scary.Movie.2026.1080p.WEBRip.x264.AAC.mp4",
        browser_verification={
            "verified": True,
            "verification_code": "BROWSER_FILENAME_VERIFIED",
            "evidence_source": "actual_filename",
            "actual_filename": "Scary.Movie.2026.1080p.WEBRip.x264.AAC.mp4",
        },
    )

    verified = CachePrewarmRepository.get("movies", "Scary Movie", year=2026)
    assert verified["browser_stream_ready"] is True
    assert verified["data"]["browser_verification"]["status"] == "verified_browser_ready"


def test_discovery_modal_explains_selected_browser_and_download_copies():
    app_js = Path("src/moviebot/web/app.js").read_text(encoding="utf-8")
    index_html = Path("src/moviebot/web/index.html").read_text(encoding="utf-8")

    assert "renderDetailStreamCandidates" in app_js
    assert "USED BY STREAM NOW" in app_js
    assert "modal-stream-candidates" in index_html


@pytest.mark.asyncio
async def test_unready_probe_deletes_only_new_owned_magnet(monkeypatch):
    client = AllDebridClient()
    client.api_key = "test-key"
    monkeypatch.setattr(client, "_get_provider_magnets", lambda: _async_value([
        {"id": "existing", "hash": "old-hash"},
    ]))
    monkeypatch.setattr(client, "upload_magnet", lambda magnet: _async_value({
        "id": "new-probe", "hash": "new-hash", "ready": False,
    }))
    deleted = []

    async def fake_delete(provider_id):
        deleted.append(provider_id)
        return True

    monkeypatch.setattr(client, "delete_cloud_transfer", fake_delete)

    with pytest.raises(ValueError):
        await client.unlock_magnet_stream("magnet:?xt=urn:btih:new-hash")
    assert deleted == ["new-probe"]


@pytest.mark.asyncio
async def test_existing_or_unknown_provider_state_is_never_deleted(monkeypatch):
    client = AllDebridClient()
    client.api_key = "test-key"
    deleted = []

    async def fake_delete(provider_id):
        deleted.append(provider_id)
        return True

    monkeypatch.setattr(client, "delete_cloud_transfer", fake_delete)
    monkeypatch.setattr(client, "upload_magnet", lambda magnet: _async_value({
        "id": "existing", "hash": "same-hash", "ready": False,
    }))
    monkeypatch.setattr(client, "_get_provider_magnets", lambda: _async_value([
        {"id": "existing", "hash": "same-hash"},
    ]))
    with pytest.raises(ValueError):
        await client.unlock_magnet_stream("magnet:?xt=urn:btih:same-hash")

    monkeypatch.setattr(client, "_get_provider_magnets", lambda: _async_value(None))
    monkeypatch.setattr(client, "upload_magnet", lambda magnet: _async_value({
        "id": "unknown-state", "hash": "unknown-hash", "ready": False,
    }))
    with pytest.raises(ValueError):
        await client.unlock_magnet_stream("magnet:?xt=urn:btih:unknown-hash")
    assert deleted == []


@pytest.mark.asyncio
async def test_probe_cleanup_failure_is_retryable(monkeypatch):
    client = AllDebridClient()
    client.api_key = "test-key"
    monkeypatch.setattr(client, "_get_provider_magnets", lambda: _async_value([]))
    monkeypatch.setattr(client, "upload_magnet", lambda magnet: _async_value({
        "id": "new-probe", "hash": "new-hash", "ready": False,
    }))

    async def failed_delete(provider_id):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(client, "delete_cloud_transfer", failed_delete)
    with pytest.raises(AllDebridProbeCleanupError) as exc_info:
        await client.unlock_magnet_stream("magnet:?xt=urn:btih:new-hash")
    assert exc_info.value.code == "PROBE_CLEANUP_FAILED"
    assert exc_info.value.retryable is True


async def _async_value(value):
    return value
