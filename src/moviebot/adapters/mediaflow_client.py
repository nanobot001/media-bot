"""Authenticated, localhost-only client for the isolated MediaFlow pilot."""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional
from urllib.parse import unquote, urlsplit

import httpx

from moviebot.config import settings


class MediaFlowError(RuntimeError):
    """A sanitized MediaFlow pilot failure."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def _is_localhost_url(value: str) -> bool:
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


class MediaFlowClient:
    """Use MediaFlow's encrypted URL generator without exposing provider secrets."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        api_password: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.base_url = (base_url or settings.mediaflow_url).rstrip("/")
        self.api_password = api_password if api_password is not None else settings.mediaflow_api_password
        self.timeout_seconds = timeout_seconds or settings.mediaflow_timeout_seconds
        self.transport = transport
        if not _is_localhost_url(self.base_url):
            raise MediaFlowError(
                "MEDIAFLOW_NON_LOCAL_URL",
                "The MediaFlow pilot must bind to localhost.",
            )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            transport=self.transport,
        )

    async def health(self) -> Dict[str, Any]:
        """Check the unauthenticated health endpoint without returning config."""
        try:
            async with self._client() as client:
                response = await client.get("/health")
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return {
                "ok": False,
                "code": "MEDIAFLOW_HEALTH_FAILED",
                "retryable": True,
                "message": "MediaFlow health check failed.",
                "detail": type(exc).__name__,
            }
        raw_capabilities = payload.get("capabilities") if isinstance(payload, Mapping) else {}
        capabilities = {
            "force_audio_stereo": bool(
                isinstance(raw_capabilities, Mapping)
                and raw_capabilities.get("force_audio_stereo") is True
            ),
        }
        return {
            "ok": True,
            "code": "MEDIAFLOW_HEALTHY",
            "service": "mediaflow-proxy",
            "status": payload.get("status") if isinstance(payload, Mapping) else None,
            "capabilities": capabilities,
        }

    async def generate_signed_playback_url(
        self,
        destination_url: str,
        *,
        mode: str = "transcode_hls",
        start_seconds: Optional[float] = None,
        filename: Optional[str] = None,
        request_headers: Optional[Mapping[str, str]] = None,
        expiration_seconds: int = 3600,
        force_audio_stereo: bool = False,
        _allow_hls_fallback: bool = True,
    ) -> Dict[str, Any]:
        """Generate an encrypted local playback URL and return no upstream identity."""
        if not self.api_password:
            raise MediaFlowError("MEDIAFLOW_PASSWORD_MISSING", "MediaFlow API password is not configured.")
        if not self._valid_destination_url(destination_url):
            raise MediaFlowError(
                "MEDIAFLOW_DESTINATION_INVALID",
                "The pilot destination must be a credential-free HTTP(S) URL.",
            )
        if expiration_seconds <= 0 or expiration_seconds > 24 * 60 * 60:
            raise MediaFlowError(
                "MEDIAFLOW_EXPIRATION_INVALID",
                "Playback URL expiration must be between 1 second and 24 hours.",
            )

        requested_mode = mode.lower().strip()
        normalized_mode = requested_mode
        forced_mode_reason = None
        if force_audio_stereo and normalized_mode == "transcode_hls":
            normalized_mode = "transcode_stream"
            forced_mode_reason = "AUDIO_STEREO_REQUIRES_DIRECT_TRANSCODE"
        if force_audio_stereo and normalized_mode == "direct_stream":
            raise MediaFlowError(
                "MEDIAFLOW_AUDIO_MODE_INVALID",
                "Stereo downmix requires MediaFlow transcoding.",
            )
        endpoint, query_params = self._mode_parameters(
            normalized_mode,
            start_seconds,
            force_audio_stereo=force_audio_stereo,
        )
        payload: Dict[str, Any] = {
            "mediaflow_proxy_url": self.base_url,
            "endpoint": endpoint,
            "destination_url": destination_url,
            "query_params": query_params,
            "request_headers": dict(request_headers or {}),
            "api_password": self.api_password,
            "expiration": expiration_seconds,
        }
        if filename and endpoint == "/proxy/stream":
            payload["filename"] = filename

        try:
            async with self._client() as client:
                response = await client.post("/generate_url", json=payload)
                response.raise_for_status()
                response_payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MediaFlowError(
                "MEDIAFLOW_URL_GENERATION_FAILED",
                "MediaFlow could not generate a playback URL.",
                retryable=True,
            ) from exc

        generated_url = response_payload.get("url") if isinstance(response_payload, Mapping) else None
        if not isinstance(generated_url, str) or not self._safe_generated_url(generated_url, destination_url):
            raise MediaFlowError(
                "MEDIAFLOW_URL_SECURITY_FAILED",
                "MediaFlow returned a missing or unsafe playback URL.",
            )
        if normalized_mode == "transcode_hls" and _allow_hls_fallback:
            fallback_reason = None
            try:
                hls_is_safe = await self._hls_manifest_is_safe(generated_url, destination_url)
            except MediaFlowError as exc:
                hls_is_safe = False
                fallback_reason = exc.code
            if not hls_is_safe:
                fallback = await self.generate_signed_playback_url(
                    destination_url,
                    mode="transcode_stream",
                    start_seconds=start_seconds,
                    filename=filename,
                    request_headers=request_headers,
                    expiration_seconds=expiration_seconds,
                    force_audio_stereo=force_audio_stereo,
                    _allow_hls_fallback=False,
                )
                fallback["requested_mode"] = requested_mode
                fallback["fallback_reason"] = fallback_reason or "HLS_MANIFEST_UNSAFE"
                return fallback
        result = {
            "ok": True,
            "code": "MEDIAFLOW_PLAYBACK_URL_READY",
            "url": generated_url,
            "endpoint": endpoint,
            "mode": normalized_mode,
            "expires_in_seconds": expiration_seconds,
        }
        if requested_mode != normalized_mode:
            result["requested_mode"] = requested_mode
            result["fallback_reason"] = forced_mode_reason
        return result

    @staticmethod
    def _valid_destination_url(value: str) -> bool:
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

    @staticmethod
    def _mode_parameters(
        mode: str,
        start_seconds: Optional[float],
        *,
        force_audio_stereo: bool = False,
    ) -> tuple[str, Dict[str, str]]:
        normalized = mode.lower().strip()
        if normalized == "transcode_hls":
            endpoint = "/proxy/transcode/playlist.m3u8"
            params: Dict[str, str] = {}
        elif normalized == "transcode_stream":
            endpoint = "/proxy/stream"
            params = {"transcode": "true"}
            if force_audio_stereo:
                params["force_audio_stereo"] = "true"
        elif normalized == "direct_stream":
            endpoint = "/proxy/stream"
            params = {}
        else:
            raise MediaFlowError("MEDIAFLOW_MODE_INVALID", "The pilot mode is not supported.")
        if start_seconds is not None:
            if start_seconds < 0:
                raise MediaFlowError("MEDIAFLOW_START_INVALID", "Playback start time cannot be negative.")
            if endpoint == "/proxy/stream":
                params["start"] = str(start_seconds)
        return endpoint, params

    def _safe_generated_url(self, generated_url: str, destination_url: str) -> bool:
        try:
            parsed = urlsplit(generated_url)
        except ValueError:
            return False
        if parsed.scheme.lower() not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return False
        decoded_url = unquote(generated_url)
        if (
            destination_url in decoded_url
            or self.api_password in decoded_url
            or self.api_password in decoded_url.replace("+", " ")
        ):
            return False
        return True

    async def _hls_manifest_is_safe(self, playback_url: str, destination_url: str) -> bool:
        """Reject HLS manifests that expose source identity or proxy credentials."""
        try:
            async with self._client() as client:
                response = await client.get(playback_url)
                response.raise_for_status()
                body = response.text[:1_000_000]
        except (httpx.HTTPError, ValueError) as exc:
            raise MediaFlowError(
                "MEDIAFLOW_HLS_VALIDATION_FAILED",
                "MediaFlow HLS manifest validation failed.",
                retryable=True,
            ) from exc

        decoded_body = body
        for _ in range(3):
            decoded_body = unquote(decoded_body)
        if not decoded_body.lstrip().startswith("#EXTM3U"):
            raise MediaFlowError(
                "MEDIAFLOW_HLS_INVALID_MANIFEST",
                "MediaFlow returned an invalid HLS manifest.",
                retryable=True,
            )

        destination_host = (urlsplit(destination_url).hostname or "").lower()
        if destination_url in decoded_body or self.api_password in decoded_body:
            return False
        if destination_host and destination_host in decoded_body.lower():
            return False
        return re.search(r"(?i)(?:[?&])(?:d|api_password|h_[a-z0-9_-]+)=", decoded_body) is None
