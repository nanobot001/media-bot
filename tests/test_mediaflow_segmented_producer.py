import asyncio
import json

import httpx
import pytest
from starlette.requests import Request

from moviebot.api import web_routes
from moviebot.config import settings
from moviebot.core.mediaflow_adapter import MediaFlowPlaybackRegistry
from moviebot.core.mediaflow_capacity import (
    MediaFlowCapacityConfig,
    MediaFlowCapacityRegistry,
    MediaFlowWorkload,
)
from moviebot.core.mediaflow_segmented import (
    MediaFlowSegmentedError,
    fetch_segment_bytes,
    rewrite_hls_manifest,
)


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/mediaflow/sessions/test/segments/s000000",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8000),
        }
    )


def _manifest(segment_count: int = 14) -> str:
    lines = [
        "#EXTM3U",
        "#EXT-X-TARGETDURATION:10",
        '#EXT-X-MAP:URI="/proxy/transcode/init.mp4?api_password=private"',
    ]
    for index in range(segment_count):
        lines.extend(
            [
                "#EXTINF:10.0,",
                f"/proxy/transcode/segment.mp4?seg={index}&d=private-source&token=private",
            ]
        )
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


def _capacity_registry() -> MediaFlowCapacityRegistry:
    config = MediaFlowCapacityConfig(
        cpu_cores=8.0,
        memory_mb=8192,
        gpu_percent=100.0,
        encoder_slots=2,
        max_heavy_sessions=2,
        safety_factor=1.0,
        baseline_cpu_cores=0.0,
        baseline_memory_mb=0,
        baseline_gpu_percent=0.0,
        profiles={},
        configured_profile_names=frozenset(),
    )
    return MediaFlowCapacityRegistry(config=config)


def _workload() -> MediaFlowWorkload:
    return MediaFlowWorkload(
        workload_class="video_transcode",
        resource_class="heavy_transcode",
        cpu_cores=1.0,
        memory_mb=512,
        gpu_percent=25.0,
        encoder_slots=1,
        heavy=True,
        profile_source="test",
    )


def _create_segmented_session(registry: MediaFlowPlaybackRegistry, variant_id: str) -> str:
    reservation = registry.capacity_registry.reserve(_workload())
    assert reservation["admitted"] is True
    session = registry.create(
        variant_id=variant_id,
        playback_url="http://127.0.0.1:8888/private/playlist.m3u8",
        decision={"decision": "full_transcode", "encoder_required": True},
        mode="transcode_hls",
        ttl_seconds=900,
        capacity_reservation_id=reservation["reservation_id"],
        workload=_workload().as_dict(),
    )
    registry.configure_segmented_manifest(
        session["session_id"],
        manifest_body=_manifest(),
        playlist_url="http://127.0.0.1:8888/private/playlist.m3u8",
        max_segments=32,
    )
    return session["session_id"]


