"""Opaque HLS manifest rewriting and bounded segment retrieval for MediaFlow."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import urljoin, urlsplit

import httpx


_MAP_URI_RE = re.compile(r'URI="([^"]+)"')
_SAFE_SEGMENT_KEY_RE = re.compile(r"^(?:init|s[0-9]{6})$")


class MediaFlowSegmentedError(RuntimeError):
    """Sanitized segmented-producer failure safe for structured projection."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class RewrittenHLSManifest:
    body: str
    targets: Dict[str, str]
    media_segment_count: int


def _is_local_mediaflow_target(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (
        parsed.scheme.lower() in {"http", "https"}
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        and not parsed.username
        and not parsed.password
    )


def rewrite_hls_manifest(
    body: str,
    *,
    session_id: str,
    playlist_url: str,
    max_segments: int,
) -> RewrittenHLSManifest:
    """Replace private MediaFlow HLS targets with opaque media-bot paths."""
    if not isinstance(body, str) or not body.lstrip().startswith("#EXTM3U"):
        raise MediaFlowSegmentedError(
            "MEDIAFLOW_SEGMENTED_MANIFEST_INVALID",
            "MediaFlow returned an invalid segmented playlist.",
            retryable=True,
        )
    if not _is_local_mediaflow_target(playlist_url):
        raise MediaFlowSegmentedError(
            "MEDIAFLOW_SEGMENTED_TARGET_INVALID",
            "MediaFlow returned an unsafe segmented target.",
        )
    bounded_max = max(1, min(int(max_segments), 10_000))
    public_base = f"/api/mediaflow/sessions/{session_id}/segments"
    targets: Dict[str, str] = {}
    rendered: list[str] = []
    segment_index = 0

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line.startswith("#EXT-X-MAP:"):
            match = _MAP_URI_RE.search(line)
            if not match:
                raise MediaFlowSegmentedError(
                    "MEDIAFLOW_SEGMENTED_MANIFEST_INVALID",
                    "MediaFlow returned an invalid initialization segment reference.",
                )
            target = urljoin(playlist_url, match.group(1))
            if not _is_local_mediaflow_target(target):
                raise MediaFlowSegmentedError(
                    "MEDIAFLOW_SEGMENTED_TARGET_INVALID",
                    "MediaFlow returned an unsafe initialization segment target.",
                )
            targets["init"] = target
            rendered.append(_MAP_URI_RE.sub(f'URI="{public_base}/init"', line, count=1))
            continue
        if line.startswith("#") or not line:
            # No other URI-bearing tag is currently part of the pinned
            # transcoder contract. Fail closed instead of leaking a target.
            if "URI=" in line:
                raise MediaFlowSegmentedError(
                    "MEDIAFLOW_SEGMENTED_MANIFEST_UNSUPPORTED",
                    "MediaFlow returned an unsupported playlist reference.",
                )
            rendered.append(line)
            continue

        if segment_index >= bounded_max:
            raise MediaFlowSegmentedError(
                "MEDIAFLOW_SEGMENT_LIMIT_EXCEEDED",
                "The segmented playlist exceeds the configured retention limit.",
            )
        target = urljoin(playlist_url, line)
        if not _is_local_mediaflow_target(target):
            raise MediaFlowSegmentedError(
                "MEDIAFLOW_SEGMENTED_TARGET_INVALID",
                "MediaFlow returned an unsafe media segment target.",
            )
        key = f"s{segment_index:06d}"
        targets[key] = target
        rendered.append(f"{public_base}/{key}")
        segment_index += 1

    if "init" not in targets or segment_index == 0:
        raise MediaFlowSegmentedError(
            "MEDIAFLOW_SEGMENTED_MANIFEST_EMPTY",
            "MediaFlow returned no playable media segments.",
            retryable=True,
        )
    return RewrittenHLSManifest(
        body="\n".join(rendered) + "\n",
        targets=targets,
        media_segment_count=segment_index,
    )


def safe_segment_key(value: str) -> bool:
    return bool(_SAFE_SEGMENT_KEY_RE.fullmatch(str(value or "")))


async def fetch_segment_bytes(
    target_url: str,
    *,
    timeout_seconds: float,
    max_bytes: int,
    timeout_code: str,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> tuple[bytes, str]:
    """Retrieve one bounded segment while timing actual output progress."""
    if not _is_local_mediaflow_target(target_url):
        raise MediaFlowSegmentedError(
            "MEDIAFLOW_SEGMENTED_TARGET_INVALID",
            "The segmented producer target is unsafe.",
        )
    bounded_timeout = max(0.1, min(float(timeout_seconds), 300.0))
    bounded_bytes = max(1024, min(int(max_bytes), 256 * 1024 * 1024))
    data = bytearray()
    media_type = "video/mp4"

    try:
        async with httpx.AsyncClient(
            timeout=None,
            transport=transport,
            follow_redirects=False,
        ) as client:
            async with client.stream("GET", target_url) as response:
                if response.status_code != 200:
                    code = (
                        "MEDIAFLOW_PRODUCER_SOURCE_FAILED"
                        if response.status_code in {404, 410, 416}
                        else "MEDIAFLOW_PRODUCER_FAILED"
                    )
                    raise MediaFlowSegmentedError(
                        code,
                        "MediaFlow could not produce the requested media segment.",
                        retryable=response.status_code >= 500,
                    )
                media_type = response.headers.get("content-type", "video/mp4").split(";", 1)[0]
                iterator = response.aiter_bytes(chunk_size=64 * 1024)
                while True:
                    try:
                        chunk = await asyncio.wait_for(iterator.__anext__(), timeout=bounded_timeout)
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError as exc:
                        raise MediaFlowSegmentedError(
                            timeout_code,
                            "MediaFlow stopped producing media within the configured deadline.",
                            retryable=True,
                        ) from exc
                    if not chunk:
                        continue
                    data.extend(chunk)
                    if len(data) > bounded_bytes:
                        raise MediaFlowSegmentedError(
                            "MEDIAFLOW_SEGMENT_TOO_LARGE",
                            "A MediaFlow segment exceeded the configured byte limit.",
                        )
    except MediaFlowSegmentedError:
        raise
    except httpx.HTTPError as exc:
        raise MediaFlowSegmentedError(
            "MEDIAFLOW_PRODUCER_FAILED",
            "MediaFlow could not produce the requested media segment.",
            retryable=True,
        ) from exc

    if not data:
        raise MediaFlowSegmentedError(
            timeout_code,
            "MediaFlow produced no media within the configured deadline.",
            retryable=True,
        )
    return bytes(data), media_type
