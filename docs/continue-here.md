# Continue Here

## 2026-09-01 (Block 5-5j-2 activated locally)

Current state:
- [Block 5-5j-2](blocks/block-5-5j-2-mediaflow-segmented-producer-supervision.md) is implemented and locally verified on `codex/block-5-5j-2-segmented-producer`. Heavy `full_transcode` and `subtitle_burn` decisions now use a private-to-opaque HLS gateway, while direct, remux, and audio-only route selection remains unchanged.
- Chromium playback uses vendored, integrity-verified HLS.js 1.7.1. MediaFlow 2.4.9 HLS segments preserve forced AAC-stereo intent; manifest and segment bytes, retained target references, produced-segment evidence, startup/idle deadlines, terminal codes, and per-session capacity release are bounded and sanitized.
- The digest-pinned custom image built successfully. A disposable local 135.021-second fixture exposed 27 segments; the initial segment produced 188,686 bytes in 0.093 seconds and the segment beginning at 120.0 seconds produced 187,734 bytes in 0.110 seconds. The public manifest exposed no private target and the worker PID remained unchanged across the proof.
- Focused verification passed 54 tests and the final repository-wide suite passed 443 tests. Python/JavaScript compilation, Compose configuration, custom-image build, and `git diff --check` passed. The implementation is checkpointed in commit `640d6ed`.
- The active MediaFlow container was deliberately recreated from `media-bot/mediaflow-proxy:v2.4.9-audio-stereo`, reached healthy state with segmented-HLS and forced-stereo capabilities, and PM2 `media-bot` alone was restarted. The sanitized status API reported MediaFlow enabled, configured, and healthy with zero active sessions; the dashboard showed `MediaFlow On`, `0/1 heavy`, and opened the sanitized diagnostics view. The vendored HLS.js asset returned successfully. No provider-backed playback canary was run.
- The unrelated future Block 5-8 MCP compatibility work remains in the named stash `preserve Block 5-8 MCP compatibility work`.

Next step:
- After publication, prepare Block 5-5j-3 for random seek ownership, supersession, cancellation, and complete disconnect cleanup. Blocks 5-5j-4 and 5-5j-5 still own the release-class/HDR matrix and safe alternate-version fallback, so the parent comprehensive program is not yet complete.

## 2026-08-30 (Block 5-5j-2)

Current state:
- The accumulated MediaFlow production checkpoint was verified with all 432 tests and merged as PR #12 / `e7f2a57`; local `main` and `origin/main` converged before the next branch was created.
- [Block 5-5j-2](blocks/block-5-5j-2-mediaflow-segmented-producer-supervision.md) is selected on `codex/block-5-5j-2-segmented-producer`. Its bounded outcome is sustained incremental heavy-transcode output with startup/idle supervision and bounded retention; random seek ownership, release-class/HDR coverage, and alternate-version fallback remain later children.
- The unrelated future Block 5-8 MCP compatibility work remains preserved in the named Git stash `preserve Block 5-8 MCP compatibility work` and was not included in PR #12.

Next step:
- Implement and fixture-verify the supervised segmented producer. Do not claim comprehensive MediaFlow playback until Blocks 5-5j-2 through 5-5j-5 satisfy the parent acceptance criteria.

## 2026-08-30 (Block 5-5j-1)

Current state:
- The comprehensive MediaFlow successor is documented in [Block 5-5j](blocks/block-5-5j-mediaflow-comprehensive-browser-delivery.md), with compatibility-first child sequencing for diagnostics, segmented production, seek/cancellation, release-class/HDR coverage, and safe alternate-version fallback.
- [Block 5-5j-1](blocks/block-5-5j-1-mediaflow-diagnostics-admission-evidence.md) is implemented locally on `codex/block-5-5j-mediaflow-diagnostics`. MediaFlow errors now carry versioned sanitized stages and admission evidence, `MEDIAFLOW_DIAGNOSTICS_MODE` supports off/summary/detailed projections, `/api/mediaflow/diagnostics` returns bounded localhost-only attempts, legacy decisions are marked stale, and the dashboard exposes a permanently visible `Diagnostics` view. The publication checkpoint passed all 432 tests, plus Python/JavaScript compilation, Compose configuration, and `git diff --check`.
- The branch inherited the earlier uncommitted 5-5c/5-5i working tree. The accumulated MediaFlow runtime is now checkpointed in commit `c7d577d`; `media-bot` was restarted and the live diagnostics route and dashboard assets were verified locally. No provider retry, database migration, threshold relaxation, or live playback canary occurred during 5-5j-1.

