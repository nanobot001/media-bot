import datetime
from typing import Dict, Any, Optional, List
from moviebot.adapters.prowlarr_client import ProwlarrClient


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

        if limit is not None and limit > 0:
            results = results[:limit]

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



