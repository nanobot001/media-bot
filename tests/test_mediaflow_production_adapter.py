import json
from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from moviebot.api import web_routes
from moviebot.config import settings
from moviebot.core.mediaflow_capacity import (
    MediaFlowCapacityConfig,
    MediaFlowCapacityRegistry,
    build_workload,
    calculate_measured_profiles,
)
from moviebot.core.availability_service import AvailabilityService
from moviebot.core.mediaflow_adapter import (
    MediaFlowAdapterError,
    MediaFlowPlaybackRegistry,
    MediaFlowProductionAdapter,
    assess_transcode_capacity,
    mediaflow_playback_registry,
)
from moviebot.core.mediaflow_diagnostics import (
    MEDIAFLOW_DECISION_VERSION,
    build_diagnostics,
    project_diagnostics,
    recent_diagnostics,
)
from moviebot.db.connection import get_db_connection, init_db
from moviebot.db.release_variant_repo import ReleaseVariantRepository


def _request(method: str = "GET") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/mediaflow",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8000),
        }
    )


@pytest.fixture(autouse=True)
def mediaflow_test_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "movies.sqlite3"))
    monkeypatch.setattr(settings, "tv_database_path", str(tmp_path / "tv.sqlite3"))
    monkeypatch.setattr(settings, "tv_classic_database_path", str(tmp_path / "classic.sqlite3"))
    monkeypatch.setattr(settings, "mediaflow_production_enabled", True)
    monkeypatch.setattr(settings, "mediaflow_api_password", "production-test-secret")
    monkeypatch.setattr(settings, "mediaflow_url", "http://127.0.0.1:8888")
    monkeypatch.setattr(settings, "mediaflow_expected_version", "2.4.9")
    monkeypatch.setattr(settings, "mediaflow_session_ttl_seconds", 900)
    monkeypatch.setattr(settings, "mediaflow_diagnostics_mode", "summary")
    init_db("movies")
    init_db("tv")
    init_db("tv_classic")
    mediaflow_playback_registry.close_all(reason="test_reset")
    yield
    mediaflow_playback_registry.close_all(reason="test_reset")


def _seed_cached_variant(title: str = "Adapter Movie", year: int = 2024):
    checked_at = datetime.now(timezone.utc).isoformat()
    return ReleaseVariantRepository.upsert_variant(
        domain="movies",
        title=title,
        year=year,
        reference_id="opaque-catalog-reference",
        release_title=f"{title.replace(' ', '.')}.{year}.2160p.WEB-DL.HEVC.DDP5.1.mkv",
        ad_cache_status="cached",
        ad_checked_at=checked_at,
    )


def test_heavy_transcode_capacity_guard_rejects_oversized_sources(monkeypatch):
    monkeypatch.setattr(settings, "mediaflow_max_heavy_transcode_size_bytes", 6 * 1024 * 1024 * 1024)
    monkeypatch.setattr(settings, "mediaflow_max_heavy_transcode_duration_seconds", 7200.0)

    result = assess_transcode_capacity(
        {
            "format": {"size_bytes": 8 * 1024 * 1024 * 1024, "duration_seconds": 7148.7},
        },
        decision={"decision": "full_transcode"},
    )

    assert result["admitted"] is False
    assert result["resource_class"] == "heavy_transcode"
    assert result["reasons"] == ["source_size_exceeds_heavy_transcode_limit"]


def test_diagnostics_modes_are_bounded_and_sanitized(monkeypatch):
    diagnostic = build_diagnostics(
        stage="admission",
        code="MEDIAFLOW_TRANSCODE_TOO_EXPENSIVE",
        retryable=False,
        variant_id="variant-123",
        delivery_decision="full_transcode",
        reasons=["source_size_exceeds_heavy_transcode_limit"],
        source={
            "size_bytes": 8 * 1024 * 1024 * 1024,
            "duration_seconds": 7148.7,
            "video_codec": "hevc",
            "source_url": "https://provider.example/secret",
        },
        workload={
            "workload_class": "video_transcode",
            "profile_source": "conservative_default",
            "cpu_cores": 2.5,
        },
    )

    off = project_diagnostics(diagnostic, mode="off")
    assert off == {
        "schema_version": 1,
        "decision_version": MEDIAFLOW_DECISION_VERSION,
        "stage": "admission",
        "code": "MEDIAFLOW_TRANSCODE_TOO_EXPENSIVE",
        "retryable": False,
        "stale": False,
    }
    summary = project_diagnostics(diagnostic, mode="summary")
    assert summary["reasons"] == ["source_size_exceeds_heavy_transcode_limit"]
    assert "source" not in summary
    detailed = project_diagnostics(diagnostic, mode="detailed")
    assert detailed["source"]["size_bytes"] == 8 * 1024 * 1024 * 1024
    assert "source_url" not in detailed["source"]
    assert "provider.example" not in json.dumps(detailed)

    monkeypatch.setattr(settings, "mediaflow_diagnostics_mode", "invalid")
    assert project_diagnostics(diagnostic)["safe_next_action"] == "choose_another_release_or_external_player"


