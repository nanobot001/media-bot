# Tool Adapter Memory

## Project Role

`media-bot` is a modular, stateful Discord automation assistant and tool server that allows users and AI agents to:
1. Search and cross-reference Plex libraries to avoid duplicate downloads.
2. Search movie indexers on Prowlarr.
3. Queue high-speed direct downloads using AllDebrid and Windows Internet Download Manager (IDM).
4. Run diagnostics on active downloads and system exceptions.

## Classification

New tool-friendly project built from scratch using decoupled, parameter-driven JSON tool boundaries with a Discord gateway presentation layer.

## Runtime Model

- **PM2-supervised host process (Windows)**: Starts via Node.js supervisor (`scripts/launcher.js`) using `pm2 start scripts/launcher.js --name media-bot`, which prefers the project `.venv\Scripts\python.exe`, validates Python 3.12 plus the required imports before launch, skips broken system executables, supports `MEDIABOT_PYTHON` / `MEDIABOT_PYTHONHOME` overrides, runs the module in a hidden window (`windowsHide: true`), and forwards termination signals to prevent orphaned processes.
- **Docker service**: A python:3.12-slim based container running on Docker compose alongside Prowlarr and Flaresolverr.
- **Web service**: FastAPI webhook listener running on port `8000` to receive Tautulli notifications.
- **MCP server**: A `FastMCP` stdio-based server (`src/moviebot/cli/mcp_server.py`) exposing the tools to AI assistants.

## Source Of Truth

A local SQLite database stored at `data/moviebot.sqlite3` containing Plex cache mirrors, search logs, download job tracks, and exception logs.

## Instant Stream Readiness Contract

- `available_now` is a TMDb release-window classification only; it is not evidence of an AllDebrid cache.
- Discovery stream fields are derived from recent pre-warm verification: `cloud_cached`, `instant_download_ready`, `instant_cached`, `browser_stream_ready`, `instant_stream_status`, and `stream_reference_id`.
- `instant_cached` means a verified browser-streamable cached release only. The raw provider cache bit remains available as `cloud_cached` / `cached` for instant downloading, even when the release requires an external player.
- Each durable `prewarmed_cache` media record keeps the cached download candidate in `reference_id` / `release_title` and the preferred browser-stream candidate in `browser_stream_reference_id` / `browser_stream_release_title`; Discover uses the latter when opening a stream.
- Browser one-click playback requires an explicitly identified MP4/M4V release with H.264-family video and AAC/MP3 audio; cached MKV, HEVC/AV1, DDP/DTS/TrueHD, or unknown-audio releases remain external-player candidates and must not receive the browser-ready lightning state.
- Discover keeps `Stream Now` disabled until that browser candidate is verified. `POST /api/stream/prepare` is the explicit browser-only acquisition path: it enforces exact movie title/year (or TV season/episode), verifies cached candidates against the actual AllDebrid filename, and otherwise queues only a release that explicitly advertises MP4/M4V + H.264/AVC + AAC/MP3. The unrestricted Search/IDM path remains separate.
- `cloud_transfer_intents` is the durable ownership boundary for AllDebrid operations initiated manually through Media Bot. `/api/cloud/transfers` and `/api/cloud/notifications` merge provider status only for these locally owned transfer IDs; account-wide AllDebrid history and passive pre-warm checks must stay silent.
- `generic_cloud_cache` means ready for instant AllDebrid download only. `browser_stream` may become browser-ready only after completed-file verification; the UI and notifications must not claim browser playback for a generic cached release.
- Movie pre-warming maintains separate durable SQLite-KV cursors for a recent release-year frontier (current year down through 1980) and a TMDB all-time popularity frontier. Existing cache records are reverified before new candidates are scanned; pre-1980 titles are reached through the all-time popularity lane rather than an oldest-first crawl.

## Durable Pre-warm Runtime Contract

- `prewarm_runs` in the primary Movies database is the authoritative lifecycle ledger for system-wide passive cycles. It retains scheduled, running, completed, failed, interrupted, and skipped attempts with timestamps, trigger, interval, phase counts, provider-error count, stop reason, and sanitized structured errors.
- `prewarm_runtime_state` owns the global next-due timestamp and singleton lease. The active runtime renews the lease every 30 seconds; five minutes without a heartbeat makes the run eligible for `interrupted` reconciliation before another runtime can acquire it.
- A PM2 restart preserves the durable next-due timestamp. The scheduler starts independently of Plex startup synchronization and does not reset cadence from process-local memory.
- Concurrent startup or manual attempts never overlap. The rejected attempt is retained as `skipped` with `PREWARM_BUSY` and the active cycle ID.
- `GET /api/prewarm/status` returns sanitized active, last, next-due, and bounded cycle-history fields. `GET /api/prewarm/items` retains its prior fields and adds the same runtime projection for compatibility.
- The web Settings card shows active/last/next status; the History pre-warm panel shows the latest ten cycles. All cycles remain retained and older pages are available with bounded `limit` and `offset` status queries.
- Passive cycle state and events never create `cloud_transfer_intents`, transfer cards, notifications, downloads, or provider-wide cleanup actions.

