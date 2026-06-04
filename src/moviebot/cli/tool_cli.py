import argparse
import asyncio
import json
import sys
from pathlib import Path
from moviebot.config import settings
from moviebot.db.connection import init_db, get_db_connection
from moviebot.db.repositories import LibraryItemRepository
from moviebot.adapters.plex_client import PlexClient
from moviebot.core.dedupe import evaluate_deduplication, normalize_title
from moviebot.tools.search_sources_tool import search_sources_tool
from moviebot.tools.enqueue_download_tool import enqueue_download_tool
from moviebot.tools.query_watch_history_tool import query_watch_history_tool
from moviebot.tools.get_download_jobs_tool import get_download_jobs_tool
from moviebot.tools.resolve_pending_jobs_tool import resolve_pending_jobs_tool
from moviebot.tools.get_error_logs_tool import get_error_logs_tool
from moviebot.tools.check_movie_state_tool import check_movie_state_tool
from moviebot.tools.get_system_health_tool import get_system_health_tool
from moviebot.tools.get_tool_manifest_tool import get_tool_manifest_tool
from moviebot.tools.get_recent_events_tool import get_recent_events_tool
from moviebot.tools.tail_logs_tool import tail_logs_tool
from moviebot.tools.query_library_tool import query_library_tool
from moviebot.tools.recommend_movies_tool import recommend_movies_tool
from moviebot.tools.audit_collections_tool import audit_collections_tool
from moviebot.tools.sync_enrichment_tool import sync_enrichment_tool



def cmd_configtest(args) -> int:
    """Executes environment checkups, directory existences, and DB connection readiness."""
    print("=== MovieBot System Configuration Test ===")
    
    # 1. Output directory check
    out_dir = Path(settings.output_dir)
    print(f"Checking Output Path: {out_dir}")
    if not out_dir.exists():
        print(f"  [ERROR] Output directory '{out_dir}' does not exist on this host.")
        print(f"  Please ensure the F:\\ drive is mounted or adjust OUTPUT_DIR in .env.")
        return 1
    
    # Check writability
    try:
        test_file = out_dir / ".write_test"
        test_file.touch()
        test_file.unlink()
        print("  [OK] Output directory is writable.")
    except Exception as e:
        print(f"  [ERROR] Output directory '{out_dir}' is NOT writable: {str(e)}")
        return 1

    # 2. Database verification
    db_path = Path(settings.database_path)
    print(f"Checking Database: {db_path}")
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # Attempt to run migrations/init
        init_db()
        print("  [OK] SQLite database successfully initialized and schema applied.")
    except Exception as e:
        print(f"  [ERROR] Failed to initialize SQLite database: {str(e)}")
        return 1

    # 3. Environment parameters checks
    warnings = 0
    services = {
        "Discord Token": settings.discord_token,
        "Prowlarr ApiKey": settings.prowlarr_api_key,
        "AllDebrid ApiKey": settings.alldebrid_api_key,
        "Plex Token": settings.plex_token,
        "Tautulli ApiKey": settings.tautulli_api_key,
    }
    for service, val in services.items():
        if not val:
            print(f"  [WARNING] Key missing: {service}")
            warnings += 1
        else:
            print(f"  [OK] Value set for: {service}")
            
    print(f"Config validation finished with {warnings} warnings.")
    return 0


