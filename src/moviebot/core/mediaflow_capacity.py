"""Capacity-aware MediaFlow admission and benchmark profile helpers.

The application cannot safely infer MediaFlow's actual encoder cost from file
size alone.  This module therefore keeps the decision explicit: a workload is
assigned a bounded resource reservation, and active reservations are compared
atomically with the configured MediaFlow budget before a heavy stream starts.

The built-in profiles are conservative fallbacks.  Operators can replace them
with profiles calculated from local benchmark samples through
``calculate_measured_profiles`` without exposing provider or command details.
"""

from __future__ import annotations

import json
import math
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional

from moviebot.config import settings
from moviebot.core.mediaflow_pilot import (
    AUDIO_TRANSCODE,
    DIRECT_PLAY,
    FULL_TRANSCODE,
    REMUX_COPY,
    SUBTITLE_BURN,
)


HEAVY_WORKLOAD_CLASSES = {"video_transcode", "subtitle_burn"}
LIGHT_WORKLOAD_CLASSES = {"direct_play", "remux_copy"}
KNOWN_WORKLOAD_CLASSES = {
    "audio_transcode",
    "video_transcode",
    "subtitle_burn",
    *LIGHT_WORKLOAD_CLASSES,
}

# These values are deliberately conservative fallbacks, not claimed hardware
# measurements.  A local benchmark can replace them through the JSON setting.
_CONSERVATIVE_PROFILES: Dict[str, Dict[str, Any]] = {
    "audio_transcode": {
        "cpu_cores": 0.75,
        "memory_mb": 384,
        "gpu_percent": 0.0,
        "encoder_slots": 0,
    },
    "video_transcode": {
        "cpu_cores": 2.5,
        "memory_mb": 1024,
        "gpu_percent": 75.0,
        "encoder_slots": 1,
    },
    "subtitle_burn": {
        "cpu_cores": 3.0,
        "memory_mb": 1280,
        "gpu_percent": 90.0,
        "encoder_slots": 1,
    },
}


def _finite_float(value: Any, *, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) and parsed >= 0 else default