Next step:
- Review and publish the inherited MediaFlow checkpoint deliberately rather than staging the whole dirty worktree blindly.
- The next implementation child is the segmented producer/startup-idle supervision slice. Do not claim NeoNoir playable until that path and measured admission evidence are verified.

## 2026-08-30

Current state:
- A bounded MediaFlow capacity layer is now implemented on `codex/block-5-5c-mediaflow-production-browser-adapter` but is not yet committed or published. Heavy video transcodes (`full_transcode` and `subtitle_burn`) receive sanitized workload profiles and atomic CPU, memory, GPU, encoder-slot, and active-session reservations before signed MediaFlow URL generation. Locally measured p95 profiles can be supplied through `MEDIAFLOW_CAPACITY_PROFILES_JSON`; absent those profiles, the existing 6 GiB / 7200-second guard remains the conservative fail-safe. Direct/remux paths reserve no heavy capacity, competing heavy work returns a retryable sanitized capacity error, and the bottom runtime bar displays the current heavy-slot count when MediaFlow health is available.
- The guard is a protective admission layer, not the final streaming fix. The pinned MediaFlow container still has one Gunicorn worker, a 120-second worker timeout, 2 GiB memory, and 4 CPUs; a proper long-lived segmented streaming worker with idle-timeout supervision remains the next larger follow-up.
- Verification passed with 53 focused MediaFlow/web tests, Python compilation, and `git diff --check`. No new provider playback attempt was run, and only the admission code/runtime state is ready for review.

Next step:
- Review the admission behavior and commit/publish the current Block 5-5c checkpoint before continuing the remaining vendor/streaming-worker work.
- [Block 5-5i](blocks/block-5-5i-mediaflow-resilient-segmented-streaming.md) now has its capacity/admission portion implemented with limitations. Its remaining success criteria require incremental fragments beyond 120 seconds, idle-timeout supervision, reliable seek/cancellation, bounded cleanup, and sustained-playback verification.
- When the segmented streaming redesign is authorized, begin with a local long-duration HEVC/DTS fixture and prove incremental fragments, idle timeout, cancellation, bounded concurrency, and seek cleanup before any provider canary.

## 2026-08-29