def test_legacy_diagnostic_events_are_marked_stale():
    projected = recent_diagnostics(
        [
            {
                "event_type": "mediaflow_playback_failed",
                "source": "mediaflow",
                "entity_id": "legacy-variant",
                "occurred_at": "2026-08-30T22:09:05",
                "data_json": json.dumps(
                    {"error_code": "MEDIAFLOW_DELIVERY_UNSAFE", "retryable": False}
                ),
            }
        ],
        limit=1,
        mode="summary",
    )

    assert projected[0]["decision_version"] == "legacy"
    assert projected[0]["stale"] is True
    assert projected[0]["code"] == "MEDIAFLOW_DELIVERY_UNSAFE"


def test_measured_profiles_use_p95_with_explicit_safety_factor():
    profiles = calculate_measured_profiles(
        [
            {
                "workload_class": "video_transcode",
                "healthy": True,
                "cpu_cores": 2.0,
                "memory_mb": 900,
                "gpu_percent": 55,
                "encoder_slots": 1,
            },
            {
                "workload_class": "video_transcode",
                "healthy": True,
                "cpu_cores": 2.5,
                "memory_mb": 1200,
                "gpu_percent": 70,
                "encoder_slots": 1,
            },
            {
                "workload_class": "video_transcode",
                "healthy": False,
                "cpu_cores": 8.0,
                "memory_mb": 1900,
                "gpu_percent": 100,
                "encoder_slots": 1,
            },
        ],
        safety_factor=1.25,
    )

    assert profiles["video_transcode"] == {
        "cpu_cores": 3.12,
        "memory_mb": 1500,
        "gpu_percent": 87.5,
        "encoder_slots": 1,
        "profile_source": "benchmark_p95",
        "sample_count": 2,
    }


def test_configured_measurement_can_admit_large_source_without_size_only_rejection(monkeypatch):
    monkeypatch.setattr(
        settings,
        "mediaflow_capacity_profiles_json",
        json.dumps({
            "video_transcode": {
                "cpu_cores": 2.5,
                "memory_mb": 1024,
                "gpu_percent": 75,
                "encoder_slots": 1,
            },
        }),
    )
    result = assess_transcode_capacity(
        {
            "format": {"size_bytes": 8 * 1024 * 1024 * 1024, "duration_seconds": 7148.7},
            "video": [{"index": 0, "codec_name": "hevc", "bit_depth": 10, "width": 1920, "height": 1080}],
            "audio": [{"index": 1, "codec_name": "dts", "channels": 6}],
        },
        decision={"decision": "full_transcode", "selected_video_index": 0, "selected_audio_index": 1},
    )

    assert result["admitted"] is True
    assert result["reasons"] == []
    assert result["profile_source"] == "configured_measurement"
    assert result["source_size_bytes"] == 8 * 1024 * 1024 * 1024


