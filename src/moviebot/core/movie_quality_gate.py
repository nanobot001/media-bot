"""Shared, fail-closed movie release eligibility policy."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from moviebot.tools.tmdb_fact_provider import TMDbFactProvider


MOVIE_RELEASE_WINDOW_DAYS = 65
RELEASE_WINDOW_NOT_ELIGIBLE = "RELEASE_WINDOW_NOT_ELIGIBLE"
RELEASE_DATE_UNAVAILABLE = "RELEASE_DATE_UNAVAILABLE"
LOW_QUALITY_SOURCE = "LOW_QUALITY_SOURCE"
ELIGIBLE = "ELIGIBLE"
MOVIE_QUALITY_GATE_REJECTED = "MOVIE_QUALITY_GATE_REJECTED"

_LOW_QUALITY_SOURCE_RE = re.compile(
    r"(?<![a-z0-9])(?:cam|hdcam|camrip|hdts|telesync|telecine|ts|"
    r"screener|dvdscr|bdscr|workprint)(?![a-z0-9])",
    re.IGNORECASE,
)


def _parse_date(value: Any) -> Optional[dt.date]:
    if not isinstance(value, str):
        return None
    candidate = value.strip()[:10]
    if not candidate:
        return None
    try:
        return dt.date.fromisoformat(candidate)
    except ValueError:
        return None


def _provider_has_credentials(provider: Any) -> bool:
    """Avoid making unauthenticated TMDb requests while preserving fail-closed behavior."""
    if not hasattr(provider, "api_key") and not hasattr(provider, "bearer_token"):
        return True
    return bool(getattr(provider, "api_key", None) or getattr(provider, "bearer_token", None))


def resolve_movie_release_context(
    *,
    title: Optional[str] = None,
    year: Optional[int] = None,
    imdb_id: Optional[str] = None,
    tmdb_id: Optional[int] = None,
    authoritative_release_date: Optional[str] = None,
    provider: Optional[TMDbFactProvider] = None,
) -> Dict[str, Any]:
    """Resolve the authoritative TMDb theatrical date without guessing from a year."""
    if authoritative_release_date:
        return {
            "release_date": authoritative_release_date,
            "tmdb_id": tmdb_id,
            "source": "tmdb",
        }

    provider = provider or TMDbFactProvider()
    if not _provider_has_credentials(provider):
        return {}

    resolved_tmdb_id = tmdb_id
    try:
        if not resolved_tmdb_id and imdb_id:
            resolved_tmdb_id = provider.get_movie_id_by_imdb_id(imdb_id)
        if not resolved_tmdb_id and title:
            resolved_tmdb_id = provider.get_movie_id_by_title_year(title, year)
        if not resolved_tmdb_id:
            return {}

        details = provider.get_movie_details(resolved_tmdb_id)
    except Exception:
        return {}
    if not isinstance(details, dict):
        return {}

    return {
        "release_date": details.get("us_theatrical_date") or details.get("release_date"),
        "tmdb_id": details.get("tmdb_id") or resolved_tmdb_id,
        "source": "tmdb",
    }


def evaluate_movie_eligibility(
    *,
    title: Optional[str] = None,
    year: Optional[int] = None,
    imdb_id: Optional[str] = None,
    tmdb_id: Optional[int] = None,
    authoritative_release_date: Optional[str] = None,
    provider: Optional[TMDbFactProvider] = None,
    today: Optional[dt.date] = None,
) -> Dict[str, Any]:
    """Return a safe structured movie decision; unknown dates are never eligible."""
    today = today or dt.date.today()
    cutoff_date = today - dt.timedelta(days=MOVIE_RELEASE_WINDOW_DAYS)
    context = resolve_movie_release_context(
        title=title,
        year=year,
        imdb_id=imdb_id,
        tmdb_id=tmdb_id,
        authoritative_release_date=authoritative_release_date,
        provider=provider,
    )
    raw_release_date = context.get("release_date")
    release_date = _parse_date(raw_release_date)
    base = {
        "eligible": False,
        "reason": RELEASE_DATE_UNAVAILABLE,
        "release_date": release_date.isoformat() if release_date else None,
        "age_days": None,
        "cutoff_date": cutoff_date.isoformat(),
        "tmdb_id": context.get("tmdb_id"),
        "source": context.get("source"),
        "actionable": False,
    }
    if release_date is None:
        return base

    age_days = (today - release_date).days
    base["age_days"] = age_days
    if release_date > cutoff_date:
        base["reason"] = RELEASE_WINDOW_NOT_ELIGIBLE
        return base

    base["eligible"] = True
    base["reason"] = ELIGIBLE
    base["actionable"] = True
    return base


def has_low_quality_source_marker(release_title: str) -> bool:
    return bool(_LOW_QUALITY_SOURCE_RE.search(release_title or ""))


def assess_movie_release(
    release: Dict[str, Any],
    eligibility: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply the hard title/date decision and then the release-title defense layer."""
    result = dict(eligibility)
    result["candidate_title"] = release.get("title") or ""
    result["actionable"] = False
    if not eligibility.get("eligible"):
        return result
    if has_low_quality_source_marker(result["candidate_title"]):
        result["eligible"] = False
        result["reason"] = LOW_QUALITY_SOURCE
        return result
    result["actionable"] = True
    return result


def filter_movie_releases(
    releases: Iterable[Dict[str, Any]],
    eligibility: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return actionable candidates plus sanitized rejected diagnostic evidence."""
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for release in releases:
        decision = assess_movie_release(release, eligibility)
        if decision["eligible"]:
            accepted_item = dict(release)
            accepted_item["quality_gate"] = decision
            accepted.append(accepted_item)
            continue
        rejected.append({
            "reference_id": release.get("reference_id"),
            "title": release.get("title"),
            "indexer": release.get("indexer"),
            "size_bytes": release.get("size_bytes"),
            "seeders": release.get("seeders"),
            "published_at": release.get("published_at"),
            "actionable": False,
            "quality_gate": decision,
        })
    return accepted, rejected


def quality_gate_error(decision: Dict[str, Any]) -> Dict[str, Any]:
    reason = decision.get("reason") or RELEASE_DATE_UNAVAILABLE
    messages = {
        RELEASE_WINDOW_NOT_ELIGIBLE: "Movie is inside the conservative 65-day theatrical release window.",
        RELEASE_DATE_UNAVAILABLE: "Authoritative TMDb movie release-date evidence is unavailable.",
        LOW_QUALITY_SOURCE: "The selected movie release contains a low-quality source marker.",
    }
    return {
        "code": MOVIE_QUALITY_GATE_REJECTED,
        "message": messages.get(reason, "Movie failed the quality gate."),
        "retryable": False,
        "severity": "info",
        "quality_gate": decision,
    }