Current state:
- Block 5-5c is implemented on `codex/block-5-5c-mediaflow-production-browser-adapter` but is not yet committed or published. The disabled-by-default production adapter accepts one exact eligible cached catalog variant, reuses the pinned MediaFlow v2.4.9 client and delivery decisions, returns only an opaque local playback session, records MediaFlow evidence separately from A/B/C, and performs bounded lifecycle cleanup.
- The normal movie detail now lists sanitized cached versions. Verified direct play remains preferred; an eligible non-direct variant offers `Play this version` only when the adapter is enabled and healthy, otherwise it shows `MediaFlow off`. Existing direct playback, external-player, and VLC fallback paths remain intact.
- A visibility follow-up adds `MediaFlow On`, `MediaFlow Off`, or `MediaFlow Error` to the fixed bottom runtime bar. This corrects the live UX gap where the exact-version action was present but below the first viewport in the movie-detail modal; a 382x920 browser check confirmed `MediaFlow On` is fully visible.
- Verification now passes with 46 focused audio/adapter/web tests, 402 full non-MCP tests, and 19 MCP tests, plus JavaScript syntax, Python compilation, Docker Compose configuration, the pinned custom MediaFlow image build and activation, and `git diff --check`.
- PM2 `media-bot` was restarted alone after the operator explicitly enabled `MEDIAFLOW_PRODUCTION_ENABLED` in the local `.env`. The sanitized status endpoint reported `enabled: true`, `configured: true`, `pin_valid: true`, expected version `2.4.9`, zero active sessions, and healthy MediaFlow service state. A refreshed local movie detail showed `Play this version` and no `MediaFlow off` action while preserving the title's provider-cached A/B/C label.
- The operator subsequently ran live playback attempts. `The Devil Wears Prada 2` reached browser playback, but exact variant `Toy Story 5 2026 1080p WEB-DL HEVC x265 5 1-BONE` failed twice after MediaFlow started its pipeline. The app requested full transcode with stereo audio, while pinned MediaFlow v2.4.9 re-encoded HEVC video but copied the already-AAC 5.1 track instead of enforcing the requested downmix. This is a confirmed app/MediaFlow execution-contract gap; the pilot's HEVC fixture used EAC3 and therefore did not cover HEVC plus multichannel AAC.
- The bounded corrective fix is now implemented: multichannel audio is detected before delivery, the adapter fails closed if the MediaFlow health contract lacks stereo-downmix capability, and the pinned custom v2.4.9 image applies the requested downmix in the universal transcode path. A real local HEVC plus AAC 5.1 fixture produced H.264 video with AAC stereo output; the active MediaFlow service advertises the capability and the app reports it healthy. The exact provider-backed Toy Story canary was not rerun.
- Forward-only `transcode_stream` seeking is now implemented: native timeline clicks/drags and arrow-key seeks debounce for 250ms, abort the old response, call the localhost-only seek route, reuse the same private source without re-unlocking the provider, and rotate the opaque playback URL. The pinned image skips packets before the requested target and preserves absolute fMP4 timeline/duration metadata. A local 6-second seek on the HEVC plus AAC 5.1 fixture produced video start 6.000s, about 12.01 seconds total duration, and AAC stereo.
- The long-file duration gap is now corrected: the handler’s authoritative source duration is passed into the pinned universal fMP4 pipeline for initial playback, while seeked streams retain their remaining-duration override. Initial local playback exposed the full 12-second fixture duration, and the 6-second seek still preserved the absolute timeline and AAC stereo output.
- The operator reports additional bugs beyond the Toy Story failure, but they have not yet been inventoried or diagnosed. Block 5-5c is implemented with the exact-title/live-canary limitation above; do not claim broad production playback readiness. The local runtime flag remains enabled unless separately changed; configuration-only rollback remains available by setting it to `false` and restarting only `media-bot`.
- The Antigravity `media-bot` MCP launcher was repaired separately: `pyproject.toml` now constrains `mcp>=0.9.1,<2`, the existing `.venv` uses MCP 1.29.1, and Antigravity invokes `.venv\Scripts\python.exe` directly instead of unavailable `py -3.12`. The exact configured server command exited cleanly on closed stdin, `FastMCP` and the server module import successfully, and all 19 MCP tests passed.

Next step:
- Inventory every additional playback bug with exact title/release, expected behavior, and observed result. Diagnose shared versus independent causes before editing or retrying live playback.
- Manually verify timeline click/drag behavior in the browser on a fixture-backed or explicitly authorized title; the automated fMP4 proof confirms server output but not operator interaction in the browser.
- If desired, make a separately authorized operator canary for the exact Toy Story release, then record browser-confirmed playback and sanitized runtime evidence. The local fixture proof does not substitute for that canary.
- Do not push or merge this block as broadly production-ready until the additional bug inventory and any required follow-up fixes are reviewed; the current work remains a recoverable local checkpoint.

Do-not-forget checks:
- MediaFlow verification is per exact variant and never promotes title state B to C or sets `browser_stream_ready` / `instant_cached`.
- Never expose raw provider references, signed MediaFlow URLs, credentials, authorization headers, or private command arguments to browser-visible responses, logs, or persisted evidence.
- A successful URL resolution, MediaFlow pipeline start, or one known-good title is not broad browser-playback proof. Require fixture coverage for each codec/channel contract and operator-confirmed playback separately.
- Do not run another provider playback attempt without explicit authorization. Rollback is configuration-only and requires no migration.

## 2026-08-29 (Block 5-5h handoff)