def test_capacity_registry_rejects_competing_heavy_work_and_releases_on_close():
    config = MediaFlowCapacityConfig(
        cpu_cores=4.0,
        memory_mb=2048,
        gpu_percent=100.0,
        encoder_slots=1,
        max_heavy_sessions=1,
        safety_factor=1.25,
        baseline_cpu_cores=0.5,
        baseline_memory_mb=256,
        baseline_gpu_percent=0.0,
        profiles={
            "video_transcode": {
                "cpu_cores": 2.5,
                "memory_mb": 1024,
                "gpu_percent": 75,
                "encoder_slots": 1,
            },
        },
        configured_profile_names=frozenset({"video_transcode"}),
    )
    capacity = MediaFlowCapacityRegistry(config=config)
    workload = build_workload(
        {
            "format": {"duration_seconds": 3600},
            "video": [{"index": 0, "codec_name": "hevc", "bit_depth": 10}],
            "audio": [{"index": 1, "codec_name": "dts", "channels": 6}],
        },
        decision={
            "decision": "full_transcode",
            "selected_video_index": 0,
            "selected_audio_index": 1,
        },
        capacity_config=config,
    )

    first = capacity.reserve(workload)
    second = capacity.reserve(workload)
    assert first["admitted"] is True
    assert second["admitted"] is False
    assert second["code"] == "MEDIAFLOW_CAPACITY_BUSY"
    assert "encoder_slots_budget_exhausted" in second["reasons"]
    assert capacity.commit(first["reservation_id"], "mfp-session") is True
    assert capacity.release("mfp-session") is True
    assert capacity.reserve(workload)["admitted"] is True


def test_direct_and_remux_work_do_not_reserve_heavy_capacity():
    config = MediaFlowCapacityConfig.from_settings()
    workload = build_workload(
        {
            "format": {"container": "mp4", "duration_seconds": 120},
            "video": [{"index": 0, "codec_name": "h264", "bit_depth": 8}],
            "audio": [{"index": 1, "codec_name": "aac", "channels": 2}],
        },
        decision={"decision": "direct_play", "selected_video_index": 0, "selected_audio_index": 1},
        capacity_config=config,
    )
    registry = MediaFlowCapacityRegistry(config=config)

    result = registry.reserve(workload)

    assert workload.heavy is False
    assert result["admitted"] is True
    assert result["reservation_id"] is None
    assert registry.status()["capacity"]["used"]["heavy_sessions"] == 0


@pytest.mark.asyncio
async def test_capacity_busy_fails_before_signed_url_generation():
    provider_source = "https://provider.example/video.mkv?token=secret"
    config = MediaFlowCapacityConfig(
        cpu_cores=4.0,
        memory_mb=2048,
        gpu_percent=100.0,
        encoder_slots=1,
        max_heavy_sessions=1,
        safety_factor=1.25,
        baseline_cpu_cores=0.5,
        baseline_memory_mb=256,
        baseline_gpu_percent=0.0,
        profiles={
            "video_transcode": {
                "cpu_cores": 2.5,
                "memory_mb": 1024,
                "gpu_percent": 75,
                "encoder_slots": 1,
            },
        },
        configured_profile_names=frozenset({"video_transcode"}),
    )
    capacity_registry = MediaFlowCapacityRegistry(config=config)
    registry = MediaFlowPlaybackRegistry(capacity_registry=capacity_registry)
    occupied_workload = build_workload(
        {
            "format": {"duration_seconds": 3600},
            "video": [{"index": 0, "codec_name": "hevc", "bit_depth": 10}],
            "audio": [{"index": 1, "codec_name": "dts", "channels": 6}],
        },
        decision={"decision": "full_transcode"},
        capacity_config=config,
    )
    occupied = capacity_registry.reserve(occupied_workload)
    assert occupied["admitted"] is True
    assert capacity_registry.commit(occupied["reservation_id"], "occupied-session") is True

    calls = {"generate": 0}

    class FakeMediaFlowClient:
        async def health(self):
            return {
                "ok": True,
                "code": "MEDIAFLOW_HEALTHY",
                "status": "healthy",
                "capabilities": {"force_audio_stereo": True},
            }

        async def generate_signed_playback_url(self, destination_url, **kwargs):
            calls["generate"] += 1
            raise AssertionError("capacity rejection must happen before URL generation")

    class FakeAllDebridClient:
        async def unlock_magnet_stream(self, **kwargs):
            return {
                "stream_url": provider_source,
                "filename": "Movie.2024.1080p.HEVC.DTS.mkv",
                "filesize": 1000,
            }

    async def fake_probe(stream_url):
        return {
            "ok": True,
            "inventory": {
                "format": {"container": "mkv", "duration_seconds": 3600},
                "video": [{"index": 0, "codec_name": "hevc", "bit_depth": 10}],
                "audio": [{"index": 1, "codec_name": "dts", "channels": 6}],
                "subtitles": [],
            },
        }

    adapter = MediaFlowProductionAdapter(
        mediaflow_client_factory=FakeMediaFlowClient,
        alldebrid_client_factory=FakeAllDebridClient,
        resolver=lambda reference_id, domain: "magnet:?xt=urn:btih:" + ("a" * 40),
        probe=fake_probe,
        registry=registry,
    )

    with pytest.raises(MediaFlowAdapterError) as exc_info:
        await adapter.prepare({**_seed_cached_variant(), "domain": "movies"})

    assert exc_info.value.code == "MEDIAFLOW_CAPACITY_BUSY"
    assert exc_info.value.retryable is True
    assert calls["generate"] == 0
    assert capacity_registry.release("occupied-session") is True


