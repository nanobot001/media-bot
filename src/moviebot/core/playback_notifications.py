import json
from io import BytesIO
from typing import Any, Optional

import discord
import httpx

from moviebot.config import settings
from moviebot.db.repositories import EventRepository, KeyValueRepository


START_EVENTS = {"play", "on_play", "media.play", "media_play", "playback_start"}
STOP_EVENTS = {"stop", "on_stop", "media.stop", "media_stop", "playback_stop"}
WATCHED_EVENTS = {"watched", "on_watched", "media.scrobble", "scrobble"}
PLAYBACK_EVENTS = START_EVENTS | STOP_EVENTS | WATCHED_EVENTS


def normalize_event(event: Optional[str]) -> str:
    return (event or "").strip().lower()


def is_playback_event(event: Optional[str]) -> bool:
    return normalize_event(event) in PLAYBACK_EVENTS


def is_start_event(event: Optional[str]) -> bool:
    return normalize_event(event) in START_EVENTS


def is_terminal_event(event: Optional[str]) -> bool:
    return normalize_event(event) in (STOP_EVENTS | WATCHED_EVENTS)


def build_playback_state_key(payload: Any) -> Optional[str]:
    session_key = _payload_get(payload, "session_key")
    if session_key:
        return f"tautulli_playback_session:{session_key}"

    rating_key = _payload_get(payload, "rating_key")
    user = _payload_get(payload, "user")
    player = _payload_get(payload, "player")
    title = _payload_get(payload, "title")
    if rating_key and user:
        return f"tautulli_playback_fallback:{rating_key}:{user}:{player or 'unknown'}"
    if title and user and player:
        safe_title = str(title).strip().lower()[:80]
        return f"tautulli_playback_fallback:{safe_title}:{user}:{player}"
    return None


def build_playback_embed(payload: Any) -> discord.Embed:
    event = normalize_event(_payload_get(payload, "event"))
    if event in START_EVENTS:
        title = "Now Playing"
        status_text = "Started"
        color = discord.Color.blue()
    elif event in WATCHED_EVENTS:
        title = "Watched"
        status_text = "Completed"
        color = discord.Color.green()
    else:
        title = "Playback Stopped"
        status_text = "Stopped"
        color = discord.Color.orange()

    media_title = _media_title(payload)
    user = _payload_get(payload, "user") or "Unknown viewer"
    embed = discord.Embed(
        title=title,
        description=_narrative_description(payload, user, media_title, status_text),
        color=color,
    )

    context = _media_context(payload)
    if context:
        embed.add_field(name="Media", value=context, inline=False)

    thumb = _first_url(
        _payload_get(payload, "poster_url"),
        _payload_get(payload, "thumb_url"),
        _payload_get(payload, "art_url"),
    )
    if thumb:
        embed.set_thumbnail(url=thumb)

    footer_parts = []
    rating_key = _payload_get(payload, "rating_key")
    session_key = _payload_get(payload, "session_key")
    media_type = _payload_get(payload, "media_type")
    if media_type:
        footer_parts.append(f"Type: {media_type}")
    if rating_key:
        footer_parts.append(f"Rating Key: {rating_key}")
    if session_key:
        footer_parts.append(f"Session: {session_key}")
    if footer_parts:
        embed.set_footer(text=" | ".join(str(part) for part in footer_parts)[:2048])

    return embed


def _narrative_description(payload: Any, user: str, media_title: str, status_text: str) -> str:
    media_type = str(_payload_get(payload, "media_type") or "").lower()
    action = "is listening to" if media_type == "track" else "is watching"
    if status_text == "Stopped":
        action = "stopped" if media_type == "track" else "stopped watching"
    elif status_text == "Completed":
        action = "finished" if media_type == "track" else "finished watching"

    lines = [f"**{user}** {action} {media_title}"]
    status_line = _status_line(payload, status_text)
    if status_line:
        lines.append(status_line)
    return "\n".join(lines)