Current state:
- Block 5-5h implementation is complete on `codex/block-5-5h-unified-availability-projection`. Discovery, Search, pre-warm item APIs, CLI, MCP delegation, and the UI now consume one sanitized catalog projection with canonical domain/scope identity, title/scope and exact-variant states, bounded cached variants, and truthful unknown labels. Verify its current publication and merge state from Git and GitHub before treating it as integrated.
- The reusable projection matrix covers unknown, A, B, C, stale evidence, provider errors, movie remakes, TV episodes, season packs, series isolation, and the `classic_tv` to `tv_classic` alias. Forty-six focused non-MCP tests and 387 full non-MCP tests passed; JavaScript syntax, Python compilation, manifest parsing, and diff checks passed.
- MCP verification remains blocked before assertions because `.venv` has MCP 2.1.1 while `mcp_server.py` and its tests use the 1.x `FastMCP` import. No dependency change or live provider mutation was performed. PM2 `media-bot` was subsequently restarted, and a read-only live projection/UI smoke passed, including the accessible icon-plus-text availability labels.
- Block 5-5f was merged through PR #8 at `9b00014`; the separately authorized live cleanup removed 12 definite identity mismatches from both catalog tables, restarted only PM2 `media-bot`, and verified that The Odyssey (2026) now reports unknown with zero variants.
- Block 5-5g was merged through PR #9 at `dc2440a` (`73baa16` feature commit). Search and passive pre-warming now share structured AllDebrid outcomes, retain every bounded exact variant, preserve first-seen and cycle/source evidence, and expose catalog discovered/retained/checked/cached/uncached/unknown/provider-error counts.
- Provider timeouts, HTTP failures, malformed responses, missing partial results, and unresolvable references no longer collapse to a successful uncached result. Passive work still creates no transfer ownership, downloads, cards, or completion notifications.
- Verification passed with 28 focused tests and 384 full non-MCP tests; `node --check src\moviebot\web\app.js` and `git diff --check` passed. Ruff was configured but unavailable in the project virtual environment. PM2 `media-bot` was restarted alone (PID `19872` to `35552`), then manual cycle `55ee35a36c344fed9aa3014362321d7c` completed with 311 discovered, 310 retained, 309 checked, 295 cached, 14 uncached, 2 unknown, and 0 provider errors. The transfer-intent, transfer/browser-event, and download-job baselines remained unchanged at 1, 4, and 43 respectively; no database cleanup was performed.

Next step:
- After Git/PR evidence confirms 5-5h integration and local `main` synchronization, implement Block 5-5c on a dedicated branch without mixing in the MCP SDK migration.
- Separately decide whether to pin or migrate the MCP SDK so the legacy MCP server suite can collect again.

Do-not-forget checks:
- The nested `availability` object is title/scope truth; `variant_availability_state` is the exact displayed Search/pre-warm release. Do not use one variant's state for another.
- `unknown` includes provider errors, partial missing results, and unresolvable references; only complete successful coverage can derive state A.
- Ranking may recommend one release but must not delete lower-ranked exact variants or transfer direct-play evidence between variants.
- Keep passive provider checks silent, ownership-safe, and free of raw magnets, provider URLs, credentials, and private paths.

## 2026-08-28

Current state:
- Block 5-5e is merged through PR #7 at `5e311b1`; local `main` and `origin/main` were synchronized before the next feature branch was created.
- Block 5-5f is implemented on `codex/block-5-5f-release-variant-availability-catalog` but is not yet committed or published. The primary Movies database now has additive `release_variants` and `release_catalog_checks` state, exact movie/TV scope identity, independent AllDebrid/direct-play/MediaFlow evidence, canonical unknown/A/B/C derivation, and a sanitized API/CLI inspector.
- Verification passed after the identity correction: 26 focused catalog/browser/prewarmer tests and 379 full non-MCP tests. Both suites left the active catalog count unchanged at 197. A read-only preview against the verified pre-correction backup retained 182 exact variants from 203 legacy rows and skipped 20 unproven identity associations, including `The Odyssey` availability sourced from `The Odyssey The Making of an Epic`.
- The active database was additively initialized during the first focused test collection because `tests/test_background_prewarmer.py` called `init_db()` at module scope before its temporary-database fixture. That unsafe collection-time call is removed. PM2 was not restarted and file watching is disabled.
- A consistent pre-correction SQLite backup passed `quick_check` at `scratch/live-db-backups/moviebot-before-5-5f-identity-correction-20260828-235110.sqlite3`. The already-migrated mismatched variants remain in the active database until a separately authorized cleanup after review/publication; the corrected migration does not destructively delete historical rows.
- Block 5-5c remains planning-only. The existing MediaFlow client, pilot page, fixtures, and capability tests belong to completed Block 5-5b; normal playback has not been replaced by the production adapter.
- Diagnosis of the current pre-warm behavior found two distinct correction areas: runtime evidence is process-local and restart-sensitive, while `prewarmed_cache` is a one-row-per-title snapshot that cannot retain all release variants or truthful first-seen/provider-check history.
- The agreed title-level contract is: internal `unknown`; A when a complete successful bounded AD check finds zero cached variants; B when one or more exact variants are cached but none has fresh direct-play proof; C when at least one exact cached variant has fresh authoritative direct-play proof. MediaFlow is a separate per-variant delivery capability and never promotes B to C.
- The corrective sequence now has implemented [Block 5-5e](blocks/block-5-5e-durable-prewarm-runtime-ledger.md) and [Block 5-5f](blocks/block-5-5f-release-variant-availability-catalog.md), followed by planned [Block 5-5g](blocks/block-5-5g-catalog-population-provider-truth.md) and [Block 5-5h](blocks/block-5-5h-unified-availability-projection.md).
- Block 5-5c is revised to run after those prerequisites, accept one exact cached catalog variant, preserve verified direct play as the recommended path, record MediaFlow delivery evidence separately, and provide a minimal cached-version selector.