async def cmd_sync_library(args) -> int:
    """Queries Plex movies and populates/syncs the local SQLite mirror database."""
    print("Syncing media items from Plex to local database mirror...")
    try:
        client = PlexClient()
        movies = await client.fetch_all_movies()
        print(f"Retrieved {len(movies)} movies from Plex API.")
        
        for m in movies:
            norm = normalize_title(m["title"])
            LibraryItemRepository.upsert(
                id=m["id"],
                source=m["source"],
                rating_key=m["rating_key"],
                title=m["title"],
                normalized_title=norm,
                year=m["year"],
                imdb_id=m["imdb_id"],
                file_path=m["file_path"],
                size_bytes=m["size_bytes"],
                genres=m.get("genres"),
                directors=m.get("directors"),
                studios=m.get("studios"),
                writers=m.get("writers"),
                producers=m.get("producers"),
                cast=m.get("cast"),
                countries=m.get("countries"),
                content_rating=m.get("content_rating"),
                audience_rating=m.get("audience_rating"),
                tagline=m.get("tagline"),
                originally_available_at=m.get("originally_available_at"),
                labels=m.get("labels"),
                rating=m.get("rating"),
                runtime=m.get("runtime"),
                collections=m.get("collections"),
                resolution=m.get("resolution"),
                bitrate_kbps=m.get("bitrate_kbps"),
                watch_status=m.get("watch_status"),
                watch_count=m.get("watch_count", 0),
                last_watched_at=m.get("last_watched_at"),
                synopsis=m.get("synopsis"),
                synopsis_hash=m.get("synopsis_hash"),
                metadata_refreshed_at=m.get("metadata_refreshed_at")
            )
            
        # Clean up database records of Plex movies that were not in this sync
        synced_ids = [m["id"] for m in movies]
        with get_db_connection() as conn:
            if synced_ids:
                placeholders = ",".join("?" for _ in synced_ids)
                conn.execute(
                    f"DELETE FROM library_items WHERE source = 'plex' AND id NOT IN ({placeholders})",
                    synced_ids
                )
            else:
                conn.execute("DELETE FROM library_items WHERE source = 'plex'")
            conn.commit()
            
        print("Successfully synchronized local database mirror.")
        return 0
    except Exception as e:
        print(f"Sync failed: {str(e)}")
        return 1


