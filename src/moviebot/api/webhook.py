import json
import datetime
import asyncio
from typing import Any, Optional
from fastapi import FastAPI, Header, Query, HTTPException, Depends, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
import mimetypes
from moviebot.config import settings
from moviebot.adapters.plex_client import PlexClient
from moviebot.db.repositories import LibraryItemRepository, EventRepository, KeyValueRepository, DownloadJobRepository
from moviebot.core.dedupe import normalize_title
from moviebot.tools.check_movie_state_tool import check_movie_state_tool
from moviebot.tools.get_system_health_tool import get_system_health_tool
from moviebot.tools.get_tool_manifest_tool import get_tool_manifest_tool
from moviebot.tools.get_recent_events_tool import get_recent_events_tool
from moviebot.tools.tail_logs_tool import tail_logs_tool
from moviebot.tools.query_library_tool import query_library_tool
from moviebot.api.web_routes import router as web_router


app = FastAPI(docs_url=None, redoc_url=None)
app.include_router(web_router)


# CORS for local dev Vite server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_cockpit_cache_policy(request: Request, call_next):
    """Require browser revalidation for the cockpit shell and runtime script."""
    response = await call_next(request)
    if request.url.path in {"/", "/index.html", "/app.js"}:
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response

# Fix Windows MIME type registry issues for Javascript modules
mimetypes.init()
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('text/css', '.css')

# Optional: Mount built React static files if the directory exists
ui_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "web", "dist")
if os.path.isdir(ui_dir):
    app.mount("/ui", StaticFiles(directory=ui_dir, html=True), name="ui")


@app.on_event("startup")
async def on_startup_sync_plex():
    # The passive pre-warm scheduler is an independent runtime service. Plex
    # synchronization may fail without preventing durable cadence recovery.
    from moviebot.core.background_prewarmer import start_background_prewarm_scheduler
    start_background_prewarm_scheduler()

    async def _bg_sync():
        try:
            from moviebot.adapters.plex_client import PlexClient
            from moviebot.core.conversational_rag import normalize_title
            from moviebot.db.repositories import LibraryItemRepository
            from moviebot.tools.discover_media_tool import _owned_cache
            from moviebot.tools.sync_tv_library_tool import sync_tv_library_tool

            client = PlexClient()
            movies = await client.fetch_all_movies()
            batch = []
            for m in movies:
                batch.append({
                    "id": m["id"],
                    "source": m["source"],
                    "rating_key": m["rating_key"],
                    "title": m["title"],
                    "normalized_title": normalize_title(m["title"]),
                    "year": m["year"],
                    "imdb_id": m["imdb_id"],
                    "file_path": m["file_path"],
                    "size_bytes": m["size_bytes"],
                    "genres": m.get("genres"),
                    "directors": m.get("directors"),
                    "studios": m.get("studios"),
                    "writers": m.get("writers"),
                    "producers": m.get("producers"),
                    "cast": m.get("cast"),
                    "countries": m.get("countries"),
                    "content_rating": m.get("content_rating"),
                    "audience_rating": m.get("audience_rating"),
                    "tagline": m.get("tagline"),
                    "originally_available_at": m.get("originally_available_at"),
                    "labels": m.get("labels"),
                    "rating": m.get("rating"),
                    "runtime": m.get("runtime"),
                    "collections": m.get("collections"),
                    "resolution": m.get("resolution"),
                    "bitrate_kbps": m.get("bitrate_kbps"),
                    "watch_status": m.get("watch_status"),
                    "watch_count": m.get("watch_count", 0),
                    "last_watched_at": m.get("last_watched_at"),
                    "synopsis": m.get("synopsis"),
                    "synopsis_hash": m.get("synopsis_hash"),
                    "poster_url": m.get("poster_url")
                })
            LibraryItemRepository.upsert_batch(batch)
            await sync_tv_library_tool(domain="tv")
            await sync_tv_library_tool(domain="tv_classic")
            _owned_cache.clear()
            print(f"[Plex Sync] Startup background sync completed: {len(movies)} movies indexed.")

        except Exception as e:
            print(f"[Plex Sync] Startup background sync failed: {e}")
            try:
                EventRepository.insert(
                    event_type="plex_startup_sync_failed",
                    source="startup",
                    title="Plex startup synchronization failed",
                    summary="The pre-warm scheduler remains active independently.",
                    entity_type="runtime",
                    entity_id="plex_startup_sync",
                    status="failed",
                    severity="error",
                    data_json=json.dumps({"error_code": "PLEX_STARTUP_SYNC_FAILED"}),
                )
            except Exception:
                pass

    asyncio.create_task(_bg_sync())