Next step:
- Review, commit, publish, and merge the corrected Block 5-5f without mixing 5-5g producer work or restarting the normal runtime first.
- After publication, separately authorize the bounded live cleanup of mismatched variants, restart/deploy the corrected runtime, and verify exact Odyssey catalog output.
- Then implement one block at a time in this order: 5-5g, 5-5h, 5-5c, 5-6, then 5-7.
- Use a dedicated feature branch for each implementation block.

Do-not-forget checks:
- A provider timeout, incomplete response, stale record, or absent check is `unknown`, never state A.
- Passive pre-warming may inspect already cached releases but must not create manual transfer ownership, download uncached media, produce transfer cards, or send completion notifications.
- `browser_stream_ready` and legacy `instant_cached` remain direct-play-only C aliases; MediaFlow results attach to exact variants without changing A/B/C.
- Preserve raw provider URL/magnet secrecy, canonical `tv_classic` domain identity, exact movie year, and explicit TV episode/season/pack scope.

## 2026-08-27

Current state:
- Block 5-5 is implemented and merged through PR #3; local `main` and `origin/main` are synchronized at merge commit `08e3720`.
- Chrome playback with audible, unmuted audio was operator-confirmed; browser decoded-sample telemetry was not captured and remains documented as a verification limitation.
- Block 5-5b is implemented with limitations on `codex/block-5-5b-mediaflow-capability-pilot`; its pilot decision is `adopt_with_bounded_adapter`.
- The branch contains fixture-first probe/decision/track/cleanup contracts, a localhost-only pinned Compose profile, focused tests, and a guarded fixture-only browser harness at `/mediaflow-pilot.html`. The pinned MediaFlow v2.4.9 container is healthy on `127.0.0.1:8888`. The client rejects unsafe/unverifiable HLS manifests and falls back to encrypted direct transcode, preserving URL/password secrecy. `NVIDIA_DRIVER_CAPABILITIES=compute,utility,video` is enabled and the NVENC HEVC transcode, operator playback/seek/source-switch/subtitle checks, and supplied log run passed. The vendor HLS child-URL leak remains bounded by the fallback; independently recorded reconnect, cleanup, bitmap-subtitle, HDR visual-quality, range, and browser decoded-sample evidence remain follow-up limitations.
- Block 5-5d is implemented on `codex/block-5-5d-universal-movie-quality-gate`: one shared fail-closed movie decision now gates discovery, search, ranking, pre-warming, cache preference, dry-run ranking, ingest, cloud pre-cache, and playback selection. Missing/invalid authoritative dates fail closed with `RELEASE_DATE_UNAVAILABLE`; post-window low-quality title markers are rejected as `LOW_QUALITY_SOURCE`; eligible candidates retain the existing ranking weights. No MediaFlow, provider, ranking-weight, migration, or live-state changes were made.
- Block 5-5d verification passed with 34 deterministic focused tests, 77 expanded movie/playback tests, and 359 full non-MCP tests; only the existing FastAPI/Discord deprecation warnings remain. Rejected discovery/search evidence is sanitized and non-actionable, while existing accepted browser records are not deleted or rewritten.
- Block 5-5c remains the next planned production browser-stream adapter; its rollout follows completed Block 5-5d so MediaFlow cannot make an ineligible movie playable or cacheable.