async def cmd_sync_intelligence(args) -> int:
    """Fetches detailed Plex metadata and performs dry-run or real DB enrichment."""
    dry_run = not args.no_dry_run
    mode_str = "[DRY-RUN]" if dry_run else "[REAL MODE]"
    print(f"=== Running sync-intelligence in {mode_str} ===")
    
    from moviebot.db.connection import get_db_connection
    import datetime
    
    try:
        with get_db_connection() as conn:
            cursor = conn.execute("SELECT * FROM library_items WHERE source = 'plex'")
            items = [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"Failed to fetch library items: {str(e)}")
        return 1
        
    if not items:
        print("No Plex library items found in local database. Run sync-library first.")
        return 0
        
    print(f"Found {len(items)} library items to enrich.")
    client = PlexClient()
    
    success_count = 0
    fail_count = 0
    
    for item in items:
        rating_key = item.get("rating_key")
        if not rating_key:
            print(f"Skipping {item['title']} (no rating key)")
            continue
            
        print(f"Fetching details for rating_key {rating_key}: {item['title']} ({item['year'] or 'Unknown Year'})...")
        try:
            details = await client.fetch_movie_details(rating_key)
            if not details:
                print(f"  [ERROR] No metadata details returned from Plex for rating_key {rating_key}")
                fail_count += 1
                continue
                
            # Print preview of parsed details
            print(f"  Title: {details['title']} ({details['year']})")
            print(f"  Genres: {details.get('genres')}")
            print(f"  Directors: {details.get('directors')}")
            print(f"  Studios: {details.get('studios')}")
            print(f"  Cast: {details.get('cast')}")
            print(f"  Content rating: {details.get('content_rating')}")
            print(f"  Collections: {details.get('collections')}")
            print(f"  Resolution: {details.get('resolution')}")
            print(f"  Bitrate: {details.get('bitrate_kbps')} kbps")
            print(f"  Rating: {details.get('rating')}")
            print(f"  Runtime: {details.get('runtime')} mins")
            print(f"  Watch count: {details.get('watch_count')}")
            print(f"  Synopsis (first 100 chars): {details.get('synopsis')[:100] if details.get('synopsis') else 'None'}")
            print(f"  Synopsis hash: {details.get('synopsis_hash')}")
            
            # Determine if embedding update is needed
            from moviebot.core.embeddings import get_embedding_result, encode_vector, get_configured_model
            
            existing_vector = item.get("synopsis_vector")
            existing_hash = item.get("synopsis_hash")
            existing_model = item.get("synopsis_vector_model")
            existing_dim = item.get("synopsis_vector_dim")
            existing_updated = item.get("synopsis_vector_updated_at")
            
            # Build composite document using any existing tones/themes
            from moviebot.core.embeddings import (
                build_composite_document,
                get_composite_document_hash,
                get_embedding_result,
                encode_vector,
                get_configured_model
            )
            import json
            def load_tags(val) -> list:
                if not val:
                    return []
                if isinstance(val, list):
                    return val
                try:
                    parsed = json.loads(val)
                    if isinstance(parsed, list):
                        return parsed
                except Exception:
                    pass
                return [val]

            genres = details.get("genres") or load_tags(item.get("genres"))
            tones = load_tags(item.get("tone_tags"))
            themes = load_tags(item.get("theme_tags"))
            new_synopsis = details.get("synopsis") or item.get("synopsis") or ""
            
            composite_doc = build_composite_document(
                title=details.get("title") or item.get("title", ""),
                year=details.get("year") or item.get("year"),
                genres=genres,
                tones=tones,
                themes=themes,
                synopsis=new_synopsis
            )
            
            new_hash = get_composite_document_hash(composite_doc)
            configured_model = get_configured_model()
            
            needs_embedding = False
            reason = ""
            if not existing_vector:
                needs_embedding = True
                reason = "No existing vector found"
            elif existing_hash != new_hash:
                needs_embedding = True
                reason = f"Composite document hash changed ({existing_hash} vs {new_hash})"
            elif existing_model != configured_model:
                needs_embedding = True
                reason = f"Embedding model changed ({existing_model} vs {configured_model})"
            elif existing_dim != 768:
                needs_embedding = True
                reason = f"Vector dimension mismatch ({existing_dim} vs 768)"
                
            synopsis_vector = existing_vector
            synopsis_vector_model = existing_model
            synopsis_vector_dim = existing_dim
            synopsis_vector_updated_at = existing_updated
            
            if needs_embedding and (new_synopsis or genres or details.get("title")):
                print(f"  Enriching with new composite embedding ({reason})...")
                if not dry_run:
                    try:
                        embedding_result = await get_embedding_result(composite_doc)
                        synopsis_vector = encode_vector(embedding_result.vector)
                        synopsis_vector_model = embedding_result.model
                        synopsis_vector_dim = embedding_result.dim
                        synopsis_vector_updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    except Exception as embed_err:
                        print(f"  [ERROR] Failed to fetch embedding: {str(embed_err)}")
                        needs_embedding = False
                else:
                    print(f"  [DRY-RUN] Would fetch embedding for composite document using model: {configured_model}")
            elif not new_synopsis and not genres:
                print("  Skipping embedding (no synopsis or metadata text).")
            else:
                print("  Reusing cached embedding vector.")
            
            if not dry_run:
                # Save details
                now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                LibraryItemRepository.upsert(
                    id=details["id"],
                    source=details["source"],
                    rating_key=details["rating_key"],
                    title=details["title"],
                    normalized_title=normalize_title(details["title"]),
                    year=details["year"],
                    imdb_id=details["imdb_id"],
                    file_path=details["file_path"],
                    size_bytes=details["size_bytes"],
                    genres=details.get("genres"),
                    directors=details.get("directors"),
                    studios=details.get("studios"),
                    writers=details.get("writers"),
                    producers=details.get("producers"),
                    cast=details.get("cast"),
                    countries=details.get("countries"),
                    content_rating=details.get("content_rating"),
                    audience_rating=details.get("audience_rating"),
                    tagline=details.get("tagline"),
                    originally_available_at=details.get("originally_available_at"),
                    labels=details.get("labels"),
                    rating=details.get("rating"),
                    runtime=details.get("runtime"),
                    collections=details.get("collections"),
                    resolution=details.get("resolution"),
                    bitrate_kbps=details.get("bitrate_kbps"),
                    watch_status=details.get("watch_status"),
                    watch_count=details.get("watch_count", 0),
                    last_watched_at=details.get("last_watched_at"),
                    synopsis=details.get("synopsis"),
                    synopsis_hash=new_hash,
                    metadata_refreshed_at=now_iso,
                    synopsis_vector=synopsis_vector,
                    synopsis_vector_model=synopsis_vector_model,
                    synopsis_vector_dim=synopsis_vector_dim,
                    synopsis_vector_updated_at=synopsis_vector_updated_at
                )
                print(f"  [OK] Saved to database.")
            else:
                print(f"  [DRY-RUN] Would save details to database.")
                
            success_count += 1
        except Exception as e:
            print(f"  [ERROR] Failed to fetch or save details: {str(e)}")
            fail_count += 1
            
    print(f"Finished. Success: {success_count}, Failed: {fail_count}")
    return 0


