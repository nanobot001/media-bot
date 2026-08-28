import json

import pytest

from moviebot.core import mediaflow_pilot as pilot


def _raw_probe(*, container="mp4", video_codec="h264", audio_codec="aac", subtitle_codec=None):
    streams = [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": video_codec,
            "profile": "High",
            "level": 40,
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "24000/1001",
            "pix_fmt": "yuv420p",
            "bits_per_raw_sample": "8",
            "color_primaries": "bt709",
            "color_transfer": "bt709",
            "color_space": "bt709",
            "disposition": {"default": 1, "forced": 0},
        },
        {
            "index": 1,
            "codec_type": "audio",
            "codec_name": audio_codec,
            "channels": 6,
            "channel_layout": "5.1",
            "sample_rate": "48000",
            "bit_rate": "640000",
            "tags": {"language": "eng", "title": "Main mix"},
            "disposition": {"default": 1, "forced": 0},
        },
    ]
    if subtitle_codec:
        streams.append({
            "index": 2,
            "codec_type": "subtitle",
            "codec_name": subtitle_codec,
            "tags": {"language": "eng", "title": "English"},
            "disposition": {"default": 0, "forced": 1},
        })
    return {
        "format": {
            "format_name": container,
            "format_long_name": "Fixture media",
            "duration": "120.5",
            "start_time": "0",
            "bit_rate": "5000000",
            "size": "75000000",
            "seekable": "1",
            "filename": "https://provider.example/private?token=secret",
        },
        "streams": streams,
    }


def test_sanitize_probe_reports_complete_non_sensitive_inventory():
    inventory = pilot.sanitize_probe(_raw_probe(subtitle_codec="subrip"))
    serialized = json.dumps(inventory)

    assert inventory["format"]["container"] == "mp4"
    assert inventory["duration_seconds"] == 120.5
    assert inventory["seekable"] is True
    assert inventory["video"][0]["width"] == 1920
    assert inventory["video"][0]["bit_depth"] == 8
    assert inventory["audio"][0]["language"] == "eng"
    assert inventory["audio"][0]["channel_layout"] == "5.1"
    assert inventory["subtitles"][0]["classification"] == "text"
    assert inventory["subtitles"][0]["is_text"] is True
    assert "provider.example" not in serialized
    assert "secret" not in serialized
    assert "filename" not in serialized


def test_direct_play_control_does_not_start_an_encoder():
    inventory = pilot.sanitize_probe(_raw_probe())
    decision = pilot.choose_delivery_decision(inventory, delivery_mode="direct", target_audio_channels="5.1")

    assert decision["decision"] == pilot.DIRECT_PLAY
    assert decision["encoder_required"] is False
    assert decision["video_transcode_required"] is False
    assert decision["audio_transcode_required"] is False
    assert decision["selected_audio_index"] == 1


def test_hls_compatible_streams_are_remuxed_without_reencoding():
    inventory = pilot.sanitize_probe(_raw_probe())
    decision = pilot.choose_delivery_decision(inventory, delivery_mode="hls", target_audio_channels="5.1")

    assert decision["decision"] == pilot.REMUX_COPY
    assert decision["encoder_required"] is False
    assert decision["output"] == {"container": "fMP4", "video_codec": "h264", "audio_codec": "aac"}


def test_incompatible_surround_audio_uses_audio_only_transcode():
    inventory = pilot.sanitize_probe(_raw_probe(audio_codec="eac3"))
    decision = pilot.choose_delivery_decision(inventory, audio_index=1, target_audio_channels="stereo")

    assert decision["decision"] == pilot.AUDIO_TRANSCODE
    assert decision["video_transcode_required"] is False
    assert decision["audio_transcode_required"] is True
    assert decision["output"]["video_codec"] == "h264"
    assert decision["output"]["audio_codec"] == "aac"


def test_hevc_10_bit_video_uses_full_transcode():
    raw = _raw_probe(video_codec="hevc")
    raw["streams"][0]["bits_per_raw_sample"] = "10"
    raw["streams"][0]["pix_fmt"] = "yuv420p10le"
    inventory = pilot.sanitize_probe(raw)
    decision = pilot.choose_delivery_decision(inventory)

    assert decision["decision"] == pilot.FULL_TRANSCODE
    assert decision["video_transcode_required"] is True
    assert decision["encoder_required"] is True
    assert decision["output"] == {"container": "fMP4", "video_codec": "h264", "audio_codec": "aac"}