@app.on_event("shutdown")
async def on_shutdown_prewarm_scheduler():
    from moviebot.core.background_prewarmer import stop_background_prewarm_scheduler
    from moviebot.core.mediaflow_adapter import mediaflow_playback_registry
    await stop_background_prewarm_scheduler()
    mediaflow_playback_registry.close_all(reason="shutdown")


async def status_event_generator():
    start_time = datetime.datetime.now(datetime.timezone.utc)
    while True:
        uptime = (datetime.datetime.now(datetime.timezone.utc) - start_time).total_seconds()
        
        try:
            from moviebot.adapters.media_watcher_client import MediaWatcherClient
            from moviebot.db.repositories import LibraryItemRepository
            from moviebot.core.dedupe import normalize_title

            raw_active = DownloadJobRepository.get_active_jobs(domain="all")
            active_jobs = []
            watcher = MediaWatcherClient()

            for j in raw_active:
                fname = j.get("selected_file_name") or ""
                w_status, _ = watcher.get_file_status(fname) if fname else ("unknown", None)
                if w_status == "processed":
                    try:
                        DownloadJobRepository.update_status(j["id"], "completed")
                    except Exception:
                        pass
                    continue

                clean_name = re.sub(r'\.(mkv|mp4|avi)$', '', fname, flags=re.IGNORECASE)
                year_match = re.search(r'\b(19\d{2}|20\d{2})\b', clean_name)
                title_part = clean_name[:year_match.start()].strip(' ._-') if year_match else clean_name
                norm_title = normalize_title(title_part)
                if norm_title:
                    matches = LibraryItemRepository.search_by_normalized_title(norm_title)
                    if matches:
                        try:
                            DownloadJobRepository.update_status(j["id"], "completed")
                        except Exception:
                            pass
                        continue

                # Auto-archive stale jobs > 4h old not currently tracked
                created_str = j.get("created_at") or ""
                if created_str:
                    try:
                        c_dt = datetime.datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                        if (datetime.datetime.now(datetime.timezone.utc) - c_dt).total_seconds() > 14400 and w_status != "tracking":
                            try:
                                DownloadJobRepository.update_status(j["id"], "completed")
                            except Exception:
                                pass
                            continue
                    except Exception:
                        pass

                active_jobs.append(j)
        except Exception:
            active_jobs = []

        active_count = len(active_jobs)
        is_running = active_count > 0
        
        job_previews = []
        for j in active_jobs[:5]:
            job_previews.append({
                "id": j.get("id"),
                "title": j.get("selected_file_name") or "Media Ingest",
                "status": j.get("status"),
                "domain": j.get("domain", "movies")
            })

        payload = {
            "type": "telemetry",
            "payload": {
                "state": "downloading" if is_running else "idle",
                "uptime": int(uptime),
                "active_downloads": active_count,
                "active_jobs": job_previews,
                "engine_status": "online",
                "media_watcher_status": "healthy"
            }
        }
        yield f"data: {json.dumps(payload)}\n\n"
        await asyncio.sleep(2)

@app.get("/api/stream")
async def sse_stream():
    return StreamingResponse(status_event_generator(), media_type="text/event-stream")

class TautulliPayload(BaseModel):
    event: str
    rating_key: Optional[str] = None
    imdb_id: Optional[str] = None
    title: Optional[str] = None
    grandparent_title: Optional[str] = None
    parent_title: Optional[str] = None
    media_type: Optional[str] = None
    user: Optional[str] = None
    player: Optional[str] = None
    session_key: Optional[str] = None
    season_num: Optional[Any] = None
    episode_num: Optional[Any] = None
    progress_percent: Optional[Any] = None
    duration: Optional[Any] = None
    stream_video_resolution: Optional[str] = None
    stream_container_decision: Optional[str] = None
    poster_url: Optional[str] = None
    thumb_url: Optional[str] = None
    art_url: Optional[str] = None
    occurred_at: Optional[str] = None