Next step:
- Review and integrate the completed [Block 5-5d](blocks/block-5-5d-universal-movie-quality-gate.md) branch; no live provider or AllDebrid smoke was run for this block.
- Then prepare and implement [Block 5-5c](blocks/block-5-5c-mediaflow-production-browser-adapter.md) on a dedicated branch; keep MediaFlow disabled by default until fixture-backed integration and security gates pass.
- Keep Block 5-6 and Block 5-7 unchanged while the production adapter is being qualified.

Do-not-forget checks:
- Keep MediaFlow localhost-only, authenticated, version-pinned, and unable to expose raw AllDebrid URLs or credentials.
- Prove NVENC, reconnect, seek, subtitle/audio selection, HDR handling, and process/segment cleanup; do not infer them from successful playback alone.
- Use deterministic local fixtures before any separately authorized live AllDebrid canary, and preserve local VLC fallback.

## 2026-08-26

Current State:
- **Phase 2 Complete**: All media intelligence blocks (2-1 through 2-12) implemented, verified, and merged.
- **Phase 3 Complete**: Conversational library RAG, AI user memory, external recommendations, persona settings, multi-user context, and Tautulli playback notifications implemented, verified, and merged.
- **Phase 4 (Stage 1: Interactive Foundation) COMPLETE**:
  - **Block 4-0 to 4-5**: All backend multi-domain infrastructure (router, Plex mirror, Prowlarr TV search, and download pipeline with 3-way routing) completed and verified.
- **Phase 5 (Stage 2: The Revamped Web UI Cockpit) COMPLETE**:
  - **Block 5-1 (Web UI Discovery Feeds, 3-Domain Switcher & Live Ingest Sidebar)**: Completed.
  - **Block 5-2 (Web UI Search & ⚡ Lightning Cache Badging)**: Completed.
  - **Block 5-3 (Web UI Ingestion Modals & Telemetry)**: Built 1-click movie downloads (`POST /api/ingest`), interactive TV season/episode picker checklist modal (`GET /api/tv/series-manifest`, `POST /api/tv/ingest-episodes`) with live Plex inventory cross-referencing, and floating bottom live SSE download telemetry dock (`/api/stream`). Completed and verified.
  - **Block 5-4 (3-Tier Media Lifecycle, Cloud Pre-Caching & Instant Streaming Player)**: Completed in the current feature branch, including cloud stream unlock, progress/history tracking, pre-caching, browser playback, and external-player launchers.
- **Stream readiness follow-up**: Implemented in the current worktree: authoritative pre-warm readiness for Discover, separate durable browser-stream and cached-download candidates per media record, browser-compatible cached-release selection for movies and TV, year-safe movie cache identity, resumable recent-to-1980 plus all-time-popularity movie pre-warm queues, and conservative browser audio/container gating.
- **Manual browser-copy follow-up**: Discovery keeps `Stream Now` disabled until verified and exposes `Cache Browser Copy` as an exact title/year browser-only acquisition path. Durable `cloud_transfer_intents` state limits Cloud Transfers and Notifications to manual Media Bot requests, while generic AllDebrid caching remains download-only and Search remains unrestricted.
- **Planned Phase 5 hardening sequence**: [Block 5-5](blocks/block-5-5-authoritative-browser-stream-verification.md) will use authoritative AD file evidence and bounded `ffprobe` fallback; [Block 5-6](blocks/block-5-6-adaptive-controlled-prewarming.md) will preserve existing frontiers while increasing movie throughput adaptively; [Block 5-7](blocks/block-5-7-browser-readiness-scoreboard-semantics.md) will make milestone progress count verified browser readiness. Implement and verify one block at a time in that order.
- **Verification**: 306 tests pass under Python 3.12 (excluding `tests/test_mcp_server.py`); only the existing 3 deprecation warnings remain.
- **Publication**: The foundation is committed as three scoped changes on `codex/stream-confirmation-gate`; keep `main` unchanged until this branch is separately reviewed and integrated.

---

## 3-Stage Master Implementation Plan

### Stage 1: Interactive Foundation (Backend Core for Web UI) — COMPLETED
1. **[Block 4-3: Discovery Engine & TMDb TV Extension](docs/blocks/block-4-3-discovery-engine-tmdb-tv.md)** (Completed)
2. **[Block 4-3b: TV & Classic TV Plex Library Sync & Mirror](docs/blocks/block-4-3b-tv-plex-library-sync.md)** (Completed)
3. **[Block 4-4: TV & Classic TV Prowlarr Search & Category Routing](docs/blocks/block-4-4-tv-search-category-routing.md)** (Completed)
4. **[Block 4-5: TV Episode Parsing & Download Pipeline](docs/blocks/block-4-5-tv-episode-parsing-download-pipeline.md)** (Completed)

