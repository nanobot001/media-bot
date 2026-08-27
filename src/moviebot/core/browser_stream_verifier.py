"""Authoritative checks for files selected from a debrid browser stream."""

import asyncio
import json
import shutil
from typing import Any, Dict, Optional

from moviebot.core.release_parser import (
    BROWSER_CANDIDATE_EXPLICITLY_INCOMPATIBLE,
    BROWSER_CANDIDATE_PROBEABLE,
    classify_browser_stream_candidate,
    is_browser_stream_compatible,
    is_browser_stream_metadata_compatible,
)


DEFAULT_FFPROBE_TIMEOUT_SECONDS = 20.0


def _safe_probe_summary(probe: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only non-sensitive codec fields from ffprobe output."""
    format_data = probe.get("format") if isinstance(probe.get("format"), dict) else {}
    streams = probe.get("streams") if isinstance(probe.get("streams"), list) else []
    safe_streams = []
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        safe_streams.append({
            key: stream.get(key)
            for key in (
                "codec_type",
                "codec_name",
                "profile",
                "pix_fmt",
                "bits_per_raw_sample",
            )
            if stream.get(key) is not None
        })
    return {
        "format": {
            "format_name": format_data.get("format_name"),
        },
        "streams": safe_streams,
    }


async def probe_unlocked_url(
    stream_url: str,
    *,
    actual_filename: str,
    timeout_seconds: float = DEFAULT_FFPROBE_TIMEOUT_SECONDS,
    ffprobe_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Probe one unlocked URL without invoking a shell or retaining the URL."""
    if not stream_url:
        return {
            "ok": False,
            "code": "STREAM_URL_MISSING",
            "retryable": False,
            "message": "The provider did not return a direct stream URL for probing.",
        }

    executable = ffprobe_path or shutil.which("ffprobe")
    if not executable:
        return {
            "ok": False,
            "code": "FFPROBE_UNAVAILABLE",
            "retryable": False,
            "message": "ffprobe is not installed or is not available on PATH.",
        }

    args = [
        executable,
        "-v",
        "error",
        "-show_entries",
        "format=format_name:stream=codec_type,codec_name,profile,pix_fmt,bits_per_raw_sample",
        "-of",
        "json",
        "-i",
        stream_url,
    ]
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        if process is not None:
            process.kill()
            await process.communicate()
        return {
            "ok": False,
            "code": "FFPROBE_TIMEOUT",
            "retryable": True,
            "message": "ffprobe exceeded the bounded stream verification timeout.",
        }
    except OSError:
        return {
            "ok": False,
            "code": "FFPROBE_UNAVAILABLE",
            "retryable": False,
            "message": "ffprobe could not be started.",
        }

    if process.returncode != 0:
        return {
            "ok": False,
            "code": "FFPROBE_FAILED",
            "retryable": True,
            "message": "ffprobe could not read the unlocked stream.",
        }
    try:
        probe = json.loads(stdout.decode("utf-8", errors="replace"))
    except (TypeError, ValueError):
        return {
            "ok": False,
            "code": "FFPROBE_INVALID_OUTPUT",
            "retryable": True,
            "message": "ffprobe returned invalid JSON.",
        }

    safe_probe = _safe_probe_summary(probe)
    if not is_browser_stream_metadata_compatible(safe_probe, actual_filename):
        return {
            "ok": False,
            "code": "BROWSER_CODEC_UNSUPPORTED",
            "retryable": False,
            "message": "The selected file is not MP4/M4V with H.264 video and AAC/MP3 audio.",
            "probe": safe_probe,
        }
    return {
        "ok": True,
        "code": "BROWSER_CODEC_VERIFIED",
        "retryable": False,
        "evidence_source": "ffprobe",
        "probe": safe_probe,
        "audio_track_present": True,
    }


async def verify_stream_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Verify the provider-selected file, probing only when its name is ambiguous."""
    actual_filename = str(payload.get("filename") or "")
    result: Dict[str, Any] = {
        "verified": False,
        "actual_filename": actual_filename,
        "file_id": payload.get("file_id"),
        "filesize": payload.get("filesize") or 0,
        "audio_track_present": False,
        "audio_decoded": None,
    }

    if is_browser_stream_compatible(actual_filename):
        result.update({
            "verified": True,
            "verification_code": "BROWSER_FILENAME_VERIFIED",
            "evidence_source": "actual_filename",
            "audio_track_present": True,
        })
        return result

    classification = classify_browser_stream_candidate(actual_filename)
    if classification == BROWSER_CANDIDATE_EXPLICITLY_INCOMPATIBLE:
        result.update({
            "verification_code": "BROWSER_CODEC_UNSUPPORTED",
            "evidence_source": "actual_filename",
            "message": "The provider-selected file has an explicitly unsupported browser format.",
            "retryable": False,
        })
        return result
    if classification != BROWSER_CANDIDATE_PROBEABLE:
        result.update({
            "verification_code": "BROWSER_VERIFICATION_FAILED",
            "message": "The provider-selected file could not be classified.",
            "retryable": False,
        })
        return result

    probe_result = await probe_unlocked_url(
        str(payload.get("stream_url") or ""),
        actual_filename=actual_filename,
    )
    result.update({
        "verification_code": probe_result.get("code", "BROWSER_VERIFICATION_FAILED"),
        "evidence_source": probe_result.get("evidence_source", "ffprobe"),
        "retryable": bool(probe_result.get("retryable", False)),
        "message": probe_result.get("message"),
        "probe": probe_result.get("probe"),
        "audio_track_present": bool(probe_result.get("audio_track_present", False)),
    })
    result["verified"] = bool(probe_result.get("ok"))
    if result["verified"]:
        result["audio_track_present"] = True
    return result