def _status_line(payload: Any, status_text: str) -> str:
    parts = []
    player = _payload_get(payload, "player")
    if player:
        parts.append(str(player))

    progress = _format_progress(_payload_get(payload, "progress_percent"))
    if progress:
        parts.append(f"{progress} complete")

    duration = _format_duration(_payload_get(payload, "duration"))
    if duration:
        parts.append(f"{duration} elapsed")

    stream = _stream_summary(payload)
    if stream:
        parts.append(stream)

    parts.append(status_text)
    return " • ".join(parts)


def _media_context(payload: Any) -> Optional[str]:
    episode_context = _episode_context(payload)
    if episode_context:
        return episode_context

    parent = _payload_get(payload, "parent_title")
    title = _payload_get(payload, "title")
    if parent and title and str(parent) != str(title):
        return f"{parent} - {title}"[:1024]
    return None



async def post_or_update_playback_notification(payload: Any, bot: Any) -> str:
    """
    Post start cards and update them for stop/watched events.

    Returns one of: posted, updated, skipped_no_state, skipped_no_channel, failed.
    """
    event = normalize_event(_payload_get(payload, "event"))
    state_key = build_playback_state_key(payload)
    embed = build_playback_embed(payload)

    if is_start_event(event):
        channel = await _resolve_playback_channel(bot)
        if not channel:
            _record_notification_event(payload, "skipped_no_channel", "No Discord playback channel configured.")
            return "skipped_no_channel"

        try:
            file = await _build_thumbnail_file(payload, embed)
            send_kwargs = {"embed": embed}
            state_payload = {"channel_id": str(channel.id)}
            if file:
                send_kwargs["file"] = file
                state_payload["thumbnail_url"] = "attachment://media-thumb.jpg"
            message = await channel.send(**send_kwargs)
            if state_key:
                state_payload["message_id"] = str(message.id)
                KeyValueRepository.set(
                    state_key,
                    json.dumps(state_payload),
                )
            _record_notification_event(payload, "posted", "Posted playback start card.")
            return "posted"
        except Exception as exc:
            _record_notification_event(payload, "failed", f"Failed to post playback card: {exc}", severity="error")
            return "failed"

    if is_terminal_event(event):
        if not state_key:
            _record_notification_event(payload, "skipped_no_state", "No playback state key could be built.")
            return "skipped_no_state"

        state = _load_state(state_key)
        if not state:
            _record_notification_event(payload, "skipped_no_state", "No prior playback card was found.")
            return "skipped_no_state"

        try:
            channel = await _resolve_channel(bot, state.get("channel_id"))
            if not channel:
                _record_notification_event(payload, "skipped_no_channel", "Stored playback channel could not be resolved.")
                return "skipped_no_channel"
            if state.get("thumbnail_url"):
                embed.set_thumbnail(url=state["thumbnail_url"])
            message = await channel.fetch_message(int(state["message_id"]))
            await message.edit(embed=embed)
            if event in WATCHED_EVENTS:
                KeyValueRepository.delete(state_key)
            _record_notification_event(payload, "updated", "Updated playback card.")
            return "updated"
        except Exception as exc:
            _record_notification_event(payload, "failed", f"Failed to update playback card: {exc}", severity="error")
            return "failed"

    _record_notification_event(payload, "skipped", "Event is not a playback notification event.")
    return "skipped"


async def _build_thumbnail_file(payload: Any, embed: discord.Embed) -> Optional[discord.File]:
    if _embed_has_thumbnail(embed):
        return None
    image_bytes = await _fetch_plex_thumbnail(_payload_get(payload, "rating_key"))
    if not image_bytes:
        return None
    embed.set_thumbnail(url="attachment://media-thumb.jpg")
    return discord.File(BytesIO(image_bytes), filename="media-thumb.jpg")


async def _fetch_plex_thumbnail(rating_key: Any) -> Optional[bytes]:
    if not rating_key or not settings.plex_token or not settings.plex_url:
        return None
    plex_url = settings.plex_url.rstrip("/")
    endpoint = f"{plex_url}/library/metadata/{rating_key}/thumb"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                endpoint,
                params={"X-Plex-Token": settings.plex_token},
                timeout=8.0,
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if content_type and not content_type.lower().startswith("image/"):
                return None
            return response.content
    except Exception as exc:
        print(f"[Playback Notification] Failed to fetch Plex thumbnail for rating key {rating_key}: {exc}")
        return None