def verify_token(
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None)
):
    expected = settings.tautulli_webhook_secret
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Webhook secret is not configured on server."
        )

    # Check Header (Bearer token)
    if authorization and authorization.startswith("Bearer "):
        provided_token = authorization.split("Bearer ")[1].strip()
        if provided_token == expected:
            return

    # Check Query Parameter
    if token and token == expected:
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authorization token."
    )


@app.post("/webhook/tautulli", dependencies=[Depends(verify_token)])
async def tautulli_webhook(request: Request):
    try:
        raw_payload = await request.json()
    except Exception as exc:
        _record_rejected_tautulli_payload("invalid_json", {}, f"Invalid JSON payload: {exc}")
        return {"status": "ignored", "event_logged": "tautulli_payload_rejected"}

    payload = _coerce_tautulli_payload(raw_payload)
    if not payload:
        _record_rejected_tautulli_payload(
            "missing_event",
            raw_payload,
            "Tautulli payload did not include a usable event field.",
        )
        return {"status": "ignored", "event_logged": "tautulli_payload_rejected"}

    occurred = payload.occurred_at or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()
    data_json = payload.model_dump_json()
    
    summary = f"User {payload.user or 'unknown'} triggered {payload.event} on {payload.title or 'unknown movie'}"
    
    try:
        EventRepository.insert(
            event_type=payload.event,
            source="tautulli",
            title=payload.title,
            summary=summary,
            entity_type="movie",
            entity_id=payload.rating_key or payload.imdb_id,
            status="received",
            severity="info",
            occurred_at=occurred,
            data_json=data_json
        )
    except Exception as e:
        print(f"[Webhook Server Error] Failed to log event to DB: {str(e)}")

    from moviebot.core.playback_notifications import is_playback_event
    if is_playback_event(payload.event):
        asyncio.create_task(_post_or_update_playback_notification(payload))

    is_sync_event = payload.event.lower() in (
        "watched", "on_watched", "media.scrobble",
        "added", "on_added", "library.new", "library-add", "library_add"
    )
    if is_sync_event:
        if payload.rating_key:
            try:
                plex = PlexClient()
                m = await plex.fetch_movie_details(payload.rating_key)
                if m:
                    # Initialize vector variables
                    synopsis_vector = None
                    synopsis_vector_model = None
                    synopsis_vector_dim = None
                    synopsis_vector_updated_at = None
                    
                    # Construct composite document
                    title = m.get("title") or ""
                    year = m.get("year")
                    genres = m.get("genres")
                    synopsis = m.get("synopsis") or ""
                    
                    # Check if database has existing enriched tags to preserve hash/vector consistency
                    tones = None
                    themes = None
                    try:
                        existing_items = LibraryItemRepository.get_by_normalized_title_and_year(
                            normalize_title(title), year
                        ) if title and year else []
                        if existing_items:
                            existing_item = existing_items[0]
                            tones = existing_item.get("tone_tags")
                            themes = existing_item.get("theme_tags")
                            if not genres:
                                genres = existing_item.get("genres")
                    except Exception:
                        pass

                    from moviebot.core.embeddings import (
                        build_composite_document,
                        get_composite_document_hash,
                        get_embedding_result,
                        encode_vector
                    )
                    
                    composite_doc = build_composite_document(
                        title=title,
                        year=year,
                        genres=genres,
                        tones=tones,
                        themes=themes,
                        synopsis=synopsis
                    )
                    synopsis_hash = get_composite_document_hash(composite_doc)
                    
                    # Generate embedding if synopsis or metadata exists
                    if title:
                        try:
                            embedding_result = await get_embedding_result(composite_doc)
                            synopsis_vector = encode_vector(embedding_result.vector)
                            synopsis_vector_model = embedding_result.model
                            synopsis_vector_dim = embedding_result.dim
                            synopsis_vector_updated_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"
                        except Exception as embed_err:
                            print(f"[Webhook Sync Warning] Failed to generate embedding on the fly: {str(embed_err)}")


                    LibraryItemRepository.upsert(
                        id=m["id"],
                        source=m["source"],
                        rating_key=m["rating_key"],
                        title=m["title"],
                        normalized_title=normalize_title(m["title"]),
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
                        synopsis=synopsis,
                        synopsis_hash=synopsis_hash,
                        synopsis_vector=synopsis_vector,
                        synopsis_vector_model=synopsis_vector_model,
                        synopsis_vector_dim=synopsis_vector_dim,
                        synopsis_vector_updated_at=synopsis_vector_updated_at
                    )
                    # Update status
                    EventRepository.insert(
                        event_type=payload.event,
                        source="tautulli",
                        title=payload.title,
                        summary=f"Successfully synced item: {payload.title}",
                        entity_type="movie",
                        entity_id=payload.rating_key,
                        status="synced",
                        severity="info",
                        occurred_at=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat(),
                        data_json=data_json
                    )

                    # Audit via MismatchGuard
                    from moviebot.core.mismatch_guard import MismatchGuard
                    from moviebot.bot.discord_app import post_mismatch_alert
                    
                    guard = MismatchGuard(plex)
                    audit_res = await guard.audit_plex_item(payload.rating_key)
                    if audit_res.get("status") == "mismatch_detected":
                        asyncio.create_task(post_mismatch_alert(audit_res))

                    # Auto-enrich newly added movies and post Discord card
                    is_add_event = payload.event.lower() in (
                        "added", "on_added", "library.new", "library-add", "library_add"
                    )
                    if is_add_event:
                        asyncio.create_task(_auto_enrich_and_notify(m))
                else:
                    print(f"[Webhook Sync Warning] Could not find Plex details for rating key: {payload.rating_key}")
            except Exception as sync_err:
                print(f"[Webhook Sync Error] Failed to sync Plex item: {str(sync_err)}")
        else:
            print(f"[Webhook Sync Warning] Received sync event for '{payload.title}' without rating_key.")

    return {"status": "success", "event_logged": payload.event}


