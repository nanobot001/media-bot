import json
import datetime
from typing import Optional
from fastapi import FastAPI, Header, Query, HTTPException, Depends, status
from pydantic import BaseModel
from moviebot.config import settings
from moviebot.adapters.plex_client import PlexClient
from moviebot.db.repositories import LibraryItemRepository, EventRepository
from moviebot.core.dedupe import normalize_title
from moviebot.tools.check_movie_state_tool import check_movie_state_tool
from moviebot.tools.get_system_health_tool import get_system_health_tool
from moviebot.tools.get_tool_manifest_tool import get_tool_manifest_tool
from moviebot.tools.get_recent_events_tool import get_recent_events_tool
from moviebot.tools.tail_logs_tool import tail_logs_tool


app = FastAPI(docs_url=None, redoc_url=None)

class TautulliPayload(BaseModel):
    event: str
    rating_key: Optional[str] = None
    imdb_id: Optional[str] = None
    title: Optional[str] = None
    user: Optional[str] = None
    player: Optional[str] = None
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
async def tautulli_webhook(payload: TautulliPayload):
    occurred = payload.occurred_at or datetime.datetime.utcnow().isoformat()
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

    is_watched = payload.event.lower() in ("watched", "on_watched", "media.scrobble")
    if is_watched:
        if payload.rating_key:
            try:
                plex = PlexClient()
                m = await plex.fetch_movie_details(payload.rating_key)
                if m:
                    LibraryItemRepository.upsert(
                        id=m["id"],
                        source=m["source"],
                        rating_key=m["rating_key"],
                        title=m["title"],
                        normalized_title=normalize_title(m["title"]),
                        year=m["year"],
                        imdb_id=m["imdb_id"],
                        file_path=m["file_path"],
                        size_bytes=m["size_bytes"]
                    )
                    # Update status
                    EventRepository.insert(
                        event_type=payload.event,
                        source="tautulli",
                        title=payload.title,
                        summary=f"Successfully synced watched item: {payload.title}",
                        entity_type="movie",
                        entity_id=payload.rating_key,
                        status="synced",
                        severity="info",
                        occurred_at=datetime.datetime.utcnow().isoformat(),
                        data_json=data_json
                    )
                else:
                    print(f"[Webhook Sync Warning] Could not find Plex details for rating key: {payload.rating_key}")
            except Exception as sync_err:
                print(f"[Webhook Sync Error] Failed to sync Plex item: {str(sync_err)}")
        else:
            print(f"[Webhook Sync Warning] Received watched event for '{payload.title}' without rating_key.")

    return {"status": "success", "event_logged": payload.event}


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

