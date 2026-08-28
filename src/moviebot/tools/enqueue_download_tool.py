import asyncio
import datetime
import json
import uuid
import re
from typing import Dict, Any, Optional, List
from moviebot.config import settings
from moviebot.db.repositories import SearchResultRepository, DownloadJobRepository, TVLibraryRepository
from moviebot.adapters.alldebrid_client import AllDebridClient
from moviebot.adapters.idm_adapter import IdmAdapter
from moviebot.core.file_selection import select_primary_video_file
from moviebot.core.tv_file_selection import parse_tv_torrent_files, filter_unowned_episodes
from moviebot.core.movie_quality_gate import (
    assess_movie_release,
    evaluate_movie_eligibility,
    quality_gate_error,
)
from moviebot.core.release_parser import extract_year_from_title


async def _jit_enrich_tv_show(title: str, domain: str = "tv") -> None:
    """Asynchronously fetches and upserts show-level metadata for first-time TV ingest."""
    try:
        from moviebot.core.dedupe import normalize_title
        from moviebot.tools.tmdb_fact_provider import TMDbFactProvider

        norm = normalize_title(title)
        existing = TVLibraryRepository.get_show_by_normalized_title_and_year(norm, domain=domain)
        if existing and existing.get("synopsis"):
            return  # Already rich show record

        provider = TMDbFactProvider()
        search_res = provider._get_json("search/tv", {"query": title})
        if not search_res or not search_res.get("results"):
            return

        tv_item = search_res["results"][0]
        tv_id = tv_item.get("id")
        show_title = tv_item.get("name") or title
        first_air_date = tv_item.get("first_air_date") or ""
        year = int(first_air_date[:4]) if len(first_air_date) >= 4 and first_air_date[:4].isdigit() else None
        overview = tv_item.get("overview") or ""
        poster_path = tv_item.get("poster_path")
        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
        backdrop_path = tv_item.get("backdrop_path")
        banner_url = f"https://image.tmdb.org/t/p/original{backdrop_path}" if backdrop_path else None

        # Detailed show info
        details = provider._get_json(f"tv/{tv_id}") if tv_id else {}
        genres = ", ".join([g["name"] for g in details.get("genres", [])]) if details and "genres" in details else ""
        networks = ", ".join([n["name"] for n in details.get("networks", [])]) if details and "networks" in details else ""
        total_seasons = details.get("number_of_seasons", 0) if details else 0
        total_episodes = details.get("number_of_episodes", 0) if details else 0
        tagline = details.get("tagline") if details else None

        show_id = existing["id"] if existing else f"tmdb-tv-{tv_id}"
        TVLibraryRepository.upsert_show(
            id=show_id,
            title=show_title,
            normalized_title=norm,
            year=year,
            tmdb_id=tv_id,
            genres=genres,
            networks=networks,
            tagline=tagline,
            synopsis=overview,
            total_seasons=total_seasons,
            total_episodes=total_episodes,
            poster_url=poster_url,
            banner_url=banner_url,
            domain=domain
        )
    except Exception:
        pass