def cmd_dedupe(args) -> int:
    """Manually test the deduplication classification matrix against SQLite database."""
    print(f"Running Deduplication Check:")
    print(f"  Input Title: {args.title}")
    print(f"  Input Year:  {args.year}")
    print(f"  Input IMDb:  {args.imdb}")
    print(f"  Incoming Resolution: {args.incoming_resolution}")
    print(f"  Incoming Size:       {args.incoming_size_bytes}")
    print(f"  Incoming Bitrate:    {args.incoming_bitrate_kbps}")
    
    tier, action, details, item = evaluate_deduplication(
        title=args.title,
        year=args.year,
        imdb_id=args.imdb,
        incoming_resolution=args.incoming_resolution,
        incoming_size_bytes=args.incoming_size_bytes,
        incoming_bitrate_kbps=args.incoming_bitrate_kbps
    )
    
    print("\nResult:")
    print(f"  Match Rating: {tier}")
    print(f"  Action:       {action}")
    print(f"  Details:      {details}")
    if item:
        print(f"  Matched Item: {item['title']} ({item['year']}) [{item['source']}]")
    return 0


async def cmd_search(args) -> int:
    """Run search sources query via Prowlarr API."""
    print(f"Searching indexers for: '{args.query}'")
    res = await search_sources_tool(query=args.query, imdb_id=args.imdb)
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


async def cmd_download(args) -> int:
    """Downloads a torrent file via debrid by reference id."""
    print(f"Enqueuing download for reference ID: {args.id} (dryrun={args.dry_run})")
    res = await enqueue_download_tool(
        reference_id=args.id,
        dry_run=args.dry_run,
        selected_file_id=args.file_id
    )
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


async def cmd_history(args) -> int:
    """Queries Tautulli watch logs for active analytics and log histories."""
    print(f"Querying Tautulli watch history (user={args.user}, search={args.query}, limit={args.limit}):")
    res = await query_watch_history_tool(
        user=args.user,
        title=args.query,
        limit=args.limit
    )
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


async def cmd_jobs(args) -> int:
    """List active or recent download jobs."""
    active_only = not args.all
    print(f"Retrieving download jobs (active_only={active_only}, limit={args.limit})...")
    res = await get_download_jobs_tool(active_only=active_only, limit=args.limit)
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


async def cmd_resolve_pending(args) -> int:
    """Manually resolve pending jobs."""
    print(f"Triggering pending jobs resolution sweep (dry_run={args.dry_run})...")
    res = await resolve_pending_jobs_tool(dry_run=args.dry_run)
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


async def cmd_errors(args) -> int:
    """List recent diagnostic error logs."""
    print(f"Retrieving diagnostic error logs (limit={args.limit})...")
    res = await get_error_logs_tool(limit=args.limit)
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


async def cmd_check_state(args) -> int:
    """Search Plex mirror, AllDebrid, IDM, folders, and logs for a movie."""
    print(f"Checking movie status for '{args.title}' (year={args.year})...")
    res = await check_movie_state_tool(title=args.title, year=args.year)
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


async def cmd_health(args) -> int:
    """Query PM2 processes, disk metrics, and stack connections."""
    print("Retrieving system health and process diagnostics...")
    res = await get_system_health_tool()
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


async def cmd_manifest(args) -> int:
    """View tool-manifest.yaml structure."""
    print("Loading developer tool manifest...")
    res = await get_tool_manifest_tool()
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


async def cmd_events(args) -> int:
    """Retrieve recent SQLite event log entries."""
    print(f"Retrieving recent system event logs (limit={args.limit})...")
    res = await get_recent_events_tool(limit=args.limit)
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


async def cmd_logs(args) -> int:
    """Tail named logs ('watcher', 'bot-out', 'bot-err')."""
    print(f"Tailing logs for source '{args.source}' (lines={args.lines})...")
    res = await tail_logs_tool(source=args.source, lines=args.lines)
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