@pytest.mark.asyncio
async def test_oversized_heavy_transcode_fails_before_mediaflow_url_generation(monkeypatch):
    monkeypatch.setattr(settings, "mediaflow_diagnostics_mode", "detailed")
    provider_source = "https://provider.example/video.mkv?token=secret"
    calls = {"generate": 0}

    class FakeMediaFlowClient:
        async def health(self):
            return {
                "ok": True,
                "code": "MEDIAFLOW_HEALTHY",
                "status": "healthy",
                "capabilities": {"force_audio_stereo": True},
            }

        async def generate_signed_playback_url(self, destination_url, **kwargs):
            calls["generate"] += 1
            raise AssertionError("capacity rejection must happen before URL generation")

    class FakeAllDebridClient:
        async def unlock_magnet_stream(self, **kwargs):
            return {
                "stream_url": provider_source,
                "filename": "Large.Movie.2024.1080p.HEVC.DTS.mkv",
                "filesize": 8 * 1024 * 1024 * 1024,
            }

    async def fake_probe(stream_url):
        return {
            "ok": True,
            "inventory": {
                "format": {"container": "mkv", "duration_seconds": 7148.7},
                "video": [{"index": 0, "codec_name": "hevc", "pixel_format": "yuv420p10le", "bit_depth": 10}],
                "audio": [{"index": 1, "codec_name": "dts", "channels": 6, "disposition": {"default": True}}],
                "subtitles": [],
            },
        }

    adapter = MediaFlowProductionAdapter(
        mediaflow_client_factory=FakeMediaFlowClient,
        alldebrid_client_factory=FakeAllDebridClient,
        resolver=lambda reference_id, domain: "magnet:?xt=urn:btih:" + ("a" * 40),
        probe=fake_probe,
        registry=MediaFlowPlaybackRegistry(),
    )

    with pytest.raises(MediaFlowAdapterError) as exc_info:
        await adapter.prepare({**_seed_cached_variant(), "domain": "movies"})

    assert exc_info.value.code == "MEDIAFLOW_TRANSCODE_TOO_EXPENSIVE"
    diagnostics = exc_info.value.public_diagnostics()
    assert diagnostics["stage"] == "admission"
    assert diagnostics["reasons"] == ["source_size_exceeds_heavy_transcode_limit"]
    assert diagnostics["source"]["size_bytes"] == 8 * 1024 * 1024 * 1024
    assert diagnostics["source"]["duration_seconds"] == 7148.7
    assert diagnostics["source"]["video_codec"] == "hevc"
    assert diagnostics["workload"]["profile_source"] == "conservative_default"
    assert calls["generate"] == 0


@pytest.mark.asyncio
async def test_disabled_production_status_fails_closed_without_health_call(monkeypatch):
    monkeypatch.setattr(settings, "mediaflow_production_enabled", False)

    class ForbiddenAdapter:
        def __init__(self):
            raise AssertionError("disabled status must not call MediaFlow")

    monkeypatch.setattr(web_routes, "MediaFlowProductionAdapter", ForbiddenAdapter)
    result = await web_routes.api_mediaflow_production_status(_request())

    assert result["ok"] is True
    assert result["enabled"] is False
    assert result["health"] == {
        "ok": False,
        "code": "MEDIAFLOW_PRODUCTION_DISABLED",
    }


def test_adapter_error_sanitizes_codes_and_sensitive_messages():
    error = MediaFlowAdapterError(
        "provider:https://example.invalid/token",
        "Authorization token=https://provider.example/secret",
    )

    assert error.code == "MEDIAFLOW_ADAPTER_FAILED"
    assert error.message == (
        "MediaFlow playback failed without retaining provider details."
    )