def test_bitmap_subtitle_forces_transparent_video_transcode():
    inventory = pilot.sanitize_probe(_raw_probe(subtitle_codec="hdmv_pgs_subtitle"))
    decision = pilot.choose_delivery_decision(inventory, subtitle_index=2)

    assert decision["decision"] == pilot.SUBTITLE_BURN
    assert decision["subtitle_mode"] == "burn"
    assert decision["video_transcode_required"] is True
    assert decision["selected_subtitle_index"] == 2


def test_text_subtitle_is_selected_for_webvtt_without_burning():
    inventory = pilot.sanitize_probe(_raw_probe(subtitle_codec="subrip"))
    decision = pilot.choose_delivery_decision(inventory, subtitle_index=2)

    assert decision["subtitle_mode"] == "webvtt"
    assert decision["decision"] == pilot.DIRECT_PLAY
    assert decision["video_transcode_required"] is False


def test_hdr_without_verified_policy_falls_back_explicitly():
    raw = _raw_probe()
    raw["streams"][0]["color_primaries"] = "bt2020"
    raw["streams"][0]["color_transfer"] = "smpte2084"
    inventory = pilot.sanitize_probe(raw)
    decision = pilot.choose_delivery_decision(inventory)

    assert inventory["video"][0]["hdr"] == {"is_hdr": True, "types": ["HDR10"], "dolby_vision": False}
    assert decision["decision"] == pilot.EXTERNAL_FALLBACK
    assert decision["hdr_action"] == "reject"


def test_hdr_tone_map_is_a_full_transcode_decision():
    raw = _raw_probe()
    raw["streams"][0]["color_transfer"] = "smpte2084"
    inventory = pilot.sanitize_probe(raw)
    decision = pilot.choose_delivery_decision(inventory, hdr_policy="tone_map")

    assert decision["decision"] == pilot.FULL_TRANSCODE
    assert decision["hdr_action"] == "tone_map"


def test_srt_and_ass_text_subtitles_convert_to_webvtt():
    srt = "1\n00:00:01,250 --> 00:00:03,500\nHello\n"
    vtt = pilot.text_subtitle_to_webvtt(srt, codec="subrip", language="eng")
    assert vtt.startswith("WEBVTT\n\nNOTE language: eng")
    assert "00:00:01.250 --> 00:00:03.500" in vtt

    ass = "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\i1}Hello\\Nworld"
    ass_vtt = pilot.text_subtitle_to_webvtt(ass, codec="ass")
    assert "00:00:01.000 --> 00:00:03.000" in ass_vtt
    assert "Hello\nworld" in ass_vtt


def test_runtime_metrics_allowlist_excludes_commands_and_secrets():
    metrics = pilot.sanitize_runtime_metrics({
        "first_frame_latency_ms": 420,
        "accelerator": "nvenc",
        "reconnect_count": 1,
        "command": "ffmpeg -i https://provider.example/token",
        "stream_url": "https://provider.example/token",
        "api_password": "pilot-secret",
    })
    assert metrics == {
        "first_frame_latency_ms": 420,
        "accelerator": "nvenc",
        "reconnect_count": 1,
    }
    assert "provider.example" not in json.dumps(metrics)
    assert "pilot-secret" not in json.dumps(metrics)


def test_session_registry_replaces_and_cleans_workers_without_accumulation():
    registry = pilot.MediaFlowSessionRegistry()
    session_id = registry.create("https://provider.example/video.mp4?secret=one")
    assert registry.replace_worker(session_id, "worker-1") is None
    assert registry.replace_worker(session_id, "worker-2") == "worker-1"
    assert registry.snapshot(session_id)["worker_count"] == 1

    terminated = []
    result = registry.close(session_id, terminate_worker=lambda worker: terminated.append(worker) or True)
    assert terminated == ["worker-2"]
    assert result["cleanup_result"] == "complete"
    assert result["terminated_worker_count"] == 1
    assert registry.close(session_id)["cleanup_result"] == "already_closed"


@pytest.mark.asyncio
async def test_ffprobe_probe_returns_sanitized_inventory(monkeypatch):
    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return json.dumps(_raw_probe()).encode(), b"stderr with https://provider.example/secret"

    calls = []

    async def fake_create(*args, **kwargs):
        calls.append(args)
        return FakeProcess()

    monkeypatch.setattr(pilot.shutil, "which", lambda name: "ffprobe.exe")
    monkeypatch.setattr(pilot.asyncio, "create_subprocess_exec", fake_create)
    result = await pilot.probe_media_url("https://provider.example/direct?token=secret")

    assert result["ok"] is True
    assert result["code"] == "MEDIA_INVENTORY_READY"
    assert result["inventory"]["stream_counts"] == {"video": 1, "audio": 1, "subtitles": 0}
    assert "provider.example" not in json.dumps(result)
    assert calls and calls[0][-1] == "https://provider.example/direct?token=secret"