async def cmd_query_library(args) -> int:
    """Search the local SQLite state mirror for movies using exact filters, FTS5, and/or semantic queries."""
    res = await query_library_tool(
        query=args.query,
        semantic_query=args.semantic_query,
        genre=args.genre,
        director=args.director,
        resolution=args.resolution,
        watch_status=args.watch_status,
        max_runtime=args.max_runtime,
        min_rating=args.min_rating,
        setting_location=args.setting_location,
        premise_tag=args.premise_tag,
        character_tag=args.character_tag,
        theme_tag=args.theme_tag,
        tone_tag=args.tone_tag,
        craft_tag=args.craft_tag,
        studio=args.studio,
        actor=args.actor,
        content_rating=args.content_rating,
        award_tag=args.award_tag,
        source_material_tag=args.source_material_tag,
        popularity_tag=args.popularity_tag,
        cultural_impact_tag=args.cultural_impact_tag,
        exclude_content_warnings=args.exclude_content_warning,
        exclude_warning_level=args.exclude_warning_level,
        include_unknown_content_warnings=args.include_unknown_content_warnings,
        limit=args.limit
    )
    if args.json:
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 1

    if not res["ok"]:
        print(f"Error querying library: {res.get('error', {}).get('message', 'Unknown error')}")
        return 1

    movies = res.get("data", {}).get("movies", [])
    if not movies:
        print("No matching movies found in library.")
        return 0

    print(f"Found {len(movies)} matching movies:")
    print("-" * 80)
    for m in movies:
        title_part = f"{m.get('title')} ({m.get('year')})"
        res_part = f"Resolution: {m.get('resolution') or 'Unknown'}"
        rating_part = f"Rating: {m.get('rating') or 'N/A'}"
        watch_part = f"Watch Status: {m.get('watch_status') or 'unwatched'}"
        
        sim_part = ""
        if "similarity_score" in m:
            sim_part = f" - {m['similarity_score'] * 100:.1f}% Match"
            
        print(f"{title_part}{sim_part} | {res_part} | {rating_part} | {watch_part}")
    print("-" * 80)
    return 0


async def cmd_sync_enrichment(args) -> int:
    """Generate structured enrichment metadata for library items, dry-run by default."""
    dry_run = not args.no_dry_run
    mode_str = "[DRY-RUN]" if dry_run else "[REAL MODE]"
    if not args.json:
        print(f"=== Running sync-enrichment in {mode_str} ===")
    res = await sync_enrichment_tool(
        dry_run=dry_run,
        limit=args.limit,
        provider=args.provider,
        offset=args.offset,
        only_missing_hard_facts=args.only_missing_hard_facts,
        only_missing_enrichment=args.only_missing_enrichment,
        only_missing_brands=args.only_missing_brands,
    )
    if args.json:
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 1
    if not res["ok"]:
        print(f"Error syncing enrichment: {res.get('error', {}).get('message', 'Unknown error')}")
        return 1

    data = res.get("data", {})
    audit = data.get("audit", {})
    if audit:
        print("Plex Coverage Audit:")
        print(f"  Total items: {audit.get('total_items')}")
        print(f"  Avg Core Coverage: {audit.get('avg_core_coverage', 0.0):.1%}")
        fields_str = ", ".join(f"{k}: {v}" for k, v in audit.get("fields", {}).items())
        print(f"  Field coverage: {fields_str}")
        print("-" * 80)

    items = data.get("items", [])
    if not items:
        print("No Plex library items processed.")
        return 0
    for item in items:
        print(f"Enriching {item.get('title')} ({item.get('year') or 'Unknown Year'})...")
        print(f"  Setting locations: {', '.join(item.get('setting_locations', [])) or 'None'}")
        print(f"  Premise tags: {', '.join(item.get('premise_tags', [])) or 'None'}")
        print(f"  Theme tags: {', '.join(item.get('theme_tags', [])) or 'None'}")
        print(f"  Tone tags: {', '.join(item.get('tone_tags', [])) or 'None'}")
        print(f"  Content warning tags: {', '.join(item.get('content_warning_tags', [])) or 'None'}")
        print(f"  Award tags: {', '.join(item.get('award_tags', [])) or 'None'}")
        print(f"  Source material tags: {', '.join(item.get('source_material_tags', [])) or 'None'}")
        print(f"  Popularity tags: {', '.join(item.get('popularity_tags', [])) or 'None'}")
        print(f"  Cultural impact tags: {', '.join(item.get('cultural_impact_tags', [])) or 'None'}")
        print(f"  Box office tier: {item.get('box_office_tier') or 'None'}")
        print(f"  Provider used: {item.get('provider_used')} (requested: {item.get('provider_requested')})")
        print("  [DRY-RUN] Would save structured enrichment metadata." if dry_run else "  [OK] Saved structured enrichment metadata.")
        print("-" * 40)

    print(f"Finished. Processed: {data.get('processed', 0)}, Dry run: {dry_run}")
    return 0