def test_long_manifest_is_opaque_bounded_and_exposes_late_timeline_segments():
    rewritten = rewrite_hls_manifest(
        _manifest(),
        session_id="mfp-public",
        playlist_url="http://127.0.0.1:8888/private/playlist.m3u8",
        max_segments=32,
    )

    assert rewritten.media_segment_count == 14
    assert "s000012" in rewritten.targets
    assert "/api/mediaflow/sessions/mfp-public/segments/s000012" in rewritten.body
    assert "private-source" not in rewritten.body
    assert "api_password" not in rewritten.body
    assert "token=" not in rewritten.body
    assert all(target.startswith("http://127.0.0.1:8888/") for target in rewritten.targets.values())
    assert "private-source" in json.dumps(rewritten.targets)

    with pytest.raises(MediaFlowSegmentedError) as exceeded:
        rewrite_hls_manifest(
            _manifest(),
            session_id="mfp-public",
            playlist_url="http://127.0.0.1:8888/private/playlist.m3u8",
            max_segments=13,
        )
    assert exceeded.value.code == "MEDIAFLOW_SEGMENT_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_segment_fetch_measures_bytes_and_distinguishes_timeout_code():
    async def success_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"playable-media", headers={"content-type": "video/mp4"})

    body, media_type = await fetch_segment_bytes(
        "http://127.0.0.1:8888/private/segment",
        timeout_seconds=1,
        max_bytes=1024,
        timeout_code="MEDIAFLOW_PRODUCER_STARTUP_TIMEOUT",
        transport=httpx.MockTransport(success_handler),
    )
    assert body == b"playable-media"
    assert media_type == "video/mp4"

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(0.2)
            yield b"late"

    async def stalled_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=SlowStream())

    with pytest.raises(MediaFlowSegmentedError) as stalled:
        await fetch_segment_bytes(
            "http://127.0.0.1:8888/private/segment",
            timeout_seconds=0.1,
            max_bytes=1024,
            timeout_code="MEDIAFLOW_PRODUCER_IDLE_TIMEOUT",
            transport=httpx.MockTransport(stalled_handler),
        )
    assert stalled.value.code == "MEDIAFLOW_PRODUCER_IDLE_TIMEOUT"


@pytest.mark.asyncio
async def test_startup_uses_media_bytes_and_idle_failure_releases_only_affected_session(monkeypatch):
    registry = MediaFlowPlaybackRegistry(capacity_registry=_capacity_registry())
    first_id = _create_segmented_session(registry, "variant-first")
    other_id = _create_segmented_session(registry, "variant-other")
    monkeypatch.setattr(web_routes, "mediaflow_playback_registry", registry)
    monkeypatch.setattr(web_routes, "_record_mediaflow_event", lambda **kwargs: None)
    monkeypatch.setattr(web_routes.ReleaseVariantRepository, "get_variant", lambda variant_id: {})
    monkeypatch.setattr(settings, "mediaflow_segment_startup_timeout_seconds", 0.1)
    monkeypatch.setattr(settings, "mediaflow_segment_idle_timeout_seconds", 0.1)

    calls = []

    async def controlled_fetch(target, *, timeout_seconds, max_bytes, timeout_code):
        calls.append((target, timeout_seconds, timeout_code))
        if len(calls) <= 2:
            return b"media-bytes", "video/mp4"
        raise MediaFlowSegmentedError(
            timeout_code,
            "MediaFlow stopped producing media within the configured deadline.",
            retryable=True,
        )

    monkeypatch.setattr(web_routes, "fetch_segment_bytes", controlled_fetch)

    init_response = await web_routes.api_mediaflow_session_segment(first_id, "init", _request())
    init_snapshot = registry.snapshot(first_id)
    assert init_response.status_code == 200
    assert init_snapshot["producer"]["state"] == "manifest_ready"
    assert init_snapshot["producer"]["started_at"] is None
    assert calls[-1][2] == "MEDIAFLOW_PRODUCER_STARTUP_TIMEOUT"

    media_response = await web_routes.api_mediaflow_session_segment(first_id, "s000000", _request())
    started = registry.snapshot(first_id)
    assert media_response.status_code == 200
    assert started["producer"]["state"] == "streaming"
    assert started["producer"]["produced_segment_count"] == 1
    assert started["producer"]["output_bytes"] == len(b"media-bytes")
    assert calls[-1][2] == "MEDIAFLOW_PRODUCER_STARTUP_TIMEOUT"

    failure = await web_routes.api_mediaflow_session_segment(first_id, "s000001", _request())
    assert failure.status_code == 504
    assert failure.headers["x-mediaflow-code"] == "MEDIAFLOW_PRODUCER_IDLE_TIMEOUT"
    assert calls[-1][2] == "MEDIAFLOW_PRODUCER_IDLE_TIMEOUT"
    assert registry.get(first_id) is None
    assert registry.get(other_id) is not None
    assert registry.status()["capacity"]["used"]["heavy_sessions"] == 1
    registry.close(other_id, reason="test_cleanup")