async def _resolve_playback_channel(bot: Any) -> Any:
    channel_id = settings.discord_playback_channel_id
    if not channel_id:
        channels = settings.allowed_channels_list
        channel_id = channels[0] if channels else None
    return await _resolve_channel(bot, channel_id)


async def _resolve_channel(bot: Any, channel_id: Any) -> Any:
    if not channel_id:
        return None
    try:
        channel_int = int(channel_id)
    except (TypeError, ValueError):
        return None
    channel = bot.get_channel(channel_int)
    if channel:
        return channel
    return await bot.fetch_channel(channel_int)


def _load_state(state_key: str) -> Optional[dict[str, str]]:
    raw = KeyValueRepository.get(state_key)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if data.get("channel_id") and data.get("message_id"):
        return data
    return None


def _embed_has_thumbnail(embed: discord.Embed) -> bool:
    return bool(getattr(embed.thumbnail, "url", None))


def _record_notification_event(payload: Any, status: str, summary: str, severity: str = "info") -> None:
    try:
        EventRepository.insert(
            event_type="playback_notification",
            source="discord",
            title=_payload_get(payload, "title"),
            summary=summary,
            entity_type=_payload_get(payload, "media_type") or "media",
            entity_id=_payload_get(payload, "rating_key"),
            status=status,
            severity=severity,
            data_json=json.dumps(
                {
                    "tautulli_event": _payload_get(payload, "event"),
                    "session_key": _payload_get(payload, "session_key"),
                    "user": _payload_get(payload, "user"),
                    "player": _payload_get(payload, "player"),
                }
            ),
        )
    except Exception as exc:
        print(f"[Playback Notification] Failed to record notification event: {exc}")


def _media_title(payload: Any) -> str:
    grandparent = _payload_get(payload, "grandparent_title")
    title = _payload_get(payload, "title")
    if grandparent and title:
        return f"**{grandparent}**"
    if title:
        return f"**{title}**"
    return "**Unknown media**"


def _episode_context(payload: Any) -> Optional[str]:
    grandparent = _payload_get(payload, "grandparent_title")
    title = _payload_get(payload, "title")
    if not grandparent:
        return None

    season = _payload_get(payload, "season_num")
    episode = _payload_get(payload, "episode_num")
    code = ""
    if season not in (None, "") and episode not in (None, ""):
        code = f"S{_as_int_string(season).zfill(2)}E{_as_int_string(episode).zfill(2)} - "

    parent = _payload_get(payload, "parent_title")
    context = f"{code}{title or 'Unknown episode'}"
    if parent and not code:
        context = f"{parent} - {context}"
    return context[:1024]


def _stream_summary(payload: Any) -> Optional[str]:
    parts = []
    resolution = _payload_get(payload, "stream_video_resolution")
    decision = _payload_get(payload, "stream_container_decision")
    if resolution:
        parts.append(str(resolution))
    if decision:
        parts.append(str(decision).replace("_", " ").title())
    return " / ".join(parts)[:1024] if parts else None


def _format_progress(progress: Any) -> Optional[str]:
    if progress in (None, ""):
        return None
    value = str(progress).strip()
    return value if value.endswith("%") else f"{value}%"


def _format_duration(duration: Any) -> Optional[str]:
    if duration in (None, ""):
        return None
    try:
        seconds = int(float(duration))
    except (TypeError, ValueError):
        return str(duration)[:1024]
    if seconds <= 0:
        return None
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"


def _first_url(*values: Any) -> Optional[str]:
    for value in values:
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return None


def _payload_get(payload: Any, key: str) -> Any:
    if isinstance(payload, dict):
        return payload.get(key)
    return getattr(payload, key, None)


def _as_int_string(value: Any) -> str:
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value)
