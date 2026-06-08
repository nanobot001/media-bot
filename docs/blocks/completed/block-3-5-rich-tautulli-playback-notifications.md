# Block 3-5: Rich Tautulli Playback Notifications

> Status: Implemented on 2026-06-07.
> Result: Implemented.
> Verification: `$env:PYTHONPATH='src'; py -3.12 -m pytest tests/test_tautulli_webhook.py tests/test_playback_notifications.py -q --basetemp data\pytesttmp` - passed, 15 tests.
> Notes: Added rich playback card formatting, automatic Plex thumbnail attachment uploads, session-aware Discord post/edit behavior, non-secret kv_store tracking, structured notification events, config/docs updates, and focused tests.

## Goal

Make Tautulli playback notifications concise, rich, and session-aware in Discord. Tautulli should continue to report playback activity to the FastAPI webhook, while media-bot decides what Discord sees: a compact embed for playback start, then an edit to that same message when the session stops or completes when enough session identity is available.

## Scope

- Expand the Tautulli webhook payload model to accept optional playback fields such as `session_key`, `media_type`, `grandparent_title`, `parent_title`, `season_num`, `episode_num`, `progress_percent`, `duration`, `stream_video_resolution`, `stream_container_decision`, and poster/thumb URL fields when Tautulli provides them.
- Add a playback notification formatter that builds compact Discord embeds for playback start, stop, and watched/completed events.
- Store lightweight playback notification state in the existing local state layer, using non-secret keys such as Tautulli session key or a conservative fallback key, so follow-up events can edit the original Discord message instead of always posting a new one.
- Preserve the existing Tautulli event logging behavior and record meaningful structured events for notification post/update/fallback outcomes.
- Preserve existing library sync behavior for watched/library-add events and existing auto-enrichment cards for new media.
- Add configuration for the playback notification target channel if needed, while retaining a safe fallback to the established allowed Discord channel behavior.
- Update `docs/setup-guide.md` with the recommended Tautulli Webhook notification agent payload and trigger setup.
- Add focused tests for payload parsing, embed formatting, session-state keying, and webhook routing behavior.

## Out Of Scope

- Full TV, anime, or TV Classic domain database sync.
- Plex section-to-domain routing or new domain SQLite schemas.
- TV/anime search, download, season pack, or episode acquisition behavior.
- RAG/query support for TV/anime episodes.
- Autonomous monitors or auto-download behavior.
- Replacing the existing new-library-item enrichment embed flow.
- Posting private file paths, API keys, tokens, raw webhook secrets, or sensitive local details to Discord or public-read tool outputs.

## Likely Files Or Areas

- `src/moviebot/api/webhook.py`
- `src/moviebot/config.py`
- `src/moviebot/core/playback_notifications.py` [NEW]
- `src/moviebot/db/repositories.py`
- `src/moviebot/bot/discord_app.py`
- `docs/setup-guide.md`
- `docs/event-log-schema.md`
- `tests/test_tautulli_webhook.py`
- `tests/test_playback_notifications.py` [NEW]

## Acceptance Criteria

- Tautulli playback start events can produce a concise Discord embed containing the viewer, media title, episode context when present, player, playback status, and selected stream/progress details when present.
- Stop or watched events update the matching playback card when a prior message is known for the session.
- If no prior message is known, stop or watched events use a bounded fallback behavior that does not create noisy duplicate message chains.
- Movie playback notifications continue to work with the existing movie-first database baseline.
- TV/anime episode metadata from Tautulli can be displayed when present without requiring TV/anime database sync.
- Existing watched and library-add sync behavior remains intact.
- Existing auto-enrichment cards for newly added media remain intact.
- Notification state stored in `kv_store` contains no secrets and no sensitive local paths.
- Structured event rows are written for meaningful post/update/fallback outcomes.
- Tests cover the new parsing, formatting, and routing behavior.

## Verification

- `$env:PYTHONPATH='src'; py -3.12 -m pytest tests/test_tautulli_webhook.py tests/test_playback_notifications.py -q --basetemp data\pytesttmp`
- Manual local webhook check posts or updates a playback card using a sample `play` payload with `session_key`.
- Manual local webhook check updates or gracefully falls back using a sample `watched` payload for the same `session_key`.