## Release-Variant Availability Catalog Contract

- `release_variants` is the additive long-term catalog in the primary Movies database. It retains multiple exact releases for a movie title/year or explicit TV series/season-pack/episode/complete-series scope; `prewarmed_cache` remains readable for compatibility.
- AllDebrid cache evidence, direct-play evidence, and MediaFlow evidence are independent per variant. MediaFlow qualification never changes the canonical availability class.
- Canonical availability is `unknown`, `not_cached` (A), `ad_cached` (B), or `direct_play_ready` (C). State A requires a fresh, complete bounded `release_catalog_checks` record with zero cached variants; missing, stale, partial, failed, or legacy false evidence remains `unknown`.
- `cached` and `cloud_cached` are additive B/C aliases. `instant_cached` and `browser_stream_ready` remain C-only aliases backed by fresh exact direct-play evidence.
- `GET /api/prewarm/catalog` and `availability-inspect` are bounded read-only inspectors for one exact media scope. They expose sanitized release facts, evidence statuses/freshness, coverage, and first/last observation timestamps, but never provider references, raw magnets, URLs, credentials, private paths, or raw evidence payloads.
- Legacy migration is additive and idempotent: fresh browser evidence becomes C evidence, cached-only rows become B evidence, and false/absent cache bits remain `unknown`. The migration does not delete or rewrite `prewarmed_cache` rows.

## Catalog Population And Provider Truth Contract

- Search and passive pre-warming use one structured AllDebrid outcome mapper. Per-candidate status is `cached`, `not_cached`, `unknown`, `provider_error`, or `unresolvable`; compatibility `cached` remains true only for `cached`.
- A provider timeout, HTTP failure, malformed payload, or failed batch is provider-error evidence. A missing item in a partial response remains `unknown`. Neither can prove state A.
- Bounded searches retain every exact eligible release variant after the movie quality gate and exact movie-year or TV-scope checks. Ranking selects a recommendation but never deletes lower-ranked variants.
- Passive writes include source-vector and durable cycle identity, preserve first-seen timestamps, and reverify catalog variants without recomputing their release identities or inheriting another variant's direct-play evidence.
- Completed pre-warm cycles expose catalog discovered, retained, checked, cached, uncached, unknown, and provider-error counts. Provider-error variants are included in unknown coverage rather than treated as uncached.

## Unified Availability Projection Contract

- Discovery, Search, pre-warm item reads, CLI Discovery, MCP Discovery, and the web UI consume the same sanitized `availability` projection from `AvailabilityService`.
- `availability_state` is `unknown`, `not_cached`, `ad_cached`, or `direct_play_ready`; additive `availability_tier` is respectively `unknown`, `A`, `B`, or `C`. Coverage and freshness metadata explain whether evidence was complete and current.
- `availability_scope` uses canonical `movies`, `tv`, or `tv_classic` identity and explicit `movie`, `series`, `season_pack`, `episode`, or `complete_series` scope. `classic_tv` remains an accepted input alias but durable catalog reads use `tv_classic`.
- Search and pre-warm rows add `variant_availability_state` for the exact displayed release while the nested `availability` object describes the requested title/scope. A cached episode or season never promotes an unscoped series card.
- `cached_variants` and all variant summaries are bounded and sanitized. They may expose release facts and evidence status, but never raw magnets, provider URLs, credentials, private paths, or provider payloads.
- Legacy action references remain additive compatibility fields. They cannot promote unknown, stale, partial, or provider-error evidence to A/B/C, and the UI labels unknown evidence as unknown rather than claiming an active search.
- Catalog population and re-verification remain silent and non-acquiring: they create no `cloud_transfer_intents`, downloads, Cloud Transfer cards, or completion notifications.

## MediaFlow Production Adapter Contract