def _positive_int(value: Any, *, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _nearest_rank_percentile(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("At least one benchmark value is required.")
    rank = max(1, math.ceil(len(ordered) * percentile))
    return ordered[min(rank - 1, len(ordered) - 1)]


@dataclass(frozen=True)
class MediaFlowWorkload:
    """Sanitized resource requirement for one prospective MediaFlow session."""

    workload_class: str
    resource_class: str
    cpu_cores: float
    memory_mb: int
    gpu_percent: float
    encoder_slots: int
    heavy: bool
    profile_source: str
    source_size_bytes: Optional[int] = None
    duration_seconds: Optional[float] = None
    video_codec: Optional[str] = None
    bit_depth: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    audio_codec: Optional[str] = None
    audio_channels: Optional[int] = None
    subtitle_mode: str = "none"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "workload_class": self.workload_class,
            "resource_class": self.resource_class,
            "cpu_cores": self.cpu_cores,
            "memory_mb": self.memory_mb,
            "gpu_percent": self.gpu_percent,
            "encoder_slots": self.encoder_slots,
            "heavy": self.heavy,
            "profile_source": self.profile_source,
            "source_size_bytes": self.source_size_bytes,
            "duration_seconds": self.duration_seconds,
            "video_codec": self.video_codec,
            "bit_depth": self.bit_depth,
            "width": self.width,
            "height": self.height,
            "audio_codec": self.audio_codec,
            "audio_channels": self.audio_channels,
            "subtitle_mode": self.subtitle_mode,
        }


@dataclass(frozen=True)
class MediaFlowCapacityConfig:
    """Configured budget for reservations, not a claim about live OS usage."""

    cpu_cores: float
    memory_mb: int
    gpu_percent: float
    encoder_slots: int
    max_heavy_sessions: int
    safety_factor: float
    baseline_cpu_cores: float
    baseline_memory_mb: int
    baseline_gpu_percent: float
    profiles: Mapping[str, Mapping[str, Any]]
    configured_profile_names: frozenset[str]

    @classmethod
    def from_settings(cls) -> "MediaFlowCapacityConfig":
        configured_profiles: Dict[str, Mapping[str, Any]] = {}
        raw_profiles = str(getattr(settings, "mediaflow_capacity_profiles_json", "") or "").strip()
        if raw_profiles:
            try:
                parsed = json.loads(raw_profiles)
            except (TypeError, ValueError):
                parsed = {}
            if isinstance(parsed, Mapping):
                for name, profile in parsed.items():
                    normalized_name = str(name).strip().lower()
                    if normalized_name in KNOWN_WORKLOAD_CLASSES and isinstance(profile, Mapping):
                        configured_profiles[normalized_name] = dict(profile)

        profiles: Dict[str, Mapping[str, Any]] = {
            name: dict(profile) for name, profile in _CONSERVATIVE_PROFILES.items()
        }
        profiles.update(configured_profiles)
        return cls(
            cpu_cores=max(0.1, _finite_float(getattr(settings, "mediaflow_capacity_cpu_cores", 4.0), default=4.0)),
            memory_mb=max(128, _positive_int(getattr(settings, "mediaflow_capacity_memory_mb", 2048), default=2048)),
            gpu_percent=min(100.0, max(0.0, _finite_float(getattr(settings, "mediaflow_capacity_gpu_percent", 100.0), default=100.0))),
            encoder_slots=max(0, _positive_int(getattr(settings, "mediaflow_capacity_encoder_slots", 1), default=1)),
            max_heavy_sessions=max(0, _positive_int(getattr(settings, "mediaflow_capacity_max_heavy_sessions", 1), default=1)),
            safety_factor=max(1.0, _finite_float(getattr(settings, "mediaflow_capacity_safety_factor", 1.25), default=1.25)),
            baseline_cpu_cores=max(0.0, _finite_float(getattr(settings, "mediaflow_capacity_baseline_cpu_cores", 0.5), default=0.5)),
            baseline_memory_mb=max(0, _positive_int(getattr(settings, "mediaflow_capacity_baseline_memory_mb", 256), default=256)),
            baseline_gpu_percent=min(100.0, max(0.0, _finite_float(getattr(settings, "mediaflow_capacity_baseline_gpu_percent", 0.0), default=0.0))),
            profiles=profiles,
            configured_profile_names=frozenset(configured_profiles),
        )


def calculate_measured_profiles(
    samples: Iterable[Mapping[str, Any]],
    *,
    safety_factor: float = 1.25,
) -> Dict[str, Dict[str, Any]]:
    """Calculate p95 reservation profiles from healthy local benchmark samples.

    Each sample must contain ``workload_class``, ``healthy`` and per-session
    resource observations: ``cpu_cores``, ``memory_mb``, ``gpu_percent`` and
    ``encoder_slots``.  Samples are expected to come from the local MediaFlow
    pilot harness; raw URLs, commands and credentials are neither consumed nor
    returned.
    """
    factor = max(1.0, _finite_float(safety_factor, default=1.25))
    grouped: Dict[str, list[Mapping[str, Any]]] = {}
    for sample in samples:
        if not isinstance(sample, Mapping) or sample.get("healthy") is not True:
            continue
        name = str(sample.get("workload_class") or "").strip().lower()
        if name not in KNOWN_WORKLOAD_CLASSES or name in LIGHT_WORKLOAD_CLASSES:
            continue
        grouped.setdefault(name, []).append(sample)

    profiles: Dict[str, Dict[str, Any]] = {}
    for name, group in grouped.items():
        if not group:
            continue
        profiles[name] = {
            "cpu_cores": round(_nearest_rank_percentile((_finite_float(item.get("cpu_cores")) for item in group), 0.95) * factor, 2),
            "memory_mb": int(math.ceil(_nearest_rank_percentile((_finite_float(item.get("memory_mb")) for item in group), 0.95) * factor)),
            "gpu_percent": round(min(100.0, _nearest_rank_percentile((_finite_float(item.get("gpu_percent")) for item in group), 0.95) * factor), 2),
            "encoder_slots": max(_positive_int(item.get("encoder_slots")) for item in group),
            "profile_source": "benchmark_p95",
            "sample_count": len(group),
        }
    return profiles


def _selected_stream(inventory: Mapping[str, Any], streams_key: str, selected_index: Any) -> Mapping[str, Any]:
    streams = inventory.get(streams_key) if isinstance(inventory.get(streams_key), list) else []
    for stream in streams:
        if isinstance(stream, Mapping) and stream.get("index") == selected_index:
            return stream
    return next((stream for stream in streams if isinstance(stream, Mapping)), {})


def _profile_numbers(profile: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        # Profile values are reservations.  calculate_measured_profiles applies
        # its safety factor before returning them.
        "cpu_cores": round(_finite_float(profile.get("cpu_cores")), 2),
        "memory_mb": int(math.ceil(_finite_float(profile.get("memory_mb")))),
        "gpu_percent": round(min(100.0, _finite_float(profile.get("gpu_percent"))), 2),
        "encoder_slots": _positive_int(profile.get("encoder_slots")),
    }


def build_workload(
    inventory: Mapping[str, Any],
    *,
    decision: Mapping[str, Any],
    source_size_bytes: Optional[int] = None,
    capacity_config: Optional[MediaFlowCapacityConfig] = None,
) -> MediaFlowWorkload:
    """Map sanitized inventory and delivery decision to a bounded profile."""
    config = capacity_config or MediaFlowCapacityConfig.from_settings()
    decision_name = str(decision.get("decision") or "").strip().lower()
    class_by_decision = {
        DIRECT_PLAY: "direct_play",
        REMUX_COPY: "remux_copy",
        AUDIO_TRANSCODE: "audio_transcode",
        FULL_TRANSCODE: "video_transcode",
        SUBTITLE_BURN: "subtitle_burn",
    }
    workload_class = class_by_decision.get(decision_name, "video_transcode")
    profile = config.profiles.get(workload_class, {})
    numbers = _profile_numbers(profile)
    format_info = inventory.get("format") if isinstance(inventory.get("format"), Mapping) else {}
    video = _selected_stream(inventory, "video", decision.get("selected_video_index"))
    audio = _selected_stream(inventory, "audio", decision.get("selected_audio_index"))
    duration = _finite_float(inventory.get("duration_seconds"), default=0.0) or _finite_float(format_info.get("duration_seconds"), default=0.0)

    if workload_class in LIGHT_WORKLOAD_CLASSES:
        numbers = {"cpu_cores": 0.0, "memory_mb": 0, "gpu_percent": 0.0, "encoder_slots": 0}

    return MediaFlowWorkload(
        workload_class=workload_class,
        resource_class="heavy_transcode" if workload_class in HEAVY_WORKLOAD_CLASSES else workload_class,
        cpu_cores=numbers["cpu_cores"],
        memory_mb=numbers["memory_mb"],
        gpu_percent=numbers["gpu_percent"],
        encoder_slots=numbers["encoder_slots"],
        heavy=workload_class in HEAVY_WORKLOAD_CLASSES,
        profile_source=("configured_measurement" if workload_class in config.configured_profile_names else "conservative_default"),
        source_size_bytes=source_size_bytes,
        duration_seconds=round(duration, 3) if duration > 0 else None,
        video_codec=str(video.get("codec_name") or "").lower() or None,
        bit_depth=_positive_int(video.get("bit_depth")) or None,
        width=_positive_int(video.get("width")) or None,
        height=_positive_int(video.get("height")) or None,
        audio_codec=str(audio.get("codec_name") or "").lower() or None,
        audio_channels=_positive_int(audio.get("channels")) or None,
        subtitle_mode=str(decision.get("subtitle_mode") or "none"),
    )


class MediaFlowCapacityRegistry:
    """Atomically reserve and release bounded MediaFlow workload capacity."""

    def __init__(self, *, config: Optional[MediaFlowCapacityConfig] = None) -> None:
        self.config = config or MediaFlowCapacityConfig.from_settings()
        self._reservations: Dict[str, MediaFlowWorkload] = {}
        self._lock = threading.Lock()

    def _used(self) -> Dict[str, Any]:
        return {
            "cpu_cores": round(sum(item.cpu_cores for item in self._reservations.values()), 2),
            "memory_mb": sum(item.memory_mb for item in self._reservations.values()),
            "gpu_percent": round(sum(item.gpu_percent for item in self._reservations.values()), 2),
            "encoder_slots": sum(item.encoder_slots for item in self._reservations.values()),
            "heavy_sessions": sum(1 for item in self._reservations.values() if item.heavy),
        }

    def _limits(self) -> Dict[str, Any]:
        return {
            "cpu_cores": round(max(0.0, self.config.cpu_cores - self.config.baseline_cpu_cores), 2),
            "memory_mb": max(0, self.config.memory_mb - self.config.baseline_memory_mb),
            "gpu_percent": round(max(0.0, self.config.gpu_percent - self.config.baseline_gpu_percent), 2),
            "encoder_slots": self.config.encoder_slots,
            "heavy_sessions": self.config.max_heavy_sessions,
        }

    def _capacity_reasons(self, workload: MediaFlowWorkload) -> list[str]:
        used = self._used()
        limits = self._limits()
        reasons = []
        for key in ("cpu_cores", "memory_mb", "gpu_percent", "encoder_slots"):
            if used[key] + getattr(workload, key) > limits[key]:
                reasons.append(f"{key}_budget_exhausted")
        if workload.heavy and used["heavy_sessions"] >= limits["heavy_sessions"]:
            reasons.append("heavy_session_limit_reached")
        return reasons

    def reserve(self, workload: MediaFlowWorkload) -> Dict[str, Any]:
        """Attempt an atomic reservation and return a sanitized decision."""
        with self._lock:
            reasons = self._capacity_reasons(workload) if any(
                getattr(workload, key) for key in ("cpu_cores", "memory_mb", "gpu_percent", "encoder_slots")
            ) else []
            if reasons:
                return {
                    "admitted": False,
                    "code": "MEDIAFLOW_CAPACITY_BUSY",
                    "retryable": True,
                    "reasons": reasons,
                    "workload": workload.as_dict(),
                    "used": self._used(),
                    "limits": self._limits(),
                }
            if not reasons and not any(
                getattr(workload, key) for key in ("cpu_cores", "memory_mb", "gpu_percent", "encoder_slots")
            ):
                return {
                    "admitted": True,
                    "code": "MEDIAFLOW_CAPACITY_NOT_REQUIRED",
                    "retryable": False,
                    "reservation_id": None,
                    "reasons": [],
                    "workload": workload.as_dict(),
                    "used": self._used(),
                    "limits": self._limits(),
                }
            reservation_id = f"mfc-{uuid.uuid4().hex}"
            self._reservations[reservation_id] = workload
            return {
                "admitted": True,
                "code": "MEDIAFLOW_CAPACITY_ADMITTED",
                "retryable": False,
                "reservation_id": reservation_id,
                "reasons": [],
                "workload": workload.as_dict(),
                "used": self._used(),
                "limits": self._limits(),
            }

    def commit(self, reservation_id: str, session_id: str) -> bool:
        with self._lock:
            workload = self._reservations.pop(reservation_id, None)
            if workload is None:
                return False
            self._reservations[session_id] = workload
            return True

    def release(self, reservation_id: Optional[str]) -> bool:
        if not reservation_id:
            return False
        with self._lock:
            return self._reservations.pop(reservation_id, None) is not None

    def status(self) -> Dict[str, Any]:
        with self._lock:
            used = self._used()
            limits = self._limits()
            return {
                "capacity_profile_source": (
                    "configured_measurement"
                    if self.config.configured_profile_names
                    else "conservative_default"
                ),
                "capacity": {
                    "used": used,
                    "limits": limits,
                    "available": {
                        key: max(0, round(limits[key] - used[key], 2))
                        if isinstance(limits[key], float)
                        else max(0, limits[key] - used[key])
                        for key in limits
                    },
                    "configured_profile_names": sorted(self.config.configured_profile_names),
                },
            }