### Stage 2: The Revamped Web UI Cockpit (Phase 5) — COMPLETED
5. **[Block 5-1: Web UI Discovery & 3-Domain Switcher](docs/blocks/block-5-1-web-ui-discovery-domain-switcher.md)** (Completed)
6. **[Block 5-2: Web UI Search & ⚡ Lightning Cache Badging](docs/blocks/block-5-2-web-ui-search-lightning-badges.md)** (Completed)
7. **[Block 5-3: Web UI Ingestion Modals & Telemetry](docs/blocks/block-5-3-web-ui-ingestion-modals-telemetry.md)** (Completed)
   - 1-click Movie grabs, TV season/episode picker checklist modal, and live floating SSE download telemetry dock.
8. **[Block 5-4: Web UI Instant Cloud Streaming & Media Player](docs/blocks/block-5-4-web-ui-instant-cloud-streaming.md)** (Completed)
   - In-browser video player modal (Plyr.js / Video.js) and 1-click desktop streaming launchers (VLC / Infuse / PotPlayer) for instant-cached AllDebrid releases.

### Stage 2A: Stream Readiness Hardening — PLANNED
9. **[Block 5-5: Authoritative Browser-Stream Verification](blocks/block-5-5-authoritative-browser-stream-verification.md)**
   - Inspect exact cached candidates using actual AD file evidence, bounded `ffprobe`, durable Search-to-Discovery promotion, and ownership-safe temporary cleanup.
10. **[Block 5-6: Adaptive Controlled Prewarming](blocks/block-5-6-adaptive-controlled-prewarming.md)**
   - Preserve all current vectors/cursors while adapting recent and all-time movie lanes between 10, 20, and 30 candidates.
11. **[Block 5-7: Browser-Readiness Scoreboard Semantics](blocks/block-5-7-browser-readiness-scoreboard-semantics.md)**
   - Keep existing milestone values but count only verified browser-ready records toward progress and frontier-to-go.

### Stage 3: Autonomous Background Engines (Post-UI Automation)
12. **[Block 4-6: TV Watchlist State & Storage](docs/blocks/block-4-6-tv-watchlist-storage.md)**
   - SQLite `tv_watchlist` repository (`watching`, `completed`, `archived`), `release_day` calendar schedules, and management tools.
13. **[Block 4-7: TV Mid-Season Backfill Engine](docs/blocks/block-4-7-tv-backfill-engine.md)**
    - Gap analysis using Plex episode inventory, full-backlog + granular per-episode backfill, reusable `resolve_missing_episodes` function, and dry-run safety.
14. **[Block 4-8: TV Airing Monitor & Auto-Archiving](docs/blocks/block-4-8-tv-airing-monitor.md)**
    - Autopilot sweep for newly aired episodes on broadcast days, automatic IDM queueing, finale detection, and auto-archiving.
15. **[Block 4-9: Weekly Release Discord Notifier & In-Line Ingest](docs/blocks/block-4-9-discord-weekly-digest.md)**
    - Discord digest reusing 4-3's discovery engine, interactive `⚡ Ingest` / `🚫 Ignore` buttons, and weekly cron.

---

### Staging Directories Reference
- **Movies**: `F:\_temp\movies` (`settings.output_dir`)
- **TV**: `F:\_temp\tv` (`settings.tv_output_dir`)
- **Classic TV**: `F:\temp\Classic TV` (`settings.tv_classic_output_dir`)

---

### Immediate Next Step for Resuming
- Confirm the remote `codex/stream-confirmation-gate` publication, then retain the branch for review. Live localhost API smoke passed after the PM2 restart; the in-app browser could not perform visual QA because its URL safety policy blocked localhost reload.
- Then implement **Block 5-5** only. Do not begin 5-6 until 5-5 passes its automated suite and ownership-guarded `Scary Movie` (2026) live canary; do not begin 5-7 until 5-6 is independently verified.
- After the Phase 5 hardening sequence is complete, **Block 4-6: TV Watchlist State & Storage** resumes as the next Stage 3 implementation block.
