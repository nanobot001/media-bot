"""Fixture-first contracts for the isolated MediaFlow capability pilot.

This module deliberately has no dependency on the production stream routes.  It
normalizes ffprobe output, selects a conservative browser delivery decision,
converts text subtitles, and tracks pilot sessions without retaining provider
URLs, credentials, or FFmpeg command lines.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional
from urllib.parse import urlsplit


DIRECT_PLAY = "direct_play"
REMUX_COPY = "remux_copy"
AUDIO_TRANSCODE = "audio_transcode"
FULL_TRANSCODE = "full_transcode"
SUBTITLE_BURN = "subtitle_burn"
EXTERNAL_FALLBACK = "external_fallback"

DELIVERY_DECISIONS = {
    DIRECT_PLAY,
    REMUX_COPY,
    AUDIO_TRANSCODE,
    FULL_TRANSCODE,
    SUBTITLE_BURN,
    EXTERNAL_FALLBACK,
}

_TEXT_SUBTITLE_CODECS = {
    "ass",
    "ssa",
    "subrip",
    "srt",
    "webvtt",
    "mov_text",
    "text",
}
_BITMAP_SUBTITLE_CODECS = {
    "dvd_subtitle",
    "hdmv_pgs_subtitle",
    "pgs",
    "vobsub",
    "dvb_subtitle",
}
_SAFE_VIDEO_CODECS = {"h264", "avc1", "avc"}
_SAFE_AUDIO_CODECS = {"aac", "mp3"}
_SAFE_CONTAINERS = {"mp4", "mov", "m4v"}
_SENSITIVE_TEXT = re.compile(
    r"(?i)(?:https?://|api[_-]?password|authorization|bearer\s|token=|magnet:\?)"
)


def _safe_text(value: Any, *, limit: int = 160) -> Optional[str]:
    if value is None:
        return None
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if not text or _SENSITIVE_TEXT.search(text):
        return None
    return text[:limit]


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_bool(value: Any) -> Optional[bool]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if str(value).strip().lower() in {"1", "true", "yes"}:
        return True
    if str(value).strip().lower() in {"0", "false", "no"}:
        return False
    return None


def _safe_disposition(stream: Mapping[str, Any]) -> Dict[str, bool]:
    disposition = stream.get("disposition")
    if not isinstance(disposition, Mapping):
        disposition = {}
    return {
        "default": bool(_safe_bool(disposition.get("default")) or False),
        "forced": bool(_safe_bool(disposition.get("forced")) or False),
    }


def _safe_tag(stream: Mapping[str, Any], key: str) -> Optional[str]:
    tags = stream.get("tags")
    if not isinstance(tags, Mapping):
        return None
    return _safe_text(tags.get(key))


def _subtitle_kind(codec_name: str) -> str:
    codec = codec_name.lower()
    if codec in _BITMAP_SUBTITLE_CODECS or "pgs" in codec or "vobsub" in codec:
        return "bitmap"
    if codec in _TEXT_SUBTITLE_CODECS:
        return "text"
    return "unknown"


def _hdr_info(stream: Mapping[str, Any]) -> Dict[str, Any]:
    indicators: set[str] = set()
    transfer = str(stream.get("color_transfer") or "").lower()
    primaries = str(stream.get("color_primaries") or "").lower()
    for marker, label in (
        ("smpte2084", "HDR10"),
        ("arib-std-b67", "HLG"),
        ("dolby", "Dolby Vision"),
        ("dovi", "Dolby Vision"),
    ):
        if marker in transfer or marker in primaries:
            indicators.add(label)

    side_data_list = stream.get("side_data_list")
    if isinstance(side_data_list, list):
        for side_data in side_data_list:
            if not isinstance(side_data, Mapping):
                continue
            side_type = str(side_data.get("side_data_type") or "").lower()
            if "dovi" in side_type or "dolby" in side_type:
                indicators.add("Dolby Vision")
            elif "mastering display" in side_type or "content light" in side_type:
                indicators.add("HDR metadata")

    return {
        "is_hdr": bool(indicators),
        "types": sorted(indicators),
        "dolby_vision": "Dolby Vision" in indicators,
    }


def _safe_video_stream(stream: Mapping[str, Any]) -> Dict[str, Any]:
    codec_name = str(stream.get("codec_name") or "").lower()
    return {
        "index": _safe_int(stream.get("index")),
        "codec_name": codec_name or None,
        "profile": _safe_text(stream.get("profile")),
        "level": _safe_int(stream.get("level")),
        "width": _safe_int(stream.get("width")),
        "height": _safe_int(stream.get("height")),
        "frame_rate": _safe_text(stream.get("avg_frame_rate") or stream.get("r_frame_rate")),
        "pixel_format": _safe_text(stream.get("pix_fmt")),
        "bit_depth": _safe_int(stream.get("bits_per_raw_sample"))
        or _safe_int(stream.get("bits_per_bit")),
        "color_primaries": _safe_text(stream.get("color_primaries")),
        "transfer_characteristics": _safe_text(stream.get("color_transfer")),
        "color_space": _safe_text(stream.get("color_space")),
        "hdr": _hdr_info(stream),
        "disposition": _safe_disposition(stream),
    }


def _safe_audio_stream(stream: Mapping[str, Any]) -> Dict[str, Any]:
    codec_name = str(stream.get("codec_name") or "").lower()
    return {
        "index": _safe_int(stream.get("index")),
        "codec_name": codec_name or None,
        "language": _safe_tag(stream, "language"),
        "title": _safe_tag(stream, "title"),
        "channels": _safe_int(stream.get("channels")),
        "channel_layout": _safe_text(stream.get("channel_layout")),
        "sample_rate": _safe_int(stream.get("sample_rate")),
        "bitrate": _safe_int(stream.get("bit_rate")),
        "disposition": _safe_disposition(stream),
    }


def _safe_subtitle_stream(stream: Mapping[str, Any]) -> Dict[str, Any]:
    codec_name = str(stream.get("codec_name") or "").lower()
    kind = _subtitle_kind(codec_name)
    return {
        "index": _safe_int(stream.get("index")),
        "codec_name": codec_name or None,
        "language": _safe_tag(stream, "language"),
        "title": _safe_tag(stream, "title"),
        "classification": kind,
        "is_text": kind == "text",
        "disposition": _safe_disposition(stream),
    }


def sanitize_probe(probe: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a non-sensitive stream inventory from raw ffprobe JSON."""
    format_data = probe.get("format") if isinstance(probe.get("format"), Mapping) else {}
    streams = probe.get("streams") if isinstance(probe.get("streams"), list) else []

    format_name = str(format_data.get("format_name") or "").lower()
    format_tokens = [token.strip() for token in format_name.split(",") if token.strip()]
    safe_format = {
        "format_name": format_name or None,
        "format_long_name": _safe_text(format_data.get("format_long_name")),
        "container": next(
            (token for token in format_tokens if token in _SAFE_CONTAINERS),
            format_tokens[0] if format_tokens else None,
        ),
        "duration_seconds": _safe_float(format_data.get("duration")),
        "start_time_seconds": _safe_float(format_data.get("start_time")),
        "bitrate": _safe_int(format_data.get("bit_rate")),
        "size_bytes": _safe_int(format_data.get("size")),
        "seekable": _safe_bool(format_data.get("seekable")),
    }

    video = [
        _safe_video_stream(stream)
        for stream in streams
        if isinstance(stream, Mapping) and stream.get("codec_type") == "video"
    ]
    audio = [
        _safe_audio_stream(stream)
        for stream in streams
        if isinstance(stream, Mapping) and stream.get("codec_type") == "audio"
    ]
    subtitles = [
        _safe_subtitle_stream(stream)
        for stream in streams
        if isinstance(stream, Mapping) and stream.get("codec_type") == "subtitle"
    ]
    return {
        "format": safe_format,
        "duration_seconds": safe_format["duration_seconds"],
        "seekable": safe_format["seekable"],
        "video": video,
        "audio": audio,
        "subtitles": subtitles,
        "stream_counts": {
            "video": len(video),
            "audio": len(audio),
            "subtitles": len(subtitles),
        },
    }