async def enqueue_download_tool(
    reference_id: str,
    domain: str = "movies",
    dry_run: bool = False,
    selected_file_id: Optional[Any] = None,
    selected_file_ids: Optional[List[Any]] = None,
    skip_owned: bool = True,
    title: Optional[str] = None,
    year: Optional[int] = None,
    imdb_id: Optional[str] = None,
    tmdb_id: Optional[int] = None,
    movie_eligibility: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Downloads torrent/magnet from Prowlarr via AllDebrid and delegates to IDM.
    Supports Movies, TV, and Classic TV with 3-way destination folder routing
    and multi-file season pack episode extraction.
    """
    tool_name = "enqueue_download_tool"
    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    db_domain = "tv_classic" if domain in ("tv_classic", "classic_tv") else domain

    # 1. Determine destination output directory based on domain
    if db_domain == "tv":
        target_dir = settings.tv_output_dir
    elif db_domain == "tv_classic":
        target_dir = settings.tv_classic_output_dir
    else:
        target_dir = settings.output_dir

    # 2. Retrieve the cached search result
    search_record = SearchResultRepository.get_by_id(reference_id, domain=db_domain)
    if not search_record:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "SEARCH_RECORD_NOT_FOUND",
                "message": f"No cached search result found for reference ID: {reference_id}",
                "retryable": False,
                "severity": "error"
            }
        }

    try:
        raw_payload = json.loads(search_record["raw_json_payload"])
    except Exception:
        raw_payload = {}

    if db_domain == "movies":
        movie_title = title or search_record.get("query_string") or search_record.get("title")
        movie_year = year or extract_year_from_title(search_record.get("title") or "")
        movie_eligibility = movie_eligibility or await asyncio.to_thread(
            evaluate_movie_eligibility,
            title=movie_title,
            year=movie_year,
            imdb_id=imdb_id,
            tmdb_id=tmdb_id,
        )
        movie_release_decision = assess_movie_release(
            {"title": search_record.get("title") or ""},
            movie_eligibility,
        )
        if not movie_release_decision.get("eligible"):
            return {
                "ok": False,
                "tool": tool_name,
                "timestamp": timestamp,
                "error": quality_gate_error(movie_release_decision),
            }

    download_url = ""
    # 1. Prefer direct magnetUrl if present
    if raw_payload.get("magnetUrl") and raw_payload["magnetUrl"].startswith("magnet:"):
        download_url = raw_payload["magnetUrl"]
    # 2. If infoHash is present, construct the standard BitTorrent magnet URI
    elif raw_payload.get("infoHash"):
        ih = raw_payload["infoHash"].strip()
        title_dn = raw_payload.get("title") or search_record.get("title") or "Media"
        download_url = f"magnet:?xt=urn:btih:{ih}&dn={title_dn}"
    # 3. Fallback to downloadUrl if it starts with magnet:
    elif raw_payload.get("downloadUrl") and raw_payload["downloadUrl"].startswith("magnet:"):
        download_url = raw_payload["downloadUrl"]
    # 4. Fallback to raw downloadUrl or guid
    elif raw_payload.get("downloadUrl"):
        download_url = raw_payload["downloadUrl"]
    elif raw_payload.get("guid"):
        download_url = raw_payload["guid"]

    if not download_url:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "DOWNLOAD_URL_MISSING",
                "message": "No valid download URL or magnet infohash could be resolved from cached search record.",
                "retryable": False,
                "severity": "error"
            }
        }

    try:
        debrid = AllDebridClient()

        # =========================================================================
        # TV / CLASSIC TV MULTI-FILE EPISODE PIPELINE
        # =========================================================================
        if db_domain in ("tv", "tv_classic"):
            if dry_run:
                magnet_id = "dry_run_tv_magnet_id"
                title = search_record.get("title", "Show.S01")
                files_list = [
                    {"id": 1, "name": f"{title}.S01E01.1080p.mkv", "size": 1500000000, "link": "https://alldebrid.mock/link/1"},
                    {"id": 2, "name": f"{title}.S01E02.1080p.mkv", "size": 1500000000, "link": "https://alldebrid.mock/link/2"},
                    {"id": 3, "name": f"{title}.sample.mkv", "size": 50000000, "link": "https://alldebrid.mock/link/3"},
                    {"id": 4, "name": f"{title}.nfo", "size": 5000, "link": "https://alldebrid.mock/link/4"},
                ]
            else:
                upload_res = await debrid.upload_magnet(download_url)
                magnet_id = upload_res.get("id")
                status_res = await debrid.get_magnet_status(magnet_id)

                if status_res.get("statusCode") == 4:
                    files_list = await debrid.get_magnet_files(magnet_id)
                else:
                    files_list = []

                if not files_list:
                    job_id = str(uuid.uuid4())
                    DownloadJobRepository.create_job(
                        id=job_id,
                        alldebrid_magnet_id=str(magnet_id),
                        selected_file_name="Resolving metadata...",
                        target_dir=target_dir,
                        status="pending",
                        domain=db_domain
                    )
                    return {
                        "ok": True,
                        "tool": tool_name,
                        "timestamp": timestamp,
                        "data": {
                            "domain": domain,
                            "job_id": job_id,
                            "magnet_id": str(magnet_id),
                            "status": "pending",
                            "message": "Torrent metadata is being resolved by AllDebrid. Check status later."
                        }
                    }

            # Parse episode files and filter junk
            parsed_episodes = parse_tv_torrent_files(files_list)
            if not parsed_episodes:
                # If regex SxxExx didn't match, fallback to primary video file selector
                try:
                    _, chosen = select_primary_video_file(files_list)
                    parsed_episodes = [{
                        "id": f.get("id", 1),
                        "season": 1,
                        "episode": 1,
                        "name": f["name"],
                        "size": f["size"],
                        "link": f.get("link", ""),
                        "path": f.get("path", "")
                    } for f in chosen]
                except ValueError as ve:
                    return {
                        "ok": False,
                        "tool": tool_name,
                        "timestamp": timestamp,
                        "error": {
                            "code": "NO_VALID_EPISODES",
                            "message": f"No valid video episodes found in torrent: {str(ve)}",
                            "retryable": False,
                            "severity": "error"
                        }
                    }

            # Filter by user-selected file IDs if provided
            allowed_ids = set()
            if selected_file_ids:
                allowed_ids = {str(fid) for fid in selected_file_ids}
            elif selected_file_id is not None:
                allowed_ids = {str(selected_file_id)}

            if allowed_ids:
                parsed_episodes = [ep for ep in parsed_episodes if str(ep["id"]) in allowed_ids or ep["name"] in allowed_ids]

            # Library deduplication check (skip already owned episodes)
            skipped_owned = []
            if skip_owned:
                from moviebot.core.dedupe import normalize_title
                query_str = search_record.get("query_string") or search_record.get("title", "")
                norm = normalize_title(query_str)
                show_record = TVLibraryRepository.get_show_by_normalized_title_and_year(norm, domain=db_domain)
                if show_record:
                    owned_set = TVLibraryRepository.get_owned_episodes(show_record["id"], domain=db_domain)
                    unowned = filter_unowned_episodes(parsed_episodes, owned_set)
                    skipped_owned = [ep for ep in parsed_episodes if (ep["season"], ep["episode"]) in owned_set]
                    # If some unowned remain, proceed with unowned; if none remain, indicate already owned
                    if unowned:
                        parsed_episodes = unowned
                    elif skipped_owned:
                        return {
                            "ok": True,
                            "tool": tool_name,
                            "timestamp": timestamp,
                            "data": {
                                "domain": domain,
                                "status": "already_owned",
                                "target_dir": target_dir,
                                "message": f"All {len(skipped_owned)} episode(s) in this release are already present in your Plex library.",
                                "skipped_episodes": [{"season": e["season"], "episode": e["episode"], "name": e["name"]} for e in skipped_owned],
                            }
                        }

            if not parsed_episodes:
                return {
                    "ok": False,
                    "tool": tool_name,
                    "timestamp": timestamp,
                    "error": {
                        "code": "NO_EPISODES_TO_DOWNLOAD",
                        "message": "No episodes remaining to download after filtering.",
                        "retryable": False,
                        "severity": "error"
                    }
                }

            # Batch unlock stream links
            if dry_run:
                unlocked_urls = [f"https://alldebrid.mock/stream/{ep['id']}/{ep['name']}" for ep in parsed_episodes]
            else:
                links_to_unlock = [ep.get("link") or "" for ep in parsed_episodes]
                unlocked_urls = await debrid.unlock_links(links_to_unlock)

            # Send batch to IDM
            idm = IdmAdapter()
            downloads_payload = [
                {
                    "download_url": url or f"https://mock.stream/{ep['name']}",
                    "output_folder": target_dir,
                    "file_name": ep["name"]
                }
                for ep, url in zip(parsed_episodes, unlocked_urls)
            ]
            idm_results = await idm.send_batch_to_idm(downloads_payload, dry_run=dry_run)

            # Create download_jobs rows in SQLite for each enqueued episode
            jobs_created = []
            for ep in parsed_episodes:
                job_id = str(uuid.uuid4())
                DownloadJobRepository.create_job(
                    id=job_id,
                    alldebrid_magnet_id=str(magnet_id),
                    selected_file_name=ep["name"],
                    target_dir=target_dir,
                    status="dry_run" if dry_run else "downloading",
                    domain=db_domain
                )
                jobs_created.append({
                    "job_id": job_id,
                    "season": ep["season"],
                    "episode": ep["episode"],
                    "file_name": ep["name"],
                    "size_bytes": ep["size"],
                })

            # Trigger background Just-In-Time Show-Level Enrichment
            try:
                raw_query = search_record.get("query_string") or search_record.get("title", "")
                clean_show_name = re.sub(r'[sS]\d{1,2}.*$', '', raw_query).strip()
                if clean_show_name:
                    asyncio.create_task(_jit_enrich_tv_show(clean_show_name, domain=db_domain))
            except Exception:
                pass

            return {
                "ok": True,
                "tool": tool_name,
                "timestamp": timestamp,
                "data": {
                    "domain": domain,
                    "magnet_id": str(magnet_id),
                    "target_dir": target_dir,
                    "status": "dry_run" if dry_run else "downloading",
                    "enqueued_count": len(jobs_created),
                    "skipped_owned_count": len(skipped_owned),
                    "jobs": jobs_created,
                    "idm_routing": idm_results,
                }
            }

        # =========================================================================
        # MOVIES SINGLE-FILE PIPELINE (BACKWARD COMPATIBILITY)
        # =========================================================================
        if dry_run:
            magnet_id = "dry_run_magnet_id"
            files_list = [{"id": 1, "name": f"{search_record['title']}.mkv" if not search_record['title'].endswith(('.mkv', '.mp4')) else search_record['title'], "size": search_record["size_bytes"]}]
        else:
            upload_res = await debrid.upload_magnet(download_url)
            magnet_id = upload_res.get("id")
            status_res = await debrid.get_magnet_status(magnet_id)

            if status_res.get("statusCode") == 4:
                files_list = await debrid.get_magnet_files(magnet_id)
            else:
                files_list = []

            if not files_list:
                job_id = str(uuid.uuid4())
                DownloadJobRepository.create_job(
                    id=job_id,
                    alldebrid_magnet_id=str(magnet_id),
                    selected_file_name="Resolving metadata...",
                    target_dir=target_dir,
                    status="pending",
                    domain="movies"
                )
                return {
                    "ok": True,
                    "tool": tool_name,
                    "timestamp": timestamp,
                    "data": {
                        "domain": domain,
                        "job_id": job_id,
                        "magnet_id": str(magnet_id),
                        "status": "pending",
                        "message": "Torrent metadata is being resolved by AllDebrid. Check status later."
                    }
                }

        is_resolved, chosen_files = select_primary_video_file(files_list)
        selected_file = None
        if not is_resolved:
            if selected_file_id is not None:
                for f in chosen_files:
                    if str(f["id"]) == str(selected_file_id):
                        selected_file = f
                        break
                if not selected_file:
                    return {
                        "ok": False,
                        "tool": tool_name,
                        "timestamp": timestamp,
                        "error": {
                            "code": "INVALID_FILE_SELECTION",
                            "message": f"Provided selected_file_id '{selected_file_id}' did not match any files in the 10% variance group.",
                            "retryable": False,
                            "severity": "error"
                        }
                    }
            else:
                return {
                    "ok": True,
                    "tool": tool_name,
                    "timestamp": timestamp,
                    "data": {
                        "domain": domain,
                        "status": "requires_file_selection",
                        "magnet_id": str(magnet_id),
                        "reference_id": reference_id,
                        "candidates": chosen_files,
                        "message": "Multiple large video files detected within 10% size variance. User input required."
                    }
                }
        else:
            selected_file = chosen_files[0]

        if dry_run:
            unlocked_url = f"https://alldebrid.mock/dry_run_stream/{selected_file['name']}"
        else:
            target_debrid_link = None
            for f in files_list:
                name = f.get("name") or f.get("n")
                if name == selected_file["name"]:
                    target_debrid_link = f.get("link") or f.get("l")
                    break

            if not target_debrid_link:
                return {
                    "ok": False,
                    "tool": tool_name,
                    "timestamp": timestamp,
                    "error": {
                        "code": "DEBRID_LINK_RESOLUTION_FAILED",
                        "message": "Failed to map selected file to AllDebrid stream links array.",
                        "retryable": True,
                        "severity": "error"
                    }
                }

            unlocked_url = await debrid.unlock_link(target_debrid_link)

        idm = IdmAdapter()
        idm_res = await idm.send_to_idm(
            download_url=unlocked_url,
            output_folder=target_dir,
            file_name=selected_file["name"],
            dry_run=dry_run
        )

        job_id = str(uuid.uuid4())
        DownloadJobRepository.create_job(
            id=job_id,
            alldebrid_magnet_id=str(magnet_id),
            selected_file_name=selected_file["name"],
            target_dir=target_dir,
            status="dry_run" if dry_run else "downloading",
            domain="movies"
        )

        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "domain": domain,
                "job_id": job_id,
                "magnet_id": str(magnet_id),
                "selected_file": selected_file["name"],
                "target_dir": target_dir,
                "status": "dry_run" if dry_run else "downloading",
                "idm_routing": idm_res
            }
        }

    except Exception as e:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "ENQUEUE_DOWNLOAD_FAILED",
                "message": f"Failed to process and enqueue download: {str(e)}",
                "retryable": True,
                "severity": "critical"
            }
        }
