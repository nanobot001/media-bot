import asyncio
import datetime
from typing import Dict, Any, Optional, List
from moviebot.adapters.prowlarr_client import ProwlarrClient
from moviebot.core.movie_quality_gate import (
    evaluate_movie_eligibility,
    filter_movie_releases,
)
from moviebot.core.availability_service import AvailabilityService
from moviebot.core.release_parser import (
    extract_year_from_title,
    is_exact_media_identity,
    parse_release_details,
)
from moviebot.db.release_variant_repo import ReleaseVariantRepository


async def search_sources_tool(
    query: str,
    domain: str = "movies",
    year: Optional[int] = None,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    imdb_id: Optional[str] = None,
    tvdb_id: Optional[str] = None,
    categories: Optional[List[int]] = None,
    limit: Optional[int] = None,
    check_cache: bool = True,
    tmdb_id: Optional[int] = None,
    movie_eligibility: Optional[Dict[str, Any]] = None,
    catalog_title: Optional[str] = None,
    scope_type: Optional[str] = None,
    source_vector: str = "search",
    cycle_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Search Prowlarr indexers for movies or TV shows, filtering by category,
    obfuscating URLs with temporary tokens, and verifying instant cache.
    """
    tool_name = "search_sources_tool"
    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    try:
        client = ProwlarrClient()
        db_domain = "tv_classic" if domain in ("tv_classic", "classic_tv") else domain

        if db_domain == "movies":
            movie_eligibility = movie_eligibility or await asyncio.to_thread(
                evaluate_movie_eligibility,
                title=query,
                year=year,
                imdb_id=imdb_id,
                tmdb_id=tmdb_id,
            )
            if not movie_eligibility.get("eligible"):
                return {
                    "ok": True,
                    "tool": tool_name,
                    "timestamp": timestamp,
                    "data": {
                        "domain": domain,
                        "query": query,
                        "season": season,
                        "episode": episode,
                        "total_results": 0,
                        "library_status": _check_library_ownership(
                            query=query,
                            domain=domain,
                            season=season,
                            episode=episode,
                            imdb_id=imdb_id,
                            tvdb_id=tvdb_id,
                        ),
                        "results": [],
                        "rejected_results": [],
                        "rejected_count": 0,
                        "eligibility": movie_eligibility,
                    },
                }

        search_query = query
        if year and str(year) not in query:
            search_query = f"{query} {year}".strip()

        if db_domain in ("tv", "tv_classic"):
            results = await client.search_tv(
                query=search_query,
                season=season,
                episode=episode,
                imdb_id=imdb_id,
                tvdb_id=tvdb_id,
                categories=categories,
                domain=db_domain,
                check_cache=check_cache,
            )
        else:
            results = await client.search_movies(
                query=search_query,
                imdb_id=imdb_id,
                categories=categories,
                domain="movies",
                check_cache=check_cache,
            )

        rejected_results = []
        if db_domain == "movies" and movie_eligibility is not None:
            results, rejected_results = filter_movie_releases(results, movie_eligibility)

        if limit is not None and limit > 0:
            results = results[:limit]

        catalog_summary = _populate_release_catalog(
            results=results,
            domain=db_domain,
            title=catalog_title or query,
            year=_catalog_movie_year(year, movie_eligibility),
            tmdb_id=tmdb_id or (movie_eligibility or {}).get("tmdb_id"),
            imdb_id=imdb_id,
            tvdb_id=tvdb_id,
            season=season,
            episode=episode,
            scope_type=scope_type,
            source_vector=source_vector,
            cycle_id=cycle_id,
            check_cache=check_cache,
            checked_at=timestamp,
        )

        # Check library mirror ownership for deduplication awareness
        library_status = _check_library_ownership(
            query=query,
            domain=domain,
            season=season,
            episode=episode,
            imdb_id=imdb_id,
            tvdb_id=tvdb_id,
        )

        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "domain": domain,
                "query": query,
                "season": season,
                "episode": episode,
                "total_results": len(results),
                "library_status": library_status,
                "results": results,
                "rejected_results": rejected_results,
                "rejected_count": len(rejected_results),
                "eligibility": movie_eligibility,
                "catalog": catalog_summary,
            }
        }


    except Exception as e:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "SOURCE_SEARCH_FAILED",
                "message": f"Indexer search failed: {str(e)}",
                "retryable": True,
                "severity": "error"
            }
        }


def _catalog_movie_year(
    explicit_year: Optional[int],
    movie_eligibility: Optional[Dict[str, Any]],
) -> Optional[int]:
    if explicit_year is not None:
        return int(explicit_year)
    release_date = str((movie_eligibility or {}).get("release_date") or "")
    return int(release_date[:4]) if len(release_date) >= 4 and release_date[:4].isdigit() else None


def _candidate_scope(
    result: Dict[str, Any],
    *,
    domain: str,
    season: Optional[int],
    episode: Optional[int],
    scope_type: Optional[str],
) -> Dict[str, Any]:
    if domain == "movies":
        return {"scope_type": "movie", "season": 0, "episode": 0}
    parsed = parse_release_details(str(result.get("title") or ""))
    selected_scope = scope_type
    selected_season = int(season or 0)
    selected_episode = int(episode or 0)
    if not selected_scope:
        if selected_episode:
            selected_scope = "episode"
        elif parsed.get("is_complete_series"):
            selected_scope = "complete_series"
            selected_season = 0
        elif selected_season or parsed.get("season"):
            selected_scope = "season_pack"
            selected_season = selected_season or int(parsed.get("season") or 0)
        else:
            selected_scope = "series"
    return {
        "scope_type": selected_scope,
        "season": selected_season,
        "episode": selected_episode,
    }


def _scope_matches_release(scope: Dict[str, Any], release_title: str) -> bool:
    if scope["scope_type"] == "movie":
        return True
    parsed = parse_release_details(release_title)
    if scope["scope_type"] == "complete_series":
        return bool(parsed.get("is_complete_series"))
    if scope["scope_type"] == "episode":
        return (
            int(parsed.get("season") or 0) == int(scope["season"])
            and int(parsed.get("episode") or 0) == int(scope["episode"])
        )
    if scope["scope_type"] == "season_pack":
        return (
            not parsed.get("is_complete_series")
            and not parsed.get("episode")
            and int(parsed.get("season") or 0) == int(scope["season"])
        )
    return not parsed.get("is_tv")


def _populate_release_catalog(
    *,
    results: List[Dict[str, Any]],
    domain: str,
    title: str,
    year: Optional[int],
    tmdb_id: Optional[int],
    imdb_id: Optional[str],
    tvdb_id: Optional[str],
    season: Optional[int],
    episode: Optional[int],
    scope_type: Optional[str],
    source_vector: str,
    cycle_id: Optional[str],
    check_cache: bool,
    checked_at: str,
) -> Dict[str, Any]:
    if domain == "movies" and year is None:
        return {
            "status": "not_recorded",
            "error_code": "CATALOG_EXACT_YEAR_REQUIRED",
            "discovered_count": 0,
            "retained_count": 0,
            "checked_count": 0,
            "cached_count": 0,
            "uncached_count": 0,
            "unknown_count": 0,
            "provider_error_count": 0,
            "scopes": [],
        }

    exact: List[tuple[Dict[str, Any], Dict[str, Any]]] = []
    for result in results:
        release_title = str(result.get("title") or "")
        candidate_scope = _candidate_scope(
            result,
            domain=domain,
            season=season,
            episode=episode,
            scope_type=scope_type,
        )
        if not is_exact_media_identity(title, release_title):
            continue
        if domain == "movies" and extract_year_from_title(release_title) != int(year or 0):
            continue
        if not _scope_matches_release(candidate_scope, release_title):
            continue
        exact.append((result, candidate_scope))

    retained_ids = set()
    groups: Dict[tuple[str, int, int], List[Dict[str, Any]]] = {}
    for result, candidate_scope in exact:
        status = str(result.get("cache_status") or (
            "cached" if result.get("cached") else ("not_cached" if check_cache else "unknown")
        ))
        if status not in {"cached", "not_cached", "unknown", "provider_error", "unresolvable"}:
            status = "unknown"
        row = ReleaseVariantRepository.upsert_variant(
            domain=domain,
            title=title,
            year=year,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
            tvdb_id=tvdb_id,
            season=candidate_scope["season"],
            episode=candidate_scope["episode"],
            scope_type=candidate_scope["scope_type"],
            reference_id=result.get("reference_id"),
            release_title=str(result.get("title") or ""),
            size_bytes=result.get("size_bytes"),
            formatted_size=result.get("formatted_size"),
            seeders=result.get("seeders"),
            indexer=result.get("indexer"),
            source_vector=source_vector,
            ad_cache_status=status if check_cache else None,
            ad_checked_at=checked_at if check_cache else None,
            ad_error_code=result.get("cache_error_code") if check_cache else None,
            last_cache_checked_at=checked_at if check_cache else None,
            last_observed_cycle_id=cycle_id,
        )
        retained_ids.add(row.get("variant_id"))
        key = (
            candidate_scope["scope_type"],
            candidate_scope["season"],
            candidate_scope["episode"],
        )
        groups.setdefault(key, []).append(result)

    if not groups:
        intended = _candidate_scope(
            {},
            domain=domain,
            season=season,
            episode=episode,
            scope_type=scope_type,
        )
        groups[(intended["scope_type"], intended["season"], intended["episode"])] = []

    scope_summaries = []
    for (selected_scope, selected_season, selected_episode), candidates in groups.items():
        statuses = [
            str(row.get("cache_status") or (
                "cached" if row.get("cached") else ("not_cached" if check_cache else "unknown")
            ))
            for row in candidates
        ]
        cached_count = statuses.count("cached")
        uncached_count = statuses.count("not_cached")
        checked_count = cached_count + uncached_count
        unknown_count = len(candidates) - checked_count
        provider_error_count = statuses.count("provider_error")
        if check_cache:
            if checked_count == len(candidates):
                check_status = "complete"
            elif candidates and provider_error_count == len(candidates):
                check_status = "provider_error"
            else:
                check_status = "partial"
            error_code = next(
                (str(row.get("cache_error_code")) for row in candidates if row.get("cache_error_code")),
                None,
            )
            ReleaseVariantRepository.record_scope_check(
                domain=domain,
                title=title,
                year=year,
                tmdb_id=tmdb_id,
                season=selected_season,
                episode=selected_episode,
                scope_type=selected_scope,
                status=check_status,
                candidate_count=len(candidates),
                checked_count=checked_count,
                cached_count=cached_count,
                unknown_count=unknown_count,
                checked_at=checked_at,
                cycle_id=cycle_id,
                error_code=error_code,
            )
        state = AvailabilityService.inspect(
            domain=domain,
            title=title,
            year=year,
            tmdb_id=tmdb_id,
            season=selected_season,
            episode=selected_episode,
            scope_type=selected_scope,
        )
        scope_summaries.append({
            "scope_type": selected_scope,
            "season": selected_season,
            "episode": selected_episode,
            "availability_state": state["availability_state"],
            "candidate_count": len(candidates),
            "checked_count": checked_count,
            "cached_count": cached_count,
            "uncached_count": uncached_count,
            "unknown_count": unknown_count,
            "provider_error_count": provider_error_count,
        })

    return {
        "status": "recorded",
        "discovered_count": len(exact),
        "retained_count": len(retained_ids),
        "checked_count": sum(row["checked_count"] for row in scope_summaries),
        "cached_count": sum(row["cached_count"] for row in scope_summaries),
        "uncached_count": sum(row["uncached_count"] for row in scope_summaries),
        "unknown_count": sum(row["unknown_count"] for row in scope_summaries),
        "provider_error_count": sum(row["provider_error_count"] for row in scope_summaries),
        "scopes": scope_summaries,
    }


def _check_library_ownership(
    query: str,
    domain: str,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    imdb_id: Optional[str] = None,
    tvdb_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Inspects local SQLite mirror for existing ownership of the queried item."""
    import re
    from moviebot.db.repositories import TVLibraryRepository, LibraryItemRepository

    db_domain = "tv_classic" if domain in ("tv_classic", "classic_tv") else domain

    if db_domain in ("tv", "tv_classic"):
        norm = re.sub(r'[^a-z0-9\s]', '', query.lower()).strip()
        norm = re.sub(r'\s+', ' ', norm)

        show = None
        found_domain = db_domain
        # Try primary domain first, then fallback to other TV domain
        for d in [db_domain, "tv" if db_domain == "tv_classic" else "tv_classic"]:
            show = TVLibraryRepository.get_show_by_normalized_title_and_year(norm, domain=d)
            if show:
                found_domain = d
                break

        if not show:
            return {"in_library": False, "owned": False, "details": "Not found in local library"}

        episodes = TVLibraryRepository.get_episodes_for_show(show["id"], domain=found_domain)
        owned_set = {(e["season_number"], e["episode_number"]) for e in episodes}

        if season is not None and episode is not None:
            owned = (season, episode) in owned_set
            details = (
                f"{show['title']} S{season:02d}E{episode:02d} is IN LIBRARY ({found_domain})"
                if owned
                else f"{show['title']} S{season:02d}E{episode:02d} is MISSING from library ({found_domain})"
            )
            return {
                "in_library": True,
                "domain": found_domain,
                "show_title": show["title"],
                "season": season,
                "episode": episode,
                "owned": owned,
                "details": details,
            }
        elif season is not None:
            s_eps = [e for e in episodes if e["season_number"] == season]
            owned = len(s_eps) > 0
            details = (
                f"{show['title']} Season {season} has {len(s_eps)} episodes in library ({found_domain})"
                if owned
                else f"{show['title']} Season {season} is MISSING from library ({found_domain})"
            )
            return {
                "in_library": True,
                "domain": found_domain,
                "show_title": show["title"],
                "season": season,
                "owned": owned,
                "owned_episodes_count": len(s_eps),
                "details": details,
            }
        else:
            seasons_count = len(set(e["season_number"] for e in episodes))
            details = f"{show['title']} is IN LIBRARY ({len(episodes)} episodes across {seasons_count} seasons in {found_domain})"
            return {
                "in_library": True,
                "domain": found_domain,
                "show_title": show["title"],
                "owned": True,
                "total_episodes_count": len(episodes),
                "details": details,
            }
    else:
        try:
            from moviebot.core.dedupe import normalize_title
            from moviebot.db.repositories import LibraryItemRepository
            norm = normalize_title(query)
            matches = LibraryItemRepository.search_by_normalized_title(norm)
            if not matches:
                matches = LibraryItemRepository.search_fts(query)
            if matches:
                movie = matches[0]
                year_str = f" ({movie.get('year')})" if movie.get("year") else ""
                return {
                    "in_library": True,
                    "title": movie.get("title"),
                    "year": movie.get("year"),
                    "owned": True,
                    "details": f"{movie.get('title')}{year_str} is IN LIBRARY",
                }
        except Exception:
            pass
        return {"in_library": False, "owned": False, "details": "Not found in local library"}



