"""Sanitized, versioned MediaFlow diagnostics projections."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional

from moviebot.config import settings


MEDIAFLOW_DIAGNOSTICS_SCHEMA_VERSION = 1
MEDIAFLOW_DECISION_VERSION = "mediaflow-admission-v1"
MEDIAFLOW_DIAGNOSTICS_MODES = {"off", "summary", "detailed"}

_SAFE_STAGE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")
_SAFE_REASON = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_SAFE_TEXT = re.compile(r"^[A-Za-z0-9_ .:/+()-]{1,120}$")
_SENSITIVE_TEXT = re.compile(
    r"(?i)(?:https?://|magnet:\?|api[_-]?password|authorization|bearer\s|token=|[a-z]:\\)"
)

_SOURCE_KEYS = {
    "size_bytes",
    "duration_seconds",
    "container",
    "video_codec",
    "bit_depth",
    "width",
    "height",
    "audio_codec",
    "audio_channels",
    "subtitle_mode",
    "hdr_action",
}
_WORKLOAD_KEYS = {
    "workload_class",
    "resource_class",
    "profile_source",
    "cpu_cores",
    "memory_mb",
    "gpu_percent",
    "encoder_slots",
    "heavy",
}
_GUARDRAIL_KEYS = {
    "max_heavy_transcode_size_bytes",
    "max_heavy_transcode_duration_seconds",
}
_CAPACITY_KEYS = {"used", "limits", "available", "reasons"}
_BUDGET_KEYS = {
    "cpu_cores",
    "memory_mb",
    "gpu_percent",
    "encoder_slots",
    "heavy_sessions",
}


def diagnostics_mode(value: Optional[str] = None) -> str:
    normalized = str(
        value if value is not None else getattr(settings, "mediaflow_diagnostics_mode", "summary")
    ).strip().lower()
    return normalized if normalized in MEDIAFLOW_DIAGNOSTICS_MODES else "summary"


def _safe_number(value: Any) -> Optional[int | float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return int(number) if number.is_integer() else round(number, 3)


def _safe_label(value: Any, *, pattern: re.Pattern[str] = _SAFE_TEXT) -> Optional[str]:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()[:120]
    if not text or _SENSITIVE_TEXT.search(text) or not pattern.fullmatch(text):
        return None
    return text


def _safe_mapping(value: Any, allowed: set[str]) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result: Dict[str, Any] = {}
    for key in allowed:
        raw = value.get(key)
        if raw is None:
            continue
        if isinstance(raw, bool):
            result[key] = raw
        elif isinstance(raw, (int, float)):
            number = _safe_number(raw)
            if number is not None:
                result[key] = number
        else:
            label = _safe_label(raw)
            if label is not None:
                result[key] = label
    return result


def _safe_capacity(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result: Dict[str, Any] = {}
    for key in _CAPACITY_KEYS:
        raw = value.get(key)
        if key == "reasons":
            reasons = _safe_reasons(raw)
            if reasons:
                result[key] = reasons
        elif isinstance(raw, Mapping):
            projection = _safe_mapping(raw, _BUDGET_KEYS)
            if projection:
                result[key] = projection
    return result


def _safe_reasons(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    result = []
    for value in values:
        reason = _safe_label(value, pattern=_SAFE_REASON)
        if reason and reason not in result:
            result.append(reason)
        if len(result) >= 8:
            break
    return result


def safe_next_action(code: str) -> str:
    actions = {
        "MEDIAFLOW_TRANSCODE_TOO_EXPENSIVE": "choose_another_release_or_external_player",
        "MEDIAFLOW_CAPACITY_BUSY": "retry_shortly_or_choose_another_release",
        "MEDIAFLOW_DELIVERY_UNSAFE": "choose_compatible_release_or_external_player",
        "MEDIAFLOW_PROBE_FAILED": "retry_probe_or_choose_another_release",
        "MEDIAFLOW_BROWSER_PLAYBACK_FAILED": "choose_another_release_or_external_player",
        "MEDIAFLOW_SEEK_FAILED": "restart_playback_or_use_external_player",
    }
    return actions.get(str(code or "").upper(), "review_diagnostics_or_choose_another_release")


def build_diagnostics(
    *,
    stage: str,
    code: str,
    retryable: bool = False,
    variant_id: Optional[str] = None,
    delivery_decision: Optional[str] = None,
    reasons: Optional[Iterable[str]] = None,
    source: Optional[Mapping[str, Any]] = None,
    workload: Optional[Mapping[str, Any]] = None,
    guardrails: Optional[Mapping[str, Any]] = None,
    capacity: Optional[Mapping[str, Any]] = None,
    occurred_at: Optional[str] = None,
) -> Dict[str, Any]:
    safe_stage = _safe_label(stage, pattern=_SAFE_STAGE) or "unknown"
    safe_code = _safe_label(str(code or "").upper(), pattern=_SAFE_CODE) or "MEDIAFLOW_ADAPTER_FAILED"
    envelope: Dict[str, Any] = {
        "schema_version": MEDIAFLOW_DIAGNOSTICS_SCHEMA_VERSION,
        "decision_version": MEDIAFLOW_DECISION_VERSION,
        "occurred_at": occurred_at or datetime.now(timezone.utc).isoformat(),
        "stage": safe_stage,
        "code": safe_code,
        "retryable": bool(retryable),
        "safe_next_action": safe_next_action(safe_code),
        "stale": False,
    }
    safe_variant = _safe_label(variant_id, pattern=re.compile(r"^[A-Za-z0-9_-]{1,80}$"))
    if safe_variant:
        envelope["variant_id"] = safe_variant
    safe_decision = _safe_label(delivery_decision, pattern=_SAFE_REASON)
    if safe_decision:
        envelope["delivery_decision"] = safe_decision
    safe_reasons = _safe_reasons(list(reasons or []))
    if safe_reasons:
        envelope["reasons"] = safe_reasons
    for key, value, allowed in (
        ("source", source, _SOURCE_KEYS),
        ("workload", workload, _WORKLOAD_KEYS),
        ("guardrails", guardrails, _GUARDRAIL_KEYS),
    ):
        projection = _safe_mapping(value, allowed)
        if projection:
            envelope[key] = projection
    capacity_projection = _safe_capacity(capacity)
    if capacity_projection:
        envelope["capacity"] = capacity_projection
    return envelope


def project_diagnostics(value: Any, *, mode: Optional[str] = None) -> Dict[str, Any]:
    selected_mode = diagnostics_mode(mode)
    if not isinstance(value, Mapping):
        return {}
    decision_version = str(value.get("decision_version") or "legacy")
    base = {
        "schema_version": int(value.get("schema_version") or 0),
        "decision_version": decision_version,
        "stage": _safe_label(value.get("stage"), pattern=_SAFE_STAGE) or "unknown",
        "code": _safe_label(str(value.get("code") or "").upper(), pattern=_SAFE_CODE)
        or "MEDIAFLOW_ADAPTER_FAILED",
        "retryable": bool(value.get("retryable")),
        "stale": decision_version != MEDIAFLOW_DECISION_VERSION,
    }
    if selected_mode == "off":
        return base
    base["safe_next_action"] = _safe_label(value.get("safe_next_action"), pattern=_SAFE_REASON) or safe_next_action(base["code"])
    for key in ("variant_id", "delivery_decision", "occurred_at"):
        label = _safe_label(value.get(key))
        if label:
            base[key] = label
    reasons = _safe_reasons(value.get("reasons"))
    if reasons:
        base["reasons"] = reasons
    workload = _safe_mapping(value.get("workload"), _WORKLOAD_KEYS)
    if workload:
        base["workload"] = {
            key: workload[key]
            for key in ("workload_class", "resource_class", "profile_source")
            if key in workload
        }
    capacity = _safe_capacity(value.get("capacity"))
    if capacity:
        base["capacity"] = capacity
    if selected_mode == "detailed":
        for key, allowed in (("source", _SOURCE_KEYS), ("guardrails", _GUARDRAIL_KEYS)):
            projection = _safe_mapping(value.get(key), allowed)
            if projection:
                base[key] = projection
        if workload:
            base["workload"] = workload
    return base


def recent_diagnostics(events: Iterable[Mapping[str, Any]], *, limit: int, mode: Optional[str] = None) -> list[Dict[str, Any]]:
    selected_mode = diagnostics_mode(mode)
    bounded_limit = max(1, min(int(limit), 25))
    result: list[Dict[str, Any]] = []
    for event in events:
        if event.get("source") != "mediaflow":
            continue
        try:
            data = json.loads(event.get("data_json") or "{}")
        except (TypeError, ValueError):
            data = {}
        diagnostics = data.get("diagnostics") if isinstance(data, Mapping) else None
        if not isinstance(diagnostics, Mapping):
            code = data.get("error_code") if isinstance(data, Mapping) else None
            if not code:
                continue
            diagnostics = {
                "schema_version": 0,
                "decision_version": "legacy",
                "stage": "unknown",
                "code": code,
                "retryable": bool(data.get("retryable")),
                "variant_id": event.get("entity_id"),
                "occurred_at": event.get("occurred_at"),
            }
        projected = project_diagnostics(diagnostics, mode=selected_mode)
        if projected:
            projected["event_type"] = _safe_label(event.get("event_type"), pattern=_SAFE_STAGE) or "mediaflow_event"
            result.append(projected)
        if len(result) >= bounded_limit:
            break
    return result