- Production MediaFlow playback is controlled by `MEDIAFLOW_PRODUCTION_ENABLED`, defaults to disabled, requires the approved v2.4.9 pin, and accepts only localhost configuration with a configured API password.
- `POST /api/mediaflow/playback` accepts one exact `release_variant_id`, verifies its requested movie/TV scope, fresh provider-cached evidence, and movie quality eligibility, then reuses the pilot's sanitized probe, delivery-decision, encrypted URL, and safe-HLS fallback contracts.
- Direct-play remains the preferred route and the only source of state C. A successful MediaFlow session updates only the selected variant's independent MediaFlow evidence and never sets `browser_stream_ready` or `instant_cached`.
- The browser receives an opaque `/api/mediaflow/sessions/{session_id}/stream` reference. Raw provider URLs, magnets, passwords, authorization headers, and command arguments remain server-side and are not retained in public responses or structured events.
- Browser playing/failure telemetry changes MediaFlow evidence from `candidate` to `verified` or `failed`. Seek, completion, source replacement, explicit close, timeout, and shutdown use the bounded session registry and sanitized cleanup events.
- For forward-only `transcode_stream` responses, timeline seeking uses `POST /api/mediaflow/sessions/{session_id}/seek`: the server reuses the private unlocked source, rotates the signed URL with a new `start_seconds`, and returns the same opaque stream reference. The browser debounces drag events and aborts the previous response before resuming.
- `GET /api/mediaflow/status` exposes only enabled/configured/health/pin/session-count state. Configuration-only rollback restores the pre-existing direct browser and local VLC paths without a migration.
- `MEDIAFLOW_DIAGNOSTICS_MODE` controls sanitized evidence as `off`, `summary`, or `detailed`; invalid values use `summary`. Off mode still retains the minimal schema/decision version, failure stage, code, and retryability required for truthful operation.
- `GET /api/mediaflow/diagnostics` is a bounded localhost-only trusted read over structured MediaFlow events. It marks legacy or mismatched decision versions stale and never exposes source URLs, magnets, credentials, headers, command lines, or private paths.
- Preparation and browser failures carry a versioned stage-specific diagnostics envelope. Admission evidence may include allowlisted source measurements, workload/profile source, guardrails, current capacity, reason labels, and a safe next action according to the configured mode.
- When the app requires stereo for a selected stream with more than two audio channels, the adapter requires MediaFlow health capability `force_audio_stereo=true` and sends the signed `force_audio_stereo` parameter on direct transcode. The configured v2.4.9 image is a bounded pinned adaptation that applies the downmix in the universal transcode path; if the capability is absent, the adapter fails closed before source delivery.

## Existing Pieces Reused

Reuses regex/heuristic models and powerShell-bridge configurations (`run_idm_bridge.ps1`) derived from the adjacent `anime-pipe` project to delegate downloads from Docker containers to host Windows systems.

## Adaptation Gaps Filled

Successfully migrated to the AllDebrid `/v4.1` API. Implemented recursive dictionary-based directory flattening (`_flatten_files`) in the adapter to translate nested folders/files arrays to sequential flat IDs, maintaining 100% backward compatibility with downstream file selector tools.

## Tool Surface

All tools return standard JSON envelopes (`{ "ok": bool, "tool": str, "timestamp": str, "data": {} }` or `{ "ok": false, ... "error": {} }`):
1. `search_library`: Queries local Plex cache mirror.
2. `dedupe_check`: Normalizes titles and applies fuzzy Matching/IMDb checks to identify library duplicates.
3. `search_sources`: Searches Prowlarr indexers for category 2000 torrents, returning hashes instead of raw magnet keys.
4. `enqueue_download`: Initiates download pipeline in AllDebrid and hands off direct stream links to the IDM host bridge.
5. `get_download_jobs`: Returns current or past active job states.
6. `get_error_logs`: Lists recent database exceptions for audit.
7. `query_watch_history`: Fetches viewing timelines from Tautulli.
8. `resolve_pending_jobs`: Resolves AllDebrid jobs in `pending` status, pushes unlocked links to IDM, and moves states.

## Permission Boundaries

- `public_read`: `search_library`, `dedupe_check`, `search_sources`
- `trusted_read`: `get_download_jobs`, `get_error_logs`, `query_watch_history`
- `write_action`: `enqueue_download` (supports `dry_run`), `resolve_pending_jobs` (supports `dry_run`)

## State/Event Schema

- `library_items`: Normalised Plex media inventory.
- `search_results`: Tracked query caches with obfuscated magnet URLs.
- `download_jobs`: Download states (`pending`, `downloading`, `requires_selection`, `completed`, `failed`).
- `errors`: Pruned exception logs (max 500 records).
- `events`: Tautulli watch activities.
- `kv_store`: System cursors and state flags.

## Bot Usage Notes

- Discord slash commands validate constraints using `@in_allowed_channel()` decorator.
- Errors in commands auto-alert admins inside the `#media-errors` channel using Discord Embeds while logging stack traces to the SQLite `errors` table.
- A background worker runs every 60s in `discord_app.py` to auto-resolve pending torrent downloads.

## Do Not Break

- **Obfuscation**: Never expose raw magnet URLs or API keys in search tool return payloads.
- **Dry-run**: Always respect `dry_run=True` to allow pipeline logic validation without pushing actual links to IDM/AllDebrid.
- **Two-Step Debrid Resolve**: AllDebrid v4.1 requires checking `/magnet/status` (looking for `statusCode == 4`) followed by fetching file paths from `/magnet/files`.

## Known Limitations

- Limited to Movie downloads (Category 2000). TV shows are out-of-scope.
- Cannot organize, rename or relocate completed downloads (handled by separate `media-watcher` process).

## Verification Commands

- **Unit tests (Host)**: `$env:PYTHONPATH="src"; .\.venv\Scripts\python.exe -m pytest --ignore=tests/test_mcp_server.py`
- **CLI dry-run**: `.\.venv\Scripts\python.exe -m moviebot.cli.tool_cli download --id "<obfuscated_id>" --dry-run`