@pytest.mark.asyncio
async def test_production_adapter_returns_only_opaque_session_output():
    provider_source = "https://provider.example/video.mkv?token=secret"
    calls = {}

    class FakeMediaFlowClient:
        async def health(self):
            return {
                "ok": True,
                "code": "MEDIAFLOW_HEALTHY",
                "status": "healthy",
                "capabilities": {"force_audio_stereo": True},
            }

        async def generate_signed_playback_url(self, destination_url, **kwargs):
            calls["destination_url"] = destination_url
            calls["kwargs"] = kwargs
            return {
                "ok": True,
                "url": "http://127.0.0.1:8888/_opaque/session/stream",
                "mode": kwargs["mode"],
            }

    class FakeAllDebridClient:
        async def unlock_magnet_stream(self, **kwargs):
            calls["magnet"] = kwargs["magnet_link"]
            return {
                "stream_url": provider_source,
                "filename": "Adapter.Movie.2024.2160p.WEB-DL.HEVC.DDP5.1.mkv",
                "filesize": 1000,
            }

    async def fake_probe(stream_url):
        assert stream_url == provider_source
        return {
            "ok": True,
            "inventory": {
                "format": {"container": "mkv", "duration_seconds": 3600.5},
                "video": [{"index": 0, "codec_name": "hevc", "pixel_format": "yuv420p10le", "bit_depth": 10, "hdr": {"is_hdr": False}}],
                "audio": [{"index": 1, "codec_name": "eac3", "channels": 6, "disposition": {"default": True}}],
                "subtitles": [],
            },
        }

    registry = MediaFlowPlaybackRegistry()
    adapter = MediaFlowProductionAdapter(
        mediaflow_client_factory=FakeMediaFlowClient,
        alldebrid_client_factory=FakeAllDebridClient,
        resolver=lambda reference_id, domain: "magnet:?xt=urn:btih:" + ("a" * 40),
        probe=fake_probe,
        registry=registry,
    )
    variant = {**_seed_cached_variant(), "domain": "movies", "season": 0, "episode": 0}
    result = await adapter.prepare(variant, supports_hls=False)

    assert result["decision"]["decision"] == "full_transcode"
    assert result["decision"]["encoder_required"] is True
    assert result["mode"] == "transcode_stream"
    assert result["duration_seconds"] == 3600.5
    assert calls["kwargs"]["force_audio_stereo"] is True
    assert calls["destination_url"] == provider_source
    assert calls["magnet"].startswith("magnet:")
    public_json = json.dumps(result)
    assert "provider.example" not in public_json
    assert "production-test-secret" not in public_json
    assert registry.resolve(result["session_id"]) == "http://127.0.0.1:8888/_opaque/session/stream"
    assert registry.close(result["session_id"])["cleanup_result"] == "complete"
    assert registry.status()["capacity"]["used"]["heavy_sessions"] == 0


@pytest.mark.asyncio
async def test_seek_rotates_session_url_without_reunlocking_source():
    provider_source = "https://provider.example/video.mkv?token=secret"
    generated = []

    class FakeMediaFlowClient:
        async def health(self):
            return {
                "ok": True,
                "code": "MEDIAFLOW_HEALTHY",
                "status": "healthy",
                "capabilities": {"force_audio_stereo": True},
            }

        async def generate_signed_playback_url(self, destination_url, **kwargs):
            generated.append((destination_url, kwargs))
            return {
                "ok": True,
                "url": f"http://127.0.0.1:8888/_opaque/seek-{len(generated)}",
                "mode": kwargs["mode"],
            }

    registry = MediaFlowPlaybackRegistry()
    session = registry.create(
        variant_id="variant-seek",
        playback_url="http://127.0.0.1:8888/_opaque/initial",
        decision={"decision": "full_transcode", "accelerator": "nvenc"},
        mode="transcode_stream",
        ttl_seconds=900,
        source_url=provider_source,
        filename="movie.mkv",
        force_audio_stereo=True,
        duration_seconds=7200.0,
    )
    adapter = MediaFlowProductionAdapter(
        mediaflow_client_factory=FakeMediaFlowClient,
        registry=registry,
    )

    result = await adapter.seek(session["session_id"], 1234.5)

    assert result["start_seconds"] == 1234.5
    assert result["duration_seconds"] == 7200.0
    assert result["playback_status"] == "seeking"
    assert registry.resolve(session["session_id"]) == "http://127.0.0.1:8888/_opaque/seek-1"
    assert generated[0][0] == provider_source
    assert generated[0][1]["start_seconds"] == 1234.5
    assert generated[0][1]["force_audio_stereo"] is True
    assert "provider.example" not in json.dumps(result)


