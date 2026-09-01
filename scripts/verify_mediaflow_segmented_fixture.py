"""Verify opaque long-duration MediaFlow HLS output against a local fixture."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from typing import Any, Dict

from moviebot.adapters.mediaflow_client import MediaFlowClient
from moviebot.core.mediaflow_segmented import fetch_segment_bytes, rewrite_hls_manifest


def _select_segment_keys(manifest: str, late_seconds: float) -> tuple[str, str, float, float]:
    elapsed = 0.0
    media_index = 0
    first_key = ""
    late_key = ""
    late_start = 0.0
    pending_duration = None
    for raw_line in manifest.splitlines():
        line = raw_line.strip()
        if line.startswith("#EXTINF:"):
            pending_duration = float(line.split(":", 1)[1].split(",", 1)[0])
            continue
        if not line or line.startswith("#") or pending_duration is None:
            continue
        key = f"s{media_index:06d}"
        if not first_key:
            first_key = key
        if not late_key and elapsed >= late_seconds:
            late_key = key
            late_start = elapsed
        elapsed += pending_duration
        pending_duration = None
        media_index += 1
    if not first_key or not late_key:
        raise RuntimeError("Fixture playlist does not contain the required late segment.")
    return first_key, late_key, late_start, elapsed


async def _fetch_with_elapsed(target: str, timeout_seconds: float) -> tuple[bytes, float]:
    started = time.monotonic()
    body, _ = await fetch_segment_bytes(
        target,
        timeout_seconds=timeout_seconds,
        max_bytes=64 * 1024 * 1024,
        timeout_code="MEDIAFLOW_FIXTURE_OUTPUT_TIMEOUT",
    )
    return body, round(time.monotonic() - started, 3)


async def verify(args: argparse.Namespace) -> Dict[str, Any]:
    password = os.environ.get("MEDIAFLOW_FIXTURE_PASSWORD", "")
    if not password:
        raise RuntimeError("MEDIAFLOW_FIXTURE_PASSWORD is required.")
    client = MediaFlowClient(base_url=args.mediaflow_url, api_password=password)
    health = await client.health()
    if not health.get("ok"):
        raise RuntimeError("MediaFlow fixture service is unhealthy.")
    playback = await client.generate_signed_playback_url(
        args.fixture_url,
        mode="transcode_hls",
        filename="segmented-long-135.mkv",
        expiration_seconds=900,
        force_audio_stereo=True,
        prefer_segmented_hls=True,
    )
    private_manifest = await client.fetch_hls_manifest(playback["url"], max_bytes=2 * 1024 * 1024)
    rewritten = rewrite_hls_manifest(
        private_manifest,
        session_id="fixture-session",
        playlist_url=playback["url"],
        max_segments=4096,
    )
    first_key, late_key, late_start, duration = _select_segment_keys(
        private_manifest,
        args.late_seconds,
    )
    initial_body, initial_elapsed = await _fetch_with_elapsed(
        rewritten.targets[first_key],
        args.timeout_seconds,
    )
    late_body, late_elapsed = await _fetch_with_elapsed(
        rewritten.targets[late_key],
        args.timeout_seconds,
    )
    public_manifest = rewritten.body
    if any(marker in public_manifest for marker in ("api_password", "fixture-secret", "host.docker.internal")):
        raise RuntimeError("Opaque manifest verification failed.")
    return {
        "ok": True,
        "fixture_duration_seconds": round(duration, 3),
        "media_segment_count": rewritten.media_segment_count,
        "initial_segment": {
            "key": first_key,
            "bytes": len(initial_body),
            "elapsed_seconds": initial_elapsed,
        },
        "late_segment": {
            "key": late_key,
            "start_seconds": round(late_start, 3),
            "bytes": len(late_body),
            "elapsed_seconds": late_elapsed,
        },
        "opaque_manifest": True,
        "capabilities": health.get("capabilities") or {},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mediaflow-url", default="http://127.0.0.1:28888")
    parser.add_argument(
        "--fixture-url",
        default="http://host.docker.internal:18765/segmented-long-135.mkv",
    )
    parser.add_argument("--late-seconds", type=float, default=120.0)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()
    try:
        result = asyncio.run(verify(args))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "code": getattr(exc, "code", None),
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
