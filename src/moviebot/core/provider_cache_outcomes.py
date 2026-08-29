"""Shared structured AllDebrid cache-check outcome mapping.

The provider adapter may return only part of a requested batch.  Callers must
not turn an absent or failed result into evidence that a release is uncached.
This module keeps that decision identical for Search and passive pre-warming.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Set

import httpx

from moviebot.adapters.alldebrid_client import AllDebridClient


CACHE_OUTCOME_STATUSES = {
    "cached",
    "not_cached",
    "unknown",
    "provider_error",
    "unresolvable",
}


def _identities(value: Any) -> Set[str]:
    text = str(value or "").strip().lower()
    if not text:
        return set()
    identities = {text}
    match = re.search(r"btih:([^&\s]+)", text, re.IGNORECASE)
    if match:
        identities.add(match.group(1).lower())
    elif re.fullmatch(r"[a-z0-9]{32,64}", text, re.IGNORECASE):
        identities.add(text)
    return identities


def _canonical_identity(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    if not text:
        return None
    match = re.search(r"btih:([^&\s]+)", text, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    if re.fullmatch(r"(?:[a-z0-9]{32}|[a-z0-9]{40})", text, re.IGNORECASE):
        return text
    return None


def _error_code(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "AD_TIMEOUT"
    if isinstance(exc, httpx.HTTPStatusError):
        return "AD_HTTP_ERROR"
    if isinstance(exc, (TypeError, ValueError)):
        return "AD_MALFORMED_RESPONSE"
    return "AD_PROVIDER_ERROR"


def summarize_cache_outcomes(outcomes: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    candidate_count = len(outcomes)
    cached_count = sum(1 for row in outcomes if row.get("status") == "cached")
    uncached_count = sum(1 for row in outcomes if row.get("status") == "not_cached")
    provider_error_count = sum(
        1 for row in outcomes if row.get("status") == "provider_error"
    )
    unresolvable_count = sum(
        1 for row in outcomes if row.get("status") == "unresolvable"
    )
    checked_count = cached_count + uncached_count
    unknown_count = candidate_count - checked_count
    if candidate_count == checked_count:
        status = "complete"
    elif provider_error_count and checked_count == 0 and provider_error_count == candidate_count:
        status = "provider_error"
    else:
        status = "partial"
    return {
        "status": status,
        "candidate_count": candidate_count,
        "checked_count": checked_count,
        "cached_count": cached_count,
        "uncached_count": uncached_count,
        "unknown_count": unknown_count,
        "provider_error_count": provider_error_count,
        "unresolvable_count": unresolvable_count,
    }


async def check_cache_references(
    references: Sequence[Any],
    *,
    client: Optional[AllDebridClient] = None,
) -> Dict[str, Any]:
    """Return one sanitized structured outcome for every input reference."""
    outcomes: List[Dict[str, Any]] = [
        {"status": "unknown", "error_code": None} for _ in references
    ]
    groups: Dict[str, List[int]] = {}
    submitted: List[str] = []
    submitted_keys: List[str] = []

    for index, reference in enumerate(references):
        key = _canonical_identity(reference)
        if key is None:
            outcomes[index] = {
                "status": "unresolvable",
                "error_code": "AD_REFERENCE_UNRESOLVABLE",
            }
            continue
        if key not in groups:
            groups[key] = []
            submitted.append(str(reference))
            submitted_keys.append(key)
        groups[key].append(index)

    if not submitted:
        return {"outcomes": outcomes, "summary": summarize_cache_outcomes(outcomes)}

    provider = client or AllDebridClient()
    try:
        payload = await provider.instant_check(submitted)
    except Exception as exc:
        code = _error_code(exc)
        for indices in groups.values():
            for index in indices:
                outcomes[index] = {"status": "provider_error", "error_code": code}
        return {"outcomes": outcomes, "summary": summarize_cache_outcomes(outcomes)}

    if (
        not isinstance(payload, dict)
        or "magnets" not in payload
        or not isinstance(payload.get("magnets"), list)
    ):
        for indices in groups.values():
            for index in indices:
                outcomes[index] = {
                    "status": "provider_error",
                    "error_code": "AD_MALFORMED_RESPONSE",
                }
        return {"outcomes": outcomes, "summary": summarize_cache_outcomes(outcomes)}

    returned = [row for row in payload.get("magnets", []) if isinstance(row, dict)]
    returned_by_key: Dict[str, Dict[str, Any]] = {}
    for row in returned:
        row_identities = _identities(row.get("hash")) | _identities(row.get("magnet"))
        for key in submitted_keys:
            if key in row_identities:
                returned_by_key[key] = row

    failed_codes: Dict[int, str] = {}
    error_codes: List[str] = []
    for error in payload.get("errors", []) or []:
        if not isinstance(error, dict):
            continue
        code = str(error.get("code") or "AD_PROVIDER_ERROR")[:100]
        if not re.fullmatch(r"[A-Z0-9_]+", code):
            code = "AD_PROVIDER_ERROR"
        error_codes.append(code)
        for position in error.get("failed_positions", []) or []:
            try:
                failed_codes[int(position)] = code
            except (TypeError, ValueError):
                continue

    for position, key in enumerate(submitted_keys):
        row = returned_by_key.get(key)
        if row is not None:
            status = "cached" if bool(row.get("instant") or row.get("ready")) else "not_cached"
            result = {"status": status, "error_code": None}
        elif failed_codes.get(position) == "AD_PARTIAL_RESPONSE":
            result = {"status": "unknown", "error_code": "AD_PARTIAL_RESPONSE"}
        elif position in failed_codes or (error_codes and not returned):
            result = {
                "status": "provider_error",
                "error_code": (
                    failed_codes.get(position)
                    or (error_codes[0] if error_codes else "AD_PROVIDER_ERROR")
                ),
            }
        else:
            result = {"status": "unknown", "error_code": "AD_PARTIAL_RESPONSE"}
        for index in groups[key]:
            outcomes[index] = dict(result)

    return {"outcomes": outcomes, "summary": summarize_cache_outcomes(outcomes)}