@pytest.mark.asyncio
async def test_multichannel_aac_fails_closed_without_stereo_capability():
    provider_source = "https://provider.example/video.mkv?token=secret"

    class FakeMediaFlowClient:
        async def health(self):
            return {
                "ok": True,
                "code": "MEDIAFLOW_HEALTHY",
                "status": "healthy",
                "capabilities": {"force_audio_stereo": False},
            }

        async def generate_signed_playback_url(self, destination_url, **kwargs):
            raise AssertionError("URL generation must not run without stereo capability")

    class FakeAllDebridClient:
        async def unlock_magnet_stream(self, **kwargs):
            return {"stream_url": provider_source, "filename": "movie.mkv", "filesize": 1000}

    async def fake_probe(stream_url):
        return {
            "ok": True,
            "inventory": {
                "format": {"container": "mkv"},
                "video": [{"index": 0, "codec_name": "hevc", "pixel_format": "yuv420p10le", "bit_depth": 10}],
                "audio": [{"index": 1, "codec_name": "aac", "channels": 6, "disposition": {"default": True}}],
                "subtitles": [],
            },
        }

    adapter = MediaFlowProductionAdapter(
        mediaflow_client_factory=FakeMediaFlowClient,
        alldebrid_client_factory=FakeAllDebridClient,
        resolver=lambda reference_id, domain: "magnet:?xt=urn:btih:" + ("a" * 40),
        probe=fake_probe,
        registry=MediaFlowPlaybackRegistry(),
    )

    with pytest.raises(MediaFlowAdapterError) as exc_info:
        await adapter.prepare({**_seed_cached_variant(), "domain": "movies"})

    assert exc_info.value.code == "MEDIAFLOW_AUDIO_STEREO_UNSUPPORTED"


@pytest.mark.asyncio
async def test_production_route_preserves_state_b_and_records_candidate(monkeypatch):
    variant = _seed_cached_variant()

    async def eligible_movie(**kwargs):
        return {"eligible": True, "reason": "ELIGIBLE"}

    class FakeAdapter:
        async def prepare(self, selected, **kwargs):
            assert selected["variant_id"] == variant["variant_id"]
            return {
                "session_id": "mfp-opaque",
                "decision": {
                    "decision": "full_transcode",
                    "encoder_required": True,
                    "accelerator": "not_started",
                    "output": {"container": "fMP4", "video_codec": "h264", "audio_codec": "aac"},
                },
                "mode": "transcode_stream",
                "fallback_reason": None,
                "filename": variant["release_title"],
                "filesize": 1000,
                "mime_type": "video/mp4",
                "expires_at": "2026-08-29T12:15:00+00:00",
                "runtime_metrics": {"accelerator": "not_started"},
            }

    monkeypatch.setattr(web_routes, "_evaluate_movie_request", eligible_movie)
    monkeypatch.setattr(web_routes, "MediaFlowProductionAdapter", FakeAdapter)
    req = web_routes.MediaFlowProductionPlaybackRequest(
        release_variant_id=variant["variant_id"],
        domain="movies",
        title="Adapter Movie",
        year=2024,
        scope_type="movie",
    )
    result = await web_routes.api_mediaflow_production_playback(req, _request("POST"))

    assert result["ok"] is True
    assert result["stream_url"] == "/api/mediaflow/sessions/mfp-opaque/stream"
    assert result["mediaflow_playback_ready"] is True
    assert result["browser_stream_ready"] is False
    assert result["availability_state"] == "ad_cached"
    serialized = json.dumps(result)
    assert "opaque-catalog-reference" not in serialized
    assert "magnet:" not in serialized
    assert "production-test-secret" not in serialized
    stored = ReleaseVariantRepository.get_variant(variant["variant_id"])
    assert stored["mediaflow_status"] == "candidate"
    assert AvailabilityService.inspect(
        domain="movies", title="Adapter Movie", year=2024
    )["availability_state"] == "ad_cached"