async def cmd_recommend(args) -> int:
    """Generate recommendations based on user taste vector profile."""
    res = await recommend_movies_tool(user=args.user, limit=args.limit)
    if args.json:
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 1

    if not res["ok"]:
        print(f"Error generating recommendations: {res.get('error', {}).get('message', 'Unknown error')}")
        return 1

    recs = res.get("data", {}).get("recommendations", [])
    if not recs:
        print("No recommendations available.")
        return 0

    user_label = args.user or "All Users"
    print(f"Taste Recommendations for '{user_label}':")
    print("-" * 80)
    for idx, r in enumerate(recs, 1):
        title_part = f"{idx}. {r.get('title')} ({r.get('year')})"
        score_part = f"Score: {r.get('score', 0.0):.2f}"
        breakdown_part = f"(Sim: {r.get('cosine_similarity', 0.0):.2f}, Genre: {r.get('genre_score', 0.0):.2f}, Dir: {r.get('director_score', 0.0):.2f})"
        print(f"{title_part:<40} | {score_part} {breakdown_part}")
    print("-" * 80)
    return 0


async def cmd_audit_collections(args) -> int:
    """Audit local collections to detect sequel gaps and missing titles."""
    res = await audit_collections_tool()
    if args.json:
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 1

    if not res["ok"]:
        print(f"Error auditing collections: {res.get('error', {}).get('message', 'Unknown error')}")
        return 1

    reports = res.get("data", {}).get("reports", [])
    if not reports:
        print("All collections are fully complete! No gaps found.")
        return 0

    print("Collection Audit Gaps Found:")
    print("=" * 80)
    for rep in reports:
        col = rep.get("collection")
        conf = rep.get("confidence", 1.0)
        missing = rep.get("missing", [])
        owned = rep.get("owned", [])
        
        print(f"Collection: {col} (Confidence: {conf})")
        print(f"  Owned ({len(owned)} items):")
        for o in sorted(owned, key=lambda x: x.get("index") or 0):
            idx_str = f"Part {o['index']}" if o.get('index') is not None else "Unindexed"
            print(f"    - {o.get('title')} ({o.get('year')}) [{idx_str}]")
        print(f"  Missing Gaps ({len(missing)} items):")
        for m in sorted(missing, key=lambda x: x.get("index") or 0):
            idx_str = f"Part {m['index']}" if m.get('index') is not None else "Unindexed"
            year_str = f" ({m['year']})" if m.get('year') is not None else ""
            print(f"    - {m.get('title')}{year_str} [{idx_str}]")
        print("-" * 80)
    return 0


