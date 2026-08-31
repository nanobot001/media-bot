"""Bounded production adapter over the verified MediaFlow pilot contracts."""

from __future__ import annotations

import asyncio
import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional
from urllib.parse import urlsplit

from moviebot.adapters.alldebrid_client import AllDebridClient
from moviebot.adapters.mediaflow_client import MediaFlowClient, MediaFlowError
from moviebot.config import settings
from moviebot.core.mediaflow_capacity import MediaFlowCapacityRegistry, build_workload
from moviebot.core.mediaflow_diagnostics import (
    MEDIAFLOW_DECISION_VERSION,
    build_diagnostics,
    diagnostics_mode,
    project_diagnostics,
)
from moviebot.core.mediaflow_pilot import (
    DIRECT_PLAY,
    EXTERNAL_FALLBACK,
    FULL_TRANSCODE,
    SUBTITLE_BURN,
    choose_delivery_decision,
    probe_media_url,
    sanitize_runtime_metrics,
)


MEDIAFLOW_PINNED_VERSION = "2.4.9"
_SENSITIVE_TEXT = re.compile(
    r"(?i)(?:https?://|magnet:\?|api[_-]?password|authorization|bearer\s|token=)"
)


class MediaFlowAdapterError(RuntimeError):
    """A sanitized production-adapter failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        stage: str = "adapter",
        diagnostics: Optional[Dict[str, Any]] = None,
    ) -> None:
        safe_code = str(code or "MEDIAFLOW_ADAPTER_FAILED").strip().upper()[:80]
        if not re.fullmatch(r"[A-Z0-9_]+", safe_code):
            safe_code = "MEDIAFLOW_ADAPTER_FAILED"
        safe_message = (
            str(message or "MediaFlow playback failed.")
            .replace("\r", " ")
            .replace("\n", " ")
            .strip()[:240]
        )
        if not safe_message or _SENSITIVE_TEXT.search(safe_message):
            safe_message = "MediaFlow playback failed without retaining provider details."
        super().__init__(safe_message)
        self.code = safe_code
        self.message = safe_message
        self.retryable = retryable
        self.stage = stage
        context = diagnostics or {}
        self.diagnostics = build_diagnostics(
            stage=stage,
            code=safe_code,
            retryable=retryable,
            variant_id=context.get("variant_id"),
            delivery_decision=context.get("delivery_decision"),
            reasons=context.get("reasons"),
            source=context.get("source"),
            workload=context.get("workload"),
            guardrails=context.get("guardrails"),
            capacity=context.get("capacity"),
        )

    def public_diagnostics(self, *, mode: Optional[str] = None) -> Dict[str, Any]:
        return project_diagnostics(self.diagnostics, mode=mode)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_duration_seconds(inventory: Dict[str, Any]) -> Optional[float]:
    value = (inventory.get("format") or {}).get("duration_seconds")
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(duration) or duration <= 0:
        return None
    return round(duration, 3)


def _safe_size_bytes(value: Any) -> Optional[int]:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return None
    return size if size > 0 else None


def assess_transcode_capacity(
    inventory: Dict[str, Any],
    *,
    decision: Dict[str, Any],
    source_size_bytes: Optional[int] = None,
) -> Dict[str, Any]:
    """Apply legacy guardrails and return the sanitized workload reservation.

    Size and duration remain a fail-safe only when no calibrated profile has
    been configured for the workload class.  A configured local profile is the
    capability decision; size and duration are retained as evidence rather
    than treated as universal rejection rules.
    """
    heavy = decision.get("decision") in {FULL_TRANSCODE, SUBTITLE_BURN}

    format_info = inventory.get("format") if isinstance(inventory.get("format"), dict) else {}
    observed_sizes = [
        _safe_size_bytes(source_size_bytes),
        _safe_size_bytes(format_info.get("size_bytes")),
    ]
    observed_sizes = [value for value in observed_sizes if value is not None]
    effective_size = max(observed_sizes) if observed_sizes else None
    duration_seconds = _safe_duration_seconds(inventory)
    workload = build_workload(
        inventory,
        decision=decision,
        source_size_bytes=effective_size,
    )
    reasons = []

    max_size = _safe_size_bytes(getattr(settings, "mediaflow_max_heavy_transcode_size_bytes", 0))
    calibrated = workload.profile_source == "configured_measurement"
    if heavy and max_size and effective_size and effective_size > max_size and not calibrated:
        reasons.append("source_size_exceeds_heavy_transcode_limit")

    try:
        max_duration = float(getattr(settings, "mediaflow_max_heavy_transcode_duration_seconds", 0))
    except (TypeError, ValueError):
        max_duration = 0.0
    if heavy and max_duration > 0 and duration_seconds and duration_seconds > max_duration and not calibrated:
        reasons.append("duration_exceeds_heavy_transcode_limit")

    return {
        "admitted": not reasons,
        "resource_class": workload.resource_class,
        "reasons": reasons,
        "source_size_bytes": effective_size,
        "duration_seconds": duration_seconds,
        "profile_source": workload.profile_source,
        "workload": workload.as_dict(),
    }


def _diagnostic_context(
    *,
    variant: Dict[str, Any],
    inventory: Optional[Dict[str, Any]] = None,
    decision: Optional[Dict[str, Any]] = None,
    capacity: Optional[Dict[str, Any]] = None,
    capacity_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    inventory = inventory or {}
    decision = decision or {}
    capacity = capacity or {}
    format_info = inventory.get("format") if isinstance(inventory.get("format"), dict) else {}
    video_streams = inventory.get("video") if isinstance(inventory.get("video"), list) else []
    audio_streams = inventory.get("audio") if isinstance(inventory.get("audio"), list) else []
    video = video_streams[0] if video_streams and isinstance(video_streams[0], dict) else {}
    selected_audio_index = decision.get("selected_audio_index")
    audio = next(
        (
            stream
            for stream in audio_streams
            if isinstance(stream, dict) and stream.get("index") == selected_audio_index
        ),
        audio_streams[0] if audio_streams and isinstance(audio_streams[0], dict) else {},
    )
    source_size = capacity.get("source_size_bytes") or _safe_size_bytes(format_info.get("size_bytes"))
    return {
        "variant_id": variant.get("variant_id"),
        "delivery_decision": decision.get("decision"),
        "reasons": capacity.get("reasons") or [],
        "source": {
            "size_bytes": source_size,
            "duration_seconds": capacity.get("duration_seconds") or _safe_duration_seconds(inventory),
            "container": format_info.get("container"),
            "video_codec": video.get("codec_name"),
            "bit_depth": video.get("bit_depth"),
            "width": video.get("width"),
            "height": video.get("height"),
            "audio_codec": audio.get("codec_name"),
            "audio_channels": audio.get("channels"),
            "subtitle_mode": decision.get("subtitle_mode"),
            "hdr_action": decision.get("hdr_action"),
        },
        "workload": capacity.get("workload"),
        "guardrails": {
            "max_heavy_transcode_size_bytes": getattr(
                settings, "mediaflow_max_heavy_transcode_size_bytes", 0
            ),
            "max_heavy_transcode_duration_seconds": getattr(
                settings, "mediaflow_max_heavy_transcode_duration_seconds", 0
            ),
        },
        "capacity": capacity_state,
    }


def _public_decision(decision: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {
        "decision",
        "reason",
        "selected_audio_index",
        "selected_subtitle_index",
        "subtitle_mode",
        "video_transcode_required",
        "audio_transcode_required",
        "encoder_required",
        "accelerator",
        "hdr_action",
        "output",
    }
    return {key: decision[key] for key in allowed if key in decision}


def production_configuration() -> Dict[str, Any]:
    """Return operator-safe configuration state without secrets or private paths."""
    base_url = str(settings.mediaflow_url or "")
    parsed = urlsplit(base_url)
    local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    pin_valid = settings.mediaflow_expected_version == MEDIAFLOW_PINNED_VERSION
    return {
        "enabled": bool(settings.mediaflow_production_enabled),
        "configured": bool(settings.mediaflow_api_password) and local and pin_valid,
        "localhost_only": local,
        "expected_version": MEDIAFLOW_PINNED_VERSION,
        "pin_valid": pin_valid,
        "session_ttl_seconds": max(60, min(int(settings.mediaflow_session_ttl_seconds), 3600)),
        "diagnostics_mode": diagnostics_mode(),
        "decision_version": MEDIAFLOW_DECISION_VERSION,
    }


def require_production_configuration() -> Dict[str, Any]:
    state = production_configuration()
    if not state["enabled"]:
        raise MediaFlowAdapterError(
            "MEDIAFLOW_PRODUCTION_DISABLED",
            "MediaFlow browser playback is disabled by configuration.",
            stage="configuration",
        )
    if not state["localhost_only"]:
        raise MediaFlowAdapterError(
            "MEDIAFLOW_NON_LOCAL_URL",
            "MediaFlow production playback requires a localhost endpoint.",
            stage="configuration",
        )
    if not state["pin_valid"]:
        raise MediaFlowAdapterError(
            "MEDIAFLOW_VERSION_PIN_INVALID",
            "MediaFlow production playback requires the approved pinned version.",
            stage="configuration",
        )
    if not settings.mediaflow_api_password:
        raise MediaFlowAdapterError(
            "MEDIAFLOW_PASSWORD_MISSING",
            "MediaFlow production authentication is not configured.",
            stage="configuration",
        )
    return state


@dataclass
class _ProductionSession:
    session_id: str
    variant_id: str
    playback_url: str
    created_at: datetime
    expires_at: datetime
    decision: Dict[str, Any]
    mode: str
    source_url: str = ""
    filename: str = "media.mp4"
    force_audio_stereo: bool = False
    duration_seconds: Optional[float] = None
    capacity_reservation_id: Optional[str] = None
    workload: Optional[Dict[str, Any]] = None
    playback_status: str = "prepared"
    expiry_task: Optional[asyncio.Task] = None


class MediaFlowPlaybackRegistry:
    """Keep signed local playback URLs behind short-lived opaque session IDs."""

    def __init__(
        self,
        *,
        record_events: bool = False,
        capacity_registry: Optional[MediaFlowCapacityRegistry] = None,
    ) -> None:
        self._sessions: Dict[str, _ProductionSession] = {}
        self.record_events = record_events
        self.capacity_registry = capacity_registry or MediaFlowCapacityRegistry()

    def reserve_capacity(self, workload: Dict[str, Any]) -> Dict[str, Any]:
        from moviebot.core.mediaflow_capacity import MediaFlowWorkload

        return self.capacity_registry.reserve(MediaFlowWorkload(**workload))

    def release_capacity(self, reservation_id: Optional[str]) -> bool:
        return self.capacity_registry.release(reservation_id)

    def _record_cleanup(self, session: _ProductionSession, result: Dict[str, Any]) -> None:
        if not self.record_events:
            return
        try:
            import json

            from moviebot.db.release_variant_repo import ReleaseVariantRepository
            from moviebot.db.repositories import EventRepository

            variant = ReleaseVariantRepository.get_variant(session.variant_id) or {}
            EventRepository.insert(
                event_type="mediaflow_playback_closed",
                source="mediaflow",
                title=str(variant.get("title") or "MediaFlow playback"),
                summary="MediaFlow production playback session closed.",
                entity_type="release_variant",
                entity_id=session.variant_id,
                status="closed",
                severity="info",
                data_json=json.dumps(result, sort_keys=True),
            )
        except Exception:
            return

    def _purge_expired(self) -> None:
        now = _utc_now()
        for session_id in [
            key for key, value in self._sessions.items() if value.expires_at <= now
        ]:
            self.close(session_id, reason="timeout")

    def create(
        self,
        *,
        variant_id: str,
        playback_url: str,
        decision: Dict[str, Any],
        mode: str,
        ttl_seconds: int,
        source_url: str = "",
        filename: str = "media.mp4",
        force_audio_stereo: bool = False,
        duration_seconds: Optional[float] = None,
        capacity_reservation_id: Optional[str] = None,
        workload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self._purge_expired()
        session_id = f"mfp-{uuid.uuid4().hex}"
        created_at = _utc_now()
        session = _ProductionSession(
            session_id=session_id,
            variant_id=variant_id,
            playback_url=playback_url,
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=ttl_seconds),
            decision=_public_decision(decision),
            mode=mode,
            source_url=source_url,
            filename=filename,
            force_audio_stereo=force_audio_stereo,
            duration_seconds=duration_seconds,
            capacity_reservation_id=capacity_reservation_id,
            workload=workload,
        )
        if capacity_reservation_id and not self.capacity_registry.commit(capacity_reservation_id, session_id):
            raise RuntimeError("MediaFlow capacity reservation could not be committed.")
        if capacity_reservation_id:
            # The capacity registry keys committed reservations by the live
            # session id so TTL/close cleanup can release them deterministically.
            session.capacity_reservation_id = session_id
        self._sessions[session_id] = session
        try:
            session.expiry_task = asyncio.create_task(self._expire(session_id, ttl_seconds))
        except RuntimeError:
            session.expiry_task = None
        return self.snapshot(session_id)

    async def _expire(self, session_id: str, ttl_seconds: int) -> None:
        try:
            await asyncio.sleep(ttl_seconds)
            self.close(session_id, reason="timeout")
        except asyncio.CancelledError:
            return

    def get(self, session_id: str) -> Optional[_ProductionSession]:
        self._purge_expired()
        return self._sessions.get(session_id)

    def resolve(self, session_id: str) -> Optional[str]:
        session = self.get(session_id)
        return session.playback_url if session else None

    def snapshot(self, session_id: str) -> Dict[str, Any]:
        session = self._sessions[session_id]
        return {
            "session_id": session.session_id,
            "variant_id": session.variant_id,
            "created_at": session.created_at.isoformat(),
            "expires_at": session.expires_at.isoformat(),
            "decision": session.decision,
            "mode": session.mode,
            "duration_seconds": session.duration_seconds,
            "capacity_reservation_id": session.capacity_reservation_id,
            "workload": session.workload,
            "playback_status": session.playback_status,
        }

    def replace_playback_url(self, session_id: str, playback_url: str) -> Optional[Dict[str, Any]]:
        session = self.get(session_id)
        if session is None:
            return None
        session.playback_url = playback_url
        session.playback_status = "seeking"
        return self.snapshot(session_id)

    def mark(self, session_id: str, status: str) -> Optional[Dict[str, Any]]:
        session = self.get(session_id)
        if session is None:
            return None
        session.playback_status = status
        return self.snapshot(session_id)

    def close(self, session_id: str, *, reason: str = "closed") -> Dict[str, Any]:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return {
                "session_id": session_id,
                "cleanup_result": "already_closed",
                "exit_reason": reason,
                "upstream_disconnect_requested": False,
                "active_workers": None,
                "temporary_segment_count": None,
            }
        task = session.expiry_task
        try:
            current = asyncio.current_task() if task else None
        except RuntimeError:
            current = None
        if task and task is not current and not task.done():
            task.cancel()
        self.capacity_registry.release(session.capacity_reservation_id)
        session.playback_url = ""
        session.source_url = ""
        session.filename = ""
        result = {
            "session_id": session_id,
            "variant_id": session.variant_id,
            "cleanup_result": "complete",
            "exit_reason": reason,
            "upstream_disconnect_requested": True,
            # MediaFlow owns its FFmpeg/PyAV workers and temporary segments.
            # Do not claim zero until a separately authorized live canary
            # observes the container after the browser request disconnects.
            "active_workers": None,
            "temporary_segment_count": None,
        }
        self._record_cleanup(session, result)
        return result

    def close_all(self, *, reason: str = "shutdown") -> Dict[str, Any]:
        session_ids = list(self._sessions)
        results = [self.close(session_id, reason=reason) for session_id in session_ids]
        return {
            "cleanup_result": "complete",
            "closed_session_count": len(results),
            "active_workers": None,
            "temporary_segment_count": None,
        }

    def status(self) -> Dict[str, Any]:
        self._purge_expired()
        return {
            "active_session_count": len(self._sessions),
            **self.capacity_registry.status(),
        }


mediaflow_playback_registry = MediaFlowPlaybackRegistry(record_events=True)


class MediaFlowProductionAdapter:
    """Resolve one exact cached variant and prepare one opaque local session."""

    def __init__(
        self,
        *,
        mediaflow_client_factory: Callable[[], MediaFlowClient] = MediaFlowClient,
        alldebrid_client_factory: Callable[[], AllDebridClient] = AllDebridClient,
        resolver: Optional[Callable[[str, str], str]] = None,
        probe: Callable[..., Awaitable[Dict[str, Any]]] = probe_media_url,
        registry: MediaFlowPlaybackRegistry = mediaflow_playback_registry,
    ) -> None:
        self.mediaflow_client_factory = mediaflow_client_factory
        self.alldebrid_client_factory = alldebrid_client_factory
        self.resolver = resolver
        self.probe = probe
        self.registry = registry

    def _resolve_reference(self, reference_id: str, domain: str) -> str:
        if self.resolver is not None:
            return self.resolver(reference_id, domain)
        from moviebot.core.background_prewarmer import resolve_magnet_uri

        return resolve_magnet_uri(reference_id, domain=domain)

    async def health(self) -> Dict[str, Any]:
        config = require_production_configuration()
        try:
            health = await self.mediaflow_client_factory().health()
        except MediaFlowError as exc:
            raise MediaFlowAdapterError(
                exc.code,
                exc.message,
                retryable=exc.retryable,
                stage="service_health",
            ) from exc
        if not health.get("ok"):
            raise MediaFlowAdapterError(
                str(health.get("code") or "MEDIAFLOW_HEALTH_FAILED"),
                "MediaFlow health check failed.",
                retryable=True,
                stage="service_health",
            )
        return {**config, "health": health, **self.registry.status()}

    async def prepare(
        self,
        variant: Dict[str, Any],
        *,
        file_id: Optional[int] = None,
        start_seconds: Optional[float] = None,
        audio_index: Optional[int] = None,
        subtitle_index: Optional[int] = None,
        supports_hls: bool = False,
    ) -> Dict[str, Any]:
        config = await self.health()
        variant_context = {"variant_id": variant.get("variant_id")}
        reference_id = str(variant.get("reference_id") or "").strip()
        if not reference_id:
            raise MediaFlowAdapterError(
                "MEDIAFLOW_VARIANT_REFERENCE_MISSING",
                "The selected catalog variant has no resolvable source reference.",
                stage="source_resolution",
                diagnostics=variant_context,
            )
        try:
            magnet = self._resolve_reference(
                reference_id,
                str(variant.get("domain") or "movies"),
            )
        except Exception as exc:
            raise MediaFlowAdapterError(
                "MEDIAFLOW_VARIANT_REFERENCE_UNRESOLVABLE",
                "The selected catalog variant source could not be resolved.",
                stage="source_resolution",
                diagnostics=variant_context,
            ) from exc
        if not magnet.startswith("magnet:"):
            raise MediaFlowAdapterError(
                "MEDIAFLOW_VARIANT_REFERENCE_UNRESOLVABLE",
                "The selected catalog variant source could not be resolved.",
                stage="source_resolution",
                diagnostics=variant_context,
            )

        try:
            payload = await self.alldebrid_client_factory().unlock_magnet_stream(
                magnet_link=magnet,
                file_id=file_id,
                season=int(variant.get("season") or 0) or None,
                episode=int(variant.get("episode") or 0) or None,
            )
        except Exception as exc:
            raise MediaFlowAdapterError(
                getattr(exc, "code", "MEDIAFLOW_SOURCE_UNLOCK_FAILED"),
                "The selected cached variant could not be opened for MediaFlow.",
                retryable=bool(getattr(exc, "retryable", False)),
                stage="source_unlock",
                diagnostics=variant_context,
            ) from exc

        if not isinstance(payload, dict):
            raise MediaFlowAdapterError(
                "MEDIAFLOW_SOURCE_UNLOCK_INVALID",
                "The selected cached variant returned an invalid source response.",
                stage="source_unlock",
                diagnostics=variant_context,
            )
        source_url = str(payload.get("stream_url") or "")
        try:
            probe_result = await self.probe(source_url)
        except Exception as exc:
            raise MediaFlowAdapterError(
                "MEDIAFLOW_PROBE_FAILED",
                "The selected variant could not be safely inspected.",
                retryable=True,
                stage="probe",
                diagnostics=variant_context,
            ) from exc
        if not probe_result.get("ok"):
            raise MediaFlowAdapterError(
                str(probe_result.get("code") or "MEDIAFLOW_PROBE_FAILED"),
                str(probe_result.get("message") or "The selected variant could not be safely inspected."),
                retryable=bool(probe_result.get("retryable", False)),
                stage="probe",
                diagnostics=variant_context,
            )
        inventory = probe_result.get("inventory") or {}
        duration_seconds = _safe_duration_seconds(inventory)
        source_size_bytes = max(
            filter(
                None,
                (
                    _safe_size_bytes(payload.get("filesize")),
                    _safe_size_bytes(variant.get("size_bytes")),
                    _safe_size_bytes((inventory.get("format") or {}).get("size_bytes")),
                ),
            ),
            default=None,
        )
        decision = choose_delivery_decision(
            inventory,
            delivery_mode="hls" if supports_hls else "direct",
            audio_index=audio_index,
            subtitle_index=subtitle_index,
            target_audio_channels="stereo",
        )
        if decision.get("decision") == EXTERNAL_FALLBACK:
            raise MediaFlowAdapterError(
                "MEDIAFLOW_DELIVERY_UNSAFE",
                str(decision.get("reason") or "No safe MediaFlow browser delivery path was proven."),
                stage="delivery_policy",
                diagnostics=_diagnostic_context(
                    variant=variant,
                    inventory=inventory,
                    decision=decision,
                    capacity={"source_size_bytes": source_size_bytes, "duration_seconds": duration_seconds},
                ),
            )
        capacity = assess_transcode_capacity(
            inventory,
            decision=decision,
            source_size_bytes=source_size_bytes,
        )
        if not capacity["admitted"]:
            raise MediaFlowAdapterError(
                "MEDIAFLOW_TRANSCODE_TOO_EXPENSIVE",
                "This release is too expensive for reliable MediaFlow browser playback under current capacity. Use another release or an external player.",
                retryable=False,
                stage="admission",
                diagnostics=_diagnostic_context(
                    variant=variant,
                    inventory=inventory,
                    decision=decision,
                    capacity=capacity,
                    capacity_state=self.registry.status().get("capacity"),
                ),
            )

        reservation = self.registry.reserve_capacity(capacity["workload"])
        if not reservation["admitted"]:
            raise MediaFlowAdapterError(
                "MEDIAFLOW_CAPACITY_BUSY",
                "MediaFlow is at its safe transcode capacity. Retry shortly or use an external player.",
                retryable=True,
                stage="capacity_reservation",
                diagnostics=_diagnostic_context(
                    variant=variant,
                    inventory=inventory,
                    decision=decision,
                    capacity=capacity,
                    capacity_state={
                        "used": reservation.get("used"),
                        "limits": reservation.get("limits"),
                        "reasons": reservation.get("reasons"),
                    },
                ),
            )
        reservation_id = reservation.get("reservation_id")

        force_audio_stereo = bool(decision.get("audio_downmix_required"))
        if force_audio_stereo:
            capabilities = ((config.get("health") or {}).get("capabilities") or {})
            if capabilities.get("force_audio_stereo") is not True:
                self.registry.release_capacity(reservation_id)
                raise MediaFlowAdapterError(
                    "MEDIAFLOW_AUDIO_STEREO_UNSUPPORTED",
                    "The configured MediaFlow service cannot prove stereo downmix support.",
                    stage="delivery_policy",
                    diagnostics=_diagnostic_context(
                        variant=variant,
                        inventory=inventory,
                        decision=decision,
                        capacity=capacity,
                    ),
                )

        requested_mode = (
            "direct_stream"
            if decision.get("decision") == DIRECT_PLAY
            else ("transcode_hls" if supports_hls else "transcode_stream")
        )
        try:
            playback = await self.mediaflow_client_factory().generate_signed_playback_url(
                source_url,
                mode=requested_mode,
                start_seconds=start_seconds,
                filename=str(payload.get("filename") or variant.get("release_title") or "media.mp4"),
                expiration_seconds=config["session_ttl_seconds"],
                force_audio_stereo=force_audio_stereo,
            )
        except MediaFlowError as exc:
            self.registry.release_capacity(reservation_id)
            raise MediaFlowAdapterError(
                exc.code,
                exc.message,
                retryable=exc.retryable,
                stage="url_generation",
                diagnostics=_diagnostic_context(
                    variant=variant,
                    inventory=inventory,
                    decision=decision,
                    capacity=capacity,
                ),
            ) from exc
        except Exception:
            self.registry.release_capacity(reservation_id)
            raise

        filename = str(payload.get("filename") or variant.get("release_title") or "media.mp4")
        session = self.registry.create(
            variant_id=str(variant["variant_id"]),
            playback_url=str(playback["url"]),
            decision=decision,
            mode=str(playback.get("mode") or requested_mode),
            ttl_seconds=config["session_ttl_seconds"],
            source_url=source_url,
            filename=filename,
            force_audio_stereo=force_audio_stereo,
            duration_seconds=duration_seconds,
            capacity_reservation_id=reservation_id,
            workload=capacity["workload"],
        )
        return {
            **session,
            "filename": variant.get("release_title") or "Selected cached version",
            "filesize": int(payload.get("filesize") or variant.get("size_bytes") or 0),
            "duration_seconds": duration_seconds,
            "mime_type": (
                "application/vnd.apple.mpegurl"
                if session["mode"] == "transcode_hls"
                else "video/mp4"
            ),
            "fallback_reason": playback.get("fallback_reason"),
            "runtime_metrics": sanitize_runtime_metrics({"accelerator": decision.get("accelerator")}),
            "capacity": {
                "admitted": True,
                "profile_source": capacity.get("profile_source"),
                "workload": capacity.get("workload"),
                "reservation_id": reservation_id,
            },
        }

    async def seek(self, session_id: str, start_seconds: float) -> Dict[str, Any]:
        """Rotate one opaque session to a new transcoding start position."""
        try:
            target = float(start_seconds)
        except (TypeError, ValueError) as exc:
            raise MediaFlowAdapterError(
                "MEDIAFLOW_SEEK_INVALID",
                "The requested seek position is invalid.",
                stage="seek",
            ) from exc
        if not math.isfinite(target) or target < 0:
            raise MediaFlowAdapterError(
                "MEDIAFLOW_SEEK_INVALID",
                "The requested seek position is invalid.",
                stage="seek",
            )

        session = self.registry.get(session_id)
        if session is None:
            raise MediaFlowAdapterError(
                "MEDIAFLOW_SESSION_NOT_FOUND",
                "The MediaFlow playback session is unavailable.",
                stage="seek",
            )
        if session.mode != "transcode_stream":
            raise MediaFlowAdapterError(
                "MEDIAFLOW_SEEK_UNSUPPORTED",
                "This MediaFlow delivery mode does not support session seeking.",
                stage="seek",
                diagnostics={
                    "variant_id": session.variant_id,
                    "delivery_decision": session.decision.get("decision"),
                    "workload": session.workload,
                },
            )
        if not session.source_url:
            raise MediaFlowAdapterError(
                "MEDIAFLOW_SEEK_SOURCE_UNAVAILABLE",
                "The MediaFlow playback source is no longer available.",
                stage="seek",
                diagnostics={
                    "variant_id": session.variant_id,
                    "delivery_decision": session.decision.get("decision"),
                    "workload": session.workload,
                },
            )
        if session.duration_seconds is not None:
            target = min(target, session.duration_seconds)

        config = await self.health()
        remaining_ttl = max(1, int((session.expires_at - _utc_now()).total_seconds()))
        try:
            playback = await self.mediaflow_client_factory().generate_signed_playback_url(
                session.source_url,
                mode=session.mode,
                start_seconds=round(target, 3),
                filename=session.filename,
                expiration_seconds=min(24 * 60 * 60, remaining_ttl),
                force_audio_stereo=session.force_audio_stereo,
            )
        except MediaFlowError as exc:
            raise MediaFlowAdapterError(
                exc.code,
                exc.message,
                retryable=exc.retryable,
                stage="seek",
                diagnostics={
                    "variant_id": session.variant_id,
                    "delivery_decision": session.decision.get("decision"),
                    "workload": session.workload,
                },
            ) from exc

        snapshot = self.registry.replace_playback_url(session_id, str(playback["url"]))
        if snapshot is None:
            raise MediaFlowAdapterError(
                "MEDIAFLOW_SESSION_NOT_FOUND",
                "The MediaFlow playback session is unavailable.",
                stage="seek",
            )
        return {
            **snapshot,
            "start_seconds": round(target, 3),
            "duration_seconds": session.duration_seconds,
            "mode": playback.get("mode") or session.mode,
            "runtime_metrics": sanitize_runtime_metrics({
                "seek_target_seconds": round(target, 3),
            }),
        }