@pytest.mark.asyncio
async def test_browser_playing_event_verifies_mediaflow_without_promoting_c():
    variant = _seed_cached_variant()
    session = mediaflow_playback_registry.create(
        variant_id=variant["variant_id"],
        playback_url="http://127.0.0.1:8888/_opaque/session/stream",
        decision={"decision": "full_transcode", "accelerator": "not_started"},
        mode="transcode_stream",
        ttl_seconds=900,
    )
    event = await web_routes.api_mediaflow_session_event(
        session["session_id"],
        web_routes.MediaFlowSessionEventRequest(
            event="playing",
            metrics={
                "accelerator": "nvenc",
                "command": "ffmpeg -i https://provider.example/secret",
                "api_password": "leak",
            },
        ),
        _request("POST"),
    )
    assert event["ok"] is True
    assert event["runtime_metrics"]["accelerator"] == "nvenc"
    assert "command" not in event["runtime_metrics"]
    stored = ReleaseVariantRepository.get_variant(variant["variant_id"])
    assert stored["mediaflow_status"] == "verified"
    projection = AvailabilityService.inspect(
        domain="movies", title="Adapter Movie", year=2024
    )
    assert projection["availability_state"] == "ad_cached"
    assert projection["browser_stream_ready"] is False


@pytest.mark.asyncio
async def test_session_redirect_and_close_expose_no_provider_source():
    variant = _seed_cached_variant()
    session = mediaflow_playback_registry.create(
        variant_id=variant["variant_id"],
        playback_url="http://127.0.0.1:8888/_opaque/session/stream",
        decision={"decision": "remux_copy"},
        mode="transcode_stream",
        ttl_seconds=900,
    )
    response = await web_routes.api_mediaflow_session_stream(
        session["session_id"], _request()
    )
    assert response.status_code == 307
    assert response.headers["location"] == "http://127.0.0.1:8888/_opaque/session/stream"
    assert response.headers["cache-control"] == "no-store"

    closed = await web_routes.api_mediaflow_session_close(
        session["session_id"], _request("DELETE")
    )
    assert closed["cleanup_result"] == "complete"
    assert mediaflow_playback_registry.resolve(session["session_id"]) is None
    with get_db_connection() as conn:
        event = conn.execute(
            "SELECT event_type, data_json FROM events ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert event["event_type"] == "mediaflow_playback_closed"
    cleanup = json.loads(event["data_json"])
    assert cleanup["upstream_disconnect_requested"] is True
    assert cleanup["active_workers"] is None


@pytest.mark.asyncio
async def test_session_seek_route_returns_opaque_stream_reference(monkeypatch):
    variant = _seed_cached_variant()

    class FakeAdapter:
        async def seek(self, session_id, start_seconds):
            assert session_id == "mfp-seek"
            assert start_seconds == 456.75
            return {
                "session_id": session_id,
                "variant_id": variant["variant_id"],
                "start_seconds": start_seconds,
                "duration_seconds": 3600.5,
                "mode": "transcode_stream",
            }

    monkeypatch.setattr(web_routes, "MediaFlowProductionAdapter", FakeAdapter)
    result = await web_routes.api_mediaflow_session_seek(
        "mfp-seek",
        web_routes.MediaFlowSessionSeekRequest(start_seconds=456.75),
        _request("POST"),
    )

    assert result["ok"] is True
    assert result["stream_url"] == "/api/mediaflow/sessions/mfp-seek/stream"
    assert result["start_seconds"] == 456.75
    assert result["duration_seconds"] == 3600.5
    assert "provider.example" not in json.dumps(result)


@pytest.mark.asyncio
async def test_missing_or_uncached_variant_fails_before_adapter(monkeypatch):
    class ForbiddenAdapter:
        def __init__(self):
            raise AssertionError("adapter must not be constructed")

    monkeypatch.setattr(web_routes, "MediaFlowProductionAdapter", ForbiddenAdapter)
    missing = await web_routes.api_mediaflow_production_playback(
        web_routes.MediaFlowProductionPlaybackRequest(
            release_variant_id="f" * 64,
            domain="movies",
            title="Missing",
            year=2024,
        ),
        _request("POST"),
    )
    assert missing["code"] == "MEDIAFLOW_VARIANT_NOT_FOUND"

    checked_at = datetime.now(timezone.utc).isoformat()
    uncached = ReleaseVariantRepository.upsert_variant(
        domain="movies",
        title="Uncached Movie",
        year=2024,
        reference_id="uncached-reference",
        release_title="Uncached.Movie.2024.1080p.WEB-DL.x264.AAC.mp4",
        ad_cache_status="not_cached",
        ad_checked_at=checked_at,
    )
    rejected = await web_routes.api_mediaflow_production_playback(
        web_routes.MediaFlowProductionPlaybackRequest(
            release_variant_id=uncached["variant_id"],
            domain="movies",
            title="Uncached Movie",
            year=2024,
        ),
        _request("POST"),
    )
    assert rejected["code"] == "MEDIAFLOW_VARIANT_NOT_FRESHLY_CACHED"


@pytest.mark.asyncio
async def test_failure_diagnostics_are_persisted_and_available_from_local_route(monkeypatch):
    monkeypatch.setattr(settings, "mediaflow_diagnostics_mode", "detailed")
    variant = _seed_cached_variant(title="Diagnostic Movie")

    async def eligible_movie(**kwargs):
        return {"eligible": True, "reason_code": "ELIGIBLE"}

    class RejectingAdapter:
        async def prepare(self, selected, **kwargs):
            raise MediaFlowAdapterError(
                "MEDIAFLOW_TRANSCODE_TOO_EXPENSIVE",
                "This release exceeds the current measured MediaFlow capacity.",
                stage="admission",
                diagnostics={
                    "variant_id": selected["variant_id"],
                    "delivery_decision": "full_transcode",
                    "reasons": ["duration_exceeds_heavy_transcode_limit"],
                    "source": {
                        "size_bytes": 1829205120,
                        "duration_seconds": 7500.0,
                        "video_codec": "hevc",
                        "bit_depth": 10,
                        "audio_codec": "eac3",
                        "audio_channels": 6,
                    },
                    "workload": {
                        "workload_class": "video_transcode",
                        "profile_source": "conservative_default",
                    },
                },
            )

    monkeypatch.setattr(web_routes, "_evaluate_movie_request", eligible_movie)
    monkeypatch.setattr(web_routes, "MediaFlowProductionAdapter", RejectingAdapter)
    response = await web_routes.api_mediaflow_production_playback(
        web_routes.MediaFlowProductionPlaybackRequest(
            release_variant_id=variant["variant_id"],
            domain="movies",
            title="Diagnostic Movie",
            year=2024,
            scope_type="movie",
        ),
        _request("POST"),
    )

    assert response["code"] == "MEDIAFLOW_TRANSCODE_TOO_EXPENSIVE"
    assert response["stage"] == "admission"
    assert response["diagnostics"]["source"]["size_bytes"] == 1829205120
    with get_db_connection() as conn:
        event = conn.execute(
            "SELECT data_json FROM events WHERE event_type = 'mediaflow_playback_failed' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    stored = json.loads(event["data_json"])
    assert stored["diagnostics"]["decision_version"] == MEDIAFLOW_DECISION_VERSION
    assert "provider" not in json.dumps(stored).lower()

    diagnostics = await web_routes.api_mediaflow_diagnostics(_request(), limit=10)
    assert diagnostics["ok"] is True
    assert diagnostics["mode"] == "detailed"
    assert diagnostics["attempts"][0]["stage"] == "admission"
    assert diagnostics["attempts"][0]["source"]["video_codec"] == "hevc"

    monkeypatch.setattr(settings, "mediaflow_diagnostics_mode", "off")
    minimal = await web_routes.api_mediaflow_diagnostics(_request(), limit=10)
    assert set(minimal["attempts"][0]) == {
        "schema_version",
        "decision_version",
        "stage",
        "code",
        "retryable",
        "stale",
        "event_type",
    }


@pytest.mark.asyncio
async def test_mediaflow_diagnostics_route_is_local_only():
    remote_request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/mediaflow/diagnostics",
            "headers": [],
            "client": ("192.0.2.10", 12345),
            "server": ("127.0.0.1", 8000),
        }
    )

    response = await web_routes.api_mediaflow_diagnostics(remote_request, limit=10)
    assert response["ok"] is False
    assert response["code"] == "MEDIAFLOW_DIAGNOSTICS_LOCAL_ONLY"


def test_mediaflow_events_are_sanitized():
    with get_db_connection() as conn:
        rows = conn.execute("SELECT COUNT(*) AS count FROM events").fetchone()
    assert rows["count"] == 0