def main():

    parser = argparse.ArgumentParser(description="MovieBot Developer Command Line Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # configtest
    subparsers.add_parser("configtest", help="Verify system configs and directory mounts")

    # sync-library
    subparsers.add_parser("sync-library", help="Sync Plex items to SQLite local database")

    # sync-intelligence
    sync_intel_parser = subparsers.add_parser("sync-intelligence", help="Fetch detailed metadata for cached Plex library items")
    sync_intel_parser.add_argument("--no-dry-run", action="store_true", help="Execute real database writes (disables default dry-run)")

    # sync-enrichment
    sync_enrich_parser = subparsers.add_parser("sync-enrichment", help="Generate structured enrichment metadata for cached Plex library items")
    sync_enrich_parser.add_argument("--no-dry-run", action="store_true", help="Execute real database writes (disables default dry-run)")
    sync_enrich_parser.add_argument("--limit", type=int, default=50, help="Max items to process (default: 50)")
    sync_enrich_parser.add_argument("--offset", type=int, default=0, help="Skip this many matching items before processing (default: 0)")
    sync_enrich_parser.add_argument("--only-missing-hard-facts", action="store_true", help="Process only rows with at least one empty hard-fact field")
    sync_enrich_parser.add_argument("--only-missing-enrichment", action="store_true", help="Process only rows with no enrichment or fallback enrichment")
    sync_enrich_parser.add_argument("--only-missing-brands", action="store_true", help="Process only rows missing TMDb brand/franchise metadata")
    sync_enrich_parser.add_argument("--provider", choices=["rules", "gemini"], default="rules", help="Metadata provider (default: rules)")
    sync_enrich_parser.add_argument("--json", action="store_true", help="Output raw JSON envelope")

    # dedupe
    dedupe_parser = subparsers.add_parser("dedupe", help="Test title normalization & deduplication")
    dedupe_parser.add_argument("--title", required=True, help="Movie title string")
    dedupe_parser.add_argument("--year", type=int, required=True, help="Movie release year")
    dedupe_parser.add_argument("--imdb", help="Optional IMDb identifier")
    dedupe_parser.add_argument("--incoming-resolution", help="Optional incoming resolution (e.g. 2160p)")
    dedupe_parser.add_argument("--incoming-size-bytes", type=int, help="Optional incoming size in bytes")
    dedupe_parser.add_argument("--incoming-bitrate-kbps", type=int, help="Optional incoming bitrate in kbps")

    # search
    search_parser = subparsers.add_parser("search", help="Search Prowlarr indexers")
    search_parser.add_argument("--query", required=True, help="Search keywords query")
    search_parser.add_argument("--imdb", help="Optional IMDb identifier")

    # download
    download_parser = subparsers.add_parser("download", help="Download reference to debrid + IDM")
    download_parser.add_argument("--id", required=True, help="Obfuscated reference hash key from search results")
    download_parser.add_argument("--dry-run", action="store_true", help="Perform dry-run flow validation")
    download_parser.add_argument("--file-id", help="Optional file ID to bypass variance prompts")

    # history
    history_parser = subparsers.add_parser("history", help="Query Tautulli movie watch history log records")
    history_parser.add_argument("--user", help="Filter by viewer username")
    history_parser.add_argument("--query", help="Filter by movie title search term")
    history_parser.add_argument("--limit", type=int, default=10, help="Max entries to return (default: 10)")

    # jobs
    jobs_parser = subparsers.add_parser("jobs", help="List active or recent download jobs")
    jobs_parser.add_argument("--all", action="store_true", help="List historical and active jobs (default: active only)")
    jobs_parser.add_argument("--limit", type=int, default=50, help="Max entries to return when showing all (default: 50)")

    # resolve-pending
    resolve_parser = subparsers.add_parser("resolve-pending", help="Trigger a sweep to resolve pending torrents")
    resolve_parser.add_argument("--dry-run", action="store_true", help="Perform dry-run flow validation")

    # errors
    errors_parser = subparsers.add_parser("errors", help="List recent diagnostic error logs")
    errors_parser.add_argument("--limit", type=int, default=50, help="Max error log entries to return (default: 50)")

    # check-state
    check_parser = subparsers.add_parser("check-state", help="Check status of a movie in the pipeline")
    check_parser.add_argument("--title", required=True, help="Movie title string")
    check_parser.add_argument("--year", type=int, help="Optional movie release year")

    # health
    subparsers.add_parser("health", help="Retrieve system health and process diagnostics")

    # manifest
    subparsers.add_parser("manifest", help="View developer tool manifest")

    # events
    events_parser = subparsers.add_parser("events", help="Retrieve recent SQLite event log entries")
    events_parser.add_argument("--limit", type=int, default=50, help="Max events to retrieve (default: 50)")

    # logs
    logs_parser = subparsers.add_parser("logs", help="Tail logs for a named source")
    logs_parser.add_argument("--source", required=True, choices=["watcher", "bot-out", "bot-err"], help="Log file source name")
    logs_parser.add_argument("--lines", type=int, default=100, help="Number of lines to tail (default: 100)")

    # query-library
    query_lib_parser = subparsers.add_parser("query-library", help="Search the media intelligence library database")
    query_lib_parser.add_argument("--query", help="FTS5 query keyword")
    query_lib_parser.add_argument("--semantic-query", help="Semantic prompt query")
    query_lib_parser.add_argument("--genre", help="Genre filter")
    query_lib_parser.add_argument("--director", help="Director filter")
    query_lib_parser.add_argument("--resolution", help="Resolution filter")
    query_lib_parser.add_argument("--watch-status", help="Watch status filter")
    query_lib_parser.add_argument("--max-runtime", type=int, help="Max runtime in minutes")
    query_lib_parser.add_argument("--min-rating", type=float, help="Min rating score")
    query_lib_parser.add_argument("--setting-location", help="Structured setting location filter")
    query_lib_parser.add_argument("--premise-tag", help="Structured premise tag filter")
    query_lib_parser.add_argument("--character-tag", help="Structured character tag filter")
    query_lib_parser.add_argument("--theme-tag", help="Structured theme tag filter")
    query_lib_parser.add_argument("--tone-tag", help="Structured tone tag filter")
    query_lib_parser.add_argument("--craft-tag", help="Structured craft tag filter")
    query_lib_parser.add_argument("--studio", help="Studio/brand filter")
    query_lib_parser.add_argument("--actor", help="Actor/cast-name filter")
    query_lib_parser.add_argument("--content-rating", help="Content rating filter")
    query_lib_parser.add_argument("--award-tag", help="Award/acclaim hard-fact tag filter")
    query_lib_parser.add_argument("--source-material-tag", help="Source material hard-fact tag filter")
    query_lib_parser.add_argument("--popularity-tag", help="Popularity hard-fact tag filter")
    query_lib_parser.add_argument("--cultural-impact-tag", help="Cultural impact hard-fact tag filter")
    query_lib_parser.add_argument("--exclude-content-warning", action="append", help="Content warning to exclude; may be repeated")
    query_lib_parser.add_argument("--exclude-warning-level", default="mild", choices=["none", "mild", "moderate", "strong", "extreme"], help="Exclude warning at or above this level (default: mild)")
    query_lib_parser.add_argument("--include-unknown-content-warnings", action="store_true", help="Include rows where excluded warning levels are unknown")
    query_lib_parser.add_argument("--limit", type=int, default=50, help="Max entries to return (default: 50)")
    query_lib_parser.add_argument("--json", action="store_true", help="Output raw JSON envelope")

    # recommend
    recommend_parser = subparsers.add_parser("recommend", help="Generate taste profiling recommendations")
    recommend_parser.add_argument("--user", help="Viewer username to profile")
    recommend_parser.add_argument("--limit", type=int, default=10, help="Max entries to return (default: 10)")
    recommend_parser.add_argument("--json", action="store_true", help="Output raw JSON envelope")

    # audit-collections
    audit_col_parser = subparsers.add_parser("audit-collections", help="Audit local collections for gaps and sequels")
    audit_col_parser.add_argument("--json", action="store_true", help="Output raw JSON envelope")

    args = parser.parse_args()

    if args.command == "configtest":
        sys.exit(cmd_configtest(args))
    elif args.command == "sync-library":
        sys.exit(asyncio.run(cmd_sync_library(args)))
    elif args.command == "sync-intelligence":
        sys.exit(asyncio.run(cmd_sync_intelligence(args)))
    elif args.command == "sync-enrichment":
        sys.exit(asyncio.run(cmd_sync_enrichment(args)))
    elif args.command == "dedupe":
        sys.exit(cmd_dedupe(args))
    elif args.command == "search":
        sys.exit(asyncio.run(cmd_search(args)))
    elif args.command == "download":
        sys.exit(asyncio.run(cmd_download(args)))
    elif args.command == "history":
        sys.exit(asyncio.run(cmd_history(args)))
    elif args.command == "jobs":
        sys.exit(asyncio.run(cmd_jobs(args)))
    elif args.command == "resolve-pending":
        sys.exit(asyncio.run(cmd_resolve_pending(args)))
    elif args.command == "errors":
        sys.exit(asyncio.run(cmd_errors(args)))
    elif args.command == "check-state":
        sys.exit(asyncio.run(cmd_check_state(args)))
    elif args.command == "health":
        sys.exit(asyncio.run(cmd_health(args)))
    elif args.command == "manifest":
        sys.exit(asyncio.run(cmd_manifest(args)))
    elif args.command == "events":
        sys.exit(asyncio.run(cmd_events(args)))
    elif args.command == "logs":
        sys.exit(asyncio.run(cmd_logs(args)))
    elif args.command == "query-library":
        sys.exit(asyncio.run(cmd_query_library(args)))
    elif args.command == "recommend":
        sys.exit(asyncio.run(cmd_recommend(args)))
    elif args.command == "audit-collections":
        sys.exit(asyncio.run(cmd_audit_collections(args)))



if __name__ == "__main__":
    main()