def _coerce_tautulli_payload(raw_payload: Any) -> Optional[TautulliPayload]:
    if not isinstance(raw_payload, dict):
        return None

    event = _first_payload_value(
        raw_payload,
        "event",
        "event_type",
        "event_name",
        "tautulli_event",
        "trigger",
        "action",
        "notification_type",
    )
    event = _normalize_webhook_event(event)
    if not event:
        return None

    return TautulliPayload(
        event=event,
        rating_key=_optional_string(_first_payload_value(raw_payload, "rating_key", "ratingKey")),
        imdb_id=_optional_string(_first_payload_value(raw_payload, "imdb_id", "imdb")),
        title=_optional_string(_first_payload_value(raw_payload, "title", "full_title", "media_title")),
        grandparent_title=_optional_string(_first_payload_value(raw_payload, "grandparent_title", "grandparentTitle")),
        parent_title=_optional_string(_first_payload_value(raw_payload, "parent_title", "parentTitle")),
        media_type=_optional_string(_first_payload_value(raw_payload, "media_type", "mediaType", "type")),
        user=_optional_string(_first_payload_value(raw_payload, "user", "username", "user_name")),
        player=_optional_string(_first_payload_value(raw_payload, "player", "player_name")),
        session_key=_optional_string(_first_payload_value(raw_payload, "session_key", "sessionKey")),
        season_num=_first_payload_value(raw_payload, "season_num", "season", "season_number"),
        episode_num=_first_payload_value(raw_payload, "episode_num", "episode", "episode_number"),
        progress_percent=_first_payload_value(raw_payload, "progress_percent", "progress", "view_offset_percent"),
        duration=_first_payload_value(raw_payload, "duration", "duration_sec", "elapsed"),
        stream_video_resolution=_optional_string(_first_payload_value(raw_payload, "stream_video_resolution", "video_resolution")),
        stream_container_decision=_optional_string(_first_payload_value(raw_payload, "stream_container_decision", "container_decision")),
        poster_url=_optional_string(_first_payload_value(raw_payload, "poster_url", "poster")),
        thumb_url=_optional_string(_first_payload_value(raw_payload, "thumb_url", "thumb")),
        art_url=_optional_string(_first_payload_value(raw_payload, "art_url", "art")),
        occurred_at=_optional_string(_first_payload_value(raw_payload, "occurred_at", "timestamp", "date")),
    )


def _first_payload_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            value = payload[key]
            if value not in (None, ""):
                return value
    return None