def _validated_http_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (
        parsed.scheme.lower() in {"http", "https"}
        and bool(parsed.hostname)
        and not parsed.username
        and not parsed.password
    )


async def probe_media_url(
    stream_url: str,
    *,
    timeout_seconds: float = 30.0,
    ffprobe_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Probe one URL with ffprobe and return only the sanitized inventory."""
    if not _validated_http_url(stream_url):
        return {
            "ok": False,
            "code": "PROBE_URL_INVALID",
            "retryable": False,
            "message": "The pilot accepts only credential-free HTTP(S) media URLs.",
        }

    executable = ffprobe_path or shutil.which("ffprobe")
    if not executable:
        return {
            "ok": False,
            "code": "FFPROBE_UNAVAILABLE",
            "retryable": False,
            "message": "ffprobe is not installed or is not available on PATH.",
        }

    show_entries = (
        "format=format_name,format_long_name,duration,start_time,bit_rate,size,seekable:"
        "stream=index,codec_type,codec_name,profile,level,width,height,r_frame_rate,avg_frame_rate,"
        "pix_fmt,bits_per_raw_sample,bits_per_bit,color_primaries,color_transfer,color_space,"
        "channels,channel_layout,sample_rate,bit_rate,disposition:"
        "stream_tags=language,title:stream_side_data=side_data_type"
    )
    args = [
        executable,
        "-v",
        "error",
        "-show_entries",
        show_entries,
        "-of",
        "json",
        "-i",
        stream_url,
    ]

    process: Optional[asyncio.subprocess.Process] = None
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        if process is not None:
            process.kill()
            await process.communicate()
        return {
            "ok": False,
            "code": "FFPROBE_TIMEOUT",
            "retryable": True,
            "message": "ffprobe exceeded the bounded pilot probe timeout.",
        }
    except asyncio.CancelledError:
        if process is not None and process.returncode is None:
            process.kill()
            await process.communicate()
        raise
    except OSError:
        return {
            "ok": False,
            "code": "FFPROBE_START_FAILED",
            "retryable": False,
            "message": "ffprobe could not be started.",
        }

    if process.returncode != 0:
        return {
            "ok": False,
            "code": "FFPROBE_FAILED",
            "retryable": True,
            "message": "ffprobe could not read the pilot media source.",
        }
    try:
        parsed = json.loads(stdout.decode("utf-8", errors="replace"))
    except (AttributeError, TypeError, ValueError):
        return {
            "ok": False,
            "code": "FFPROBE_INVALID_OUTPUT",
            "retryable": True,
            "message": "ffprobe returned invalid JSON.",
        }
    if not isinstance(parsed, Mapping):
        return {
            "ok": False,
            "code": "FFPROBE_INVALID_OUTPUT",
            "retryable": True,
            "message": "ffprobe returned an unexpected JSON shape.",
        }
    return {
        "ok": True,
        "code": "MEDIA_INVENTORY_READY",
        "evidence_source": "ffprobe",
        "inventory": sanitize_probe(parsed),
    }


def _selected_stream(
    streams: Iterable[Mapping[str, Any]],
    requested_index: Optional[int],
) -> Optional[Mapping[str, Any]]:
    values = list(streams)
    if requested_index is not None:
        return next((stream for stream in values if stream.get("index") == requested_index), None)
    return next(
        (stream for stream in values if stream.get("disposition", {}).get("default")),
        values[0] if values else None,
    )


def _video_browser_safe(stream: Mapping[str, Any]) -> bool:
    codec = str(stream.get("codec_name") or "").lower()
    if codec not in _SAFE_VIDEO_CODECS:
        return False
    bits = _safe_int(stream.get("bit_depth"))
    if bits is not None and bits > 8:
        return False
    pixel_format = str(stream.get("pixel_format") or "").lower()
    return not any(marker in pixel_format for marker in ("10", "12", "14", "16", "422", "444"))


def _audio_copy_safe(stream: Mapping[str, Any], target_channels: Optional[str]) -> bool:
    codec = str(stream.get("codec_name") or "").lower()
    if codec not in _SAFE_AUDIO_CODECS:
        return False
    if not target_channels:
        return True
    normalized_target = target_channels.lower().replace(".", "")
    channels = _safe_int(stream.get("channels"))
    if normalized_target in {"stereo", "20", "2"}:
        return channels is not None and channels <= 2
    if normalized_target in {"51", "5.1"}:
        return channels is not None and channels <= 6
    return False


def choose_delivery_decision(
    inventory: Mapping[str, Any],
    *,
    delivery_mode: str = "direct",
    audio_index: Optional[int] = None,
    subtitle_index: Optional[int] = None,
    target_audio_channels: Optional[str] = None,
    hdr_policy: str = "reject",
) -> Dict[str, Any]:
    """Choose one conservative browser delivery path from a sanitized inventory."""
    video = inventory.get("video") if isinstance(inventory.get("video"), list) else []
    audio = inventory.get("audio") if isinstance(inventory.get("audio"), list) else []
    subtitles = inventory.get("subtitles") if isinstance(inventory.get("subtitles"), list) else []
    selected_video = video[0] if video and isinstance(video[0], Mapping) else None
    selected_audio = _selected_stream((stream for stream in audio if isinstance(stream, Mapping)), audio_index)
    selected_subtitle = _selected_stream(
        (stream for stream in subtitles if isinstance(stream, Mapping)),
        subtitle_index,
    )

    base = {
        "decision": EXTERNAL_FALLBACK,
        "reason": "The pilot could not prove a browser-safe video and audio path.",
        "selected_audio_index": selected_audio.get("index") if selected_audio else None,
        "selected_subtitle_index": selected_subtitle.get("index") if selected_subtitle else None,
        "audio_selection_required": bool(audio),
        "subtitle_mode": "none",
        "video_transcode_required": False,
        "audio_transcode_required": False,
        "encoder_required": False,
        "accelerator": "not_started",
        "hdr_action": "none",
        "output": {
            "container": "fMP4" if delivery_mode.lower() in {"hls", "fmp4", "transcode_hls"} else "MP4",
            "video_codec": None,
            "audio_codec": None,
        },
    }

    if selected_video is None or selected_audio is None:
        base["reason"] = "A video stream and an explicitly selectable audio stream are required."
        return base

    hdr = selected_video.get("hdr") if isinstance(selected_video.get("hdr"), Mapping) else {}
    hdr_detected = bool(hdr.get("is_hdr"))
    normalized_hdr_policy = hdr_policy.lower().strip()
    if hdr_detected and normalized_hdr_policy not in {"preserve", "tone_map"}:
        base.update({
            "reason": "HDR was detected and no verified preserve or tone-map policy was selected.",
            "hdr_action": "reject",
        })
        return base
    if hdr_detected:
        base["hdr_action"] = "tone_map" if normalized_hdr_policy == "tone_map" else "preserve_verified"

    if selected_subtitle is not None:
        classification = selected_subtitle.get("classification")
        if classification == "bitmap":
            base.update({
                "decision": SUBTITLE_BURN,
                "reason": "The selected bitmap subtitle requires a transparent full video transcode.",
                "subtitle_mode": "burn",
                "video_transcode_required": True,
                "encoder_required": True,
            })
            base["output"].update({"video_codec": "h264", "audio_codec": "aac"})
            return base
        if classification == "text":
            base["subtitle_mode"] = "webvtt"
        else:
            base.update({
                "reason": "The selected subtitle codec is not a proven text or bitmap track.",
            })
            return base

    video_safe = _video_browser_safe(selected_video)
    audio_safe = _audio_copy_safe(selected_audio, target_audio_channels)
    source_container = str((inventory.get("format") or {}).get("container") or "").lower()
    direct_mode = delivery_mode.lower() in {"direct", "mp4"}
    if video_safe and audio_safe and source_container in _SAFE_CONTAINERS and direct_mode and not hdr_detected:
        base.update({
            "decision": DIRECT_PLAY,
            "reason": "The MP4/M4V source already has browser-compatible H.264 video and AAC/MP3 audio.",
            "output": {
                "container": source_container.upper(),
                "video_codec": selected_video.get("codec_name"),
                "audio_codec": selected_audio.get("codec_name"),
            },
        })
        return base
    if video_safe and audio_safe and not hdr_detected:
        base.update({
            "decision": REMUX_COPY,
            "reason": (
                "The elementary streams are browser-compatible; only the delivery "
                "container or HLS shape needs repackaging."
            ),
            "output": {
                "container": "fMP4",
                "video_codec": selected_video.get("codec_name"),
                "audio_codec": selected_audio.get("codec_name"),
            },
        })
        return base
    if video_safe and audio_safe and hdr_detected and normalized_hdr_policy == "preserve":
        base.update({
            "decision": REMUX_COPY,
            "reason": (
                "The source is browser-compatible and the pilot was explicitly "
                "configured for verified HDR preservation."
            ),
            "output": {
                "container": "fMP4",
                "video_codec": selected_video.get("codec_name"),
                "audio_codec": selected_audio.get("codec_name"),
            },
        })
        return base
    if video_safe and not audio_safe and not hdr_detected:
        base.update({
            "decision": AUDIO_TRANSCODE,
            "reason": "Video can be copied while the selected audio requires AAC conversion or downmixing.",
            "audio_transcode_required": True,
            "encoder_required": True,
            "output": {"container": "fMP4", "video_codec": selected_video.get("codec_name"), "audio_codec": "aac"},
        })
        return base

    base.update({
        "decision": FULL_TRANSCODE,
        "reason": (
            "The selected video is not a verified browser-safe H.264 8-bit stream, "
            "so video and audio are transcoded to H.264/AAC."
        ),
        "video_transcode_required": True,
        "audio_transcode_required": not audio_safe,
        "encoder_required": True,
        "output": {"container": "fMP4", "video_codec": "h264", "audio_codec": "aac"},
    })
    return base


def _webvtt_timestamp(value: str) -> str:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    if len(parts) == 2:
        parts = ["00", *parts]
    if len(parts) != 3:
        return value
    hours, minutes, seconds = parts
    if "." in seconds:
        whole_seconds, fraction = seconds.split(".", 1)
    else:
        whole_seconds, fraction = seconds, ""
    return f"{int(hours):02d}:{int(minutes):02d}:{int(whole_seconds):02d}.{fraction[:3].ljust(3, '0')}"


def _strip_ass_markup(value: str) -> str:
    value = re.sub(r"\{[^}]*\}", "", value)
    return value.replace(r"\N", "\n").replace(r"\n", "\n").replace(r"\h", " ").strip()


def text_subtitle_to_webvtt(
    subtitle_text: str,
    *,
    codec: str = "subrip",
    language: Optional[str] = None,
) -> str:
    """Convert SRT, WebVTT, or the common ASS/SSA dialogue form to WebVTT."""
    normalized_codec = codec.lower().strip()
    if normalized_codec not in _TEXT_SUBTITLE_CODECS:
        raise ValueError("Only text subtitle codecs can be converted to WebVTT.")
    if normalized_codec in {"ass", "ssa"}:
        cues = []
        for line in subtitle_text.splitlines():
            if not line.lower().startswith("dialogue:"):
                continue
            fields = line.split(":", 1)[1].split(",", 9)
            if len(fields) < 10:
                continue
            cues.append((fields[1], fields[2], _strip_ass_markup(fields[9])))
        body = "\n\n".join(
            f"{_webvtt_timestamp(start)} --> {_webvtt_timestamp(end)}\n{text}"
            for start, end, text in cues
        )
    else:
        cleaned = subtitle_text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if cleaned.startswith("WEBVTT"):
            cleaned = cleaned.split("\n", 1)[1].lstrip("\n") if "\n" in cleaned else ""
        blocks = re.split(r"\n{2,}", cleaned)
        rendered = []
        for block in blocks:
            lines = block.splitlines()
            if not lines:
                continue
            timing_index = next((idx for idx, line in enumerate(lines) if "-->" in line), None)
            if timing_index is None:
                continue
            timing = lines[timing_index].replace(",", ".")
            rendered.append("\n".join([*lines[:timing_index], timing, *lines[timing_index + 1:]]).strip())
        body = "\n\n".join(rendered)

    language_note = f"NOTE language: {language}\n\n" if language else ""
    return f"WEBVTT\n\n{language_note}{body}".rstrip() + "\n"


def sanitize_runtime_metrics(metrics: Mapping[str, Any]) -> Dict[str, Any]:
    """Keep only metrics safe for pilot events and evidence artifacts."""
    allowed = {
        "first_frame_latency_ms",
        "seek_resume_latency_ms",
        "input_video_codec",
        "input_audio_codec",
        "output_video_codec",
        "output_audio_codec",
        "accelerator",
        "cpu_percent",
        "gpu_percent",
        "reconnect_count",
        "exit_reason",
        "cleanup_result",
        "active_workers",
        "temporary_segment_count",
    }
    result: Dict[str, Any] = {}
    for key in allowed:
        if key not in metrics:
            continue
        value = metrics[key]
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = _safe_text(value) if isinstance(value, str) else value
    return result


@dataclass
class _PilotSession:
    session_id: str
    source_fingerprint: str
    created_at: str
    worker_ids: List[str] = field(default_factory=list)


class MediaFlowSessionRegistry:
    """Track opaque pilot workers without retaining source URLs or commands."""

    def __init__(self) -> None:
        self._sessions: Dict[str, _PilotSession] = {}

    def create(self, source_identity: str) -> str:
        session_id = f"mf-{uuid.uuid4().hex}"
        fingerprint = hashlib.sha256(source_identity.encode("utf-8")).hexdigest()[:16]
        self._sessions[session_id] = _PilotSession(
            session_id=session_id,
            source_fingerprint=fingerprint,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        return session_id

    def replace_worker(self, session_id: str, worker_id: str) -> Optional[str]:
        session = self._sessions[session_id]
        obsolete = session.worker_ids[-1] if session.worker_ids else None
        session.worker_ids = [worker_id]
        return obsolete

    def snapshot(self, session_id: str) -> Dict[str, Any]:
        session = self._sessions[session_id]
        return {
            "session_id": session.session_id,
            "source_fingerprint": session.source_fingerprint,
            "created_at": session.created_at,
            "worker_count": len(session.worker_ids),
        }

    def close(
        self,
        session_id: str,
        *,
        terminate_worker: Optional[Callable[[str], bool]] = None,
    ) -> Dict[str, Any]:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return {"session_id": session_id, "cleanup_result": "already_closed", "terminated_worker_count": 0}
        terminated = 0
        failed = 0
        for worker_id in session.worker_ids:
            if terminate_worker is None:
                terminated += 1
                continue
            try:
                if terminate_worker(worker_id):
                    terminated += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
        return {
            "session_id": session_id,
            "cleanup_result": "complete" if failed == 0 else "partial",
            "terminated_worker_count": terminated,
            "failed_worker_count": failed,
        }