def _optional_string(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    return str(value)


def _normalize_webhook_event(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    event = str(value).strip().lower()
    return event or None


def _record_rejected_tautulli_payload(reason: str, raw_payload: Any, summary: str) -> None:
    try:
        EventRepository.insert(
            event_type="tautulli_payload_rejected",
            source="tautulli",
            title=_optional_string(raw_payload.get("title")) if isinstance(raw_payload, dict) else None,
            summary=summary,
            entity_type="webhook_payload",
            entity_id=None,
            status=reason,
            severity="warning",
            data_json=json.dumps(
                {
                    "reason": reason,
                    "payload": raw_payload if isinstance(raw_payload, dict) else str(raw_payload)[:500],
                },
                default=str,
            ),
        )
    except Exception as exc:
        print(f"[Webhook Server Error] Failed to log rejected Tautulli payload: {exc}")



@app.get("/health")
async def health():
    return await get_system_health_tool()


@app.get("/status")
async def get_status(title: str, year: Optional[int] = None):
    return await check_movie_state_tool(title, year)


@app.get("/manifest")
async def manifest():
    return await get_tool_manifest_tool()


@app.get("/events")
async def events(limit: int = 50):
    return await get_recent_events_tool(limit)


@app.get("/logs")
async def logs(source: str, lines: int = 100):
    return await tail_logs_tool(source, lines)


@app.get("/api/library")
async def get_library(
    query: Optional[str] = None,
    semantic_query: Optional[str] = None,
    genre: Optional[str] = None,
    resolution: Optional[str] = None,
    watch_status: Optional[str] = None,
    limit: int = 100
):
    return await query_library_tool(
        query=query,
        semantic_query=semantic_query,
        genre=genre,
        resolution=resolution,
        watch_status=watch_status,
        limit=limit
    )


async def _auto_enrich_and_notify(item: dict):
    """
    Background task: enriches a newly added movie with Gemini smart-merge
    and posts a rich Discord embed card.
    """
    title = item.get("title", "Unknown")
    year = item.get("year")
    item_key = f"auto_enrichment_posted:{item.get('id')}"
    if item.get("id") and KeyValueRepository.get(item_key):
        print(f"[Auto-Enrich] Card already posted for {title} ({year}); skipping webhook duplicate.")
        return

    try:
        from moviebot.core.auto_enrich import auto_enrich_item, build_new_movie_embed
        from moviebot.config import settings as app_settings

        enrichment = await auto_enrich_item(item, provider="gemini")
        if not enrichment:
            print(f"[Auto-Enrich] Enrichment returned None for {title} ({year})")
            return

        # Post Discord notification
        embed = build_new_movie_embed(item, enrichment)

        from moviebot.bot.discord_app import bot
        channels = app_settings.allowed_channels_list
        if not channels:
            print(f"[Auto-Enrich] No Discord channels configured — enrichment saved but card not posted for {title}")
            return

        channel = bot.get_channel(channels[0])
        if not channel:
            try:
                channel = await bot.fetch_channel(channels[0])
            except Exception:
                print(f"[Auto-Enrich ERROR] Could not fetch channel {channels[0]}")
                return

        await channel.send(embed=embed)
        if item.get("id"):
            KeyValueRepository.set(item_key, "webhook")
        print(f"[Auto-Enrich] Posted new movie card for {title} ({year})")

        # Log event
        EventRepository.insert(
            event_type="auto_enrichment",
            source="webhook",
            title=title,
            summary=f"Auto-enriched and posted card for {title} ({year})",
            entity_type="movie",
            entity_id=item.get("id"),
            status="completed",
            severity="info",
        )
    except Exception as e:
        print(f"[Auto-Enrich ERROR] Failed for {title} ({year}): {e}")
        import traceback
        traceback.print_exc()


async def _post_or_update_playback_notification(payload: TautulliPayload):
    try:
        from moviebot.bot.discord_app import bot
        from moviebot.core.playback_notifications import post_or_update_playback_notification

        await post_or_update_playback_notification(payload, bot)
    except Exception as e:
        print(f"[Playback Notification ERROR] Failed for {payload.title or 'unknown media'}: {e}")


# Mount Web Cockpit SPA static directory
web_cockpit_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web"))

from fastapi.responses import FileResponse

@app.get("/test")
@app.get("/sandbox")
async def serve_test_sandbox():
    test_file = os.path.join(web_cockpit_dir, "test.html")
    if os.path.exists(test_file):
        return FileResponse(test_file)
    return {"ok": False, "error": "test.html not found"}

if os.path.isdir(web_cockpit_dir):
    app.mount("/", StaticFiles(directory=web_cockpit_dir, html=True), name="cockpit")

