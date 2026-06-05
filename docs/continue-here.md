# Continue Here

## 2026-06-04

Current State:
- **Phase 2 Complete**: All media intelligence blocks (2-1 through 2-12) have been successfully implemented, verified, and merged.
  - **Block 2-1 (Media Intelligence Schema & FTS5)**: Added 17 new columns to `library_items` table and FTS5 search indexing.
  - **Block 2-1b (Quality Upgrade Deduplication)**: Added quality-upgrade logic while maintaining duplicate protection.
  - **Block 2-2 (Vector Embedding & Similarity Engine)**: Setup Gemini API embedding integration with cache.
  - **Block 2-3 (Taste Recommender & Collection Audit)**: Developed personalized movie recommendations based on Tautulli watch history and franchise series gap analysis.
  - **Block 2-4 (Unified Discord & MCP Interface)**: Deployed `/library`, `/recommend`, and `/audit` Discord commands and exposed them as MCP tools.
  - **Block 2-5 & 2-6 (Structured/Typed Enrichment Metadata)**: Implemented structured settings, themes, tones, craft facets, and content-warning metadata.
  - **Block 2-7 (Gemini Enrichment Source)**: Added optional automated LLM-based metadata generation with rules-based fallback.
  - **Block 2-8 & 2-9 (Plex & Hard-Fact Discovery)**: Sourced credits, awards, source material, cultural impact, and popularity facts.
  - **Block 2-10 (Authority-Backed Hard-Fact Population)**: Built dry-run-first Wikidata/Gemini population pipeline for hard facts.
  - **Block 2-11 (TMDb Franchise & Brand Enrichment)**: Sourced canonical franchise/universe names and resolved aliases.
  - **Block 2-12 (Enriched Search Embeddings & Backfill)**: Migrated to metadata-enriched composite search embeddings, resolving descriptive/subjective search false positives. Activated and verified the subjective search regression harness.
- **Tidy Blocks Layout**: Moved all completed Phase 2 block files into `docs/blocks/completed/` directory.
- **Verification**: Clean run of the test suite (150/150 pytest tests passing successfully).

- **Phase 3: Conversational Library RAG & Ask Command**:
  - **Block 3-0 (RAG Infrastructure & Caching)**: Completed the unified Gemini API completion client with exponential backoff retry and DB error logging, token-efficient metadata minifier, and thread-safe async TTL cache.
  - **Block 3-1 (Conversational Library RAG & Ask Command)**: Exposed conversational search via developer CLI subcommand `ask`, FastMCP server tool `ask_library`, and Discord slash command `/ask` with citations. Completed full testing & verification.
  - **Block 3-2 (AI User Working Memory & Plex Mapping)**: Implemented `/profile` commands, Plex username mapping with claim locking, taste modals, organic memory extraction, and conversational RAG tailoring based on active preferences. Completed full testing & verification (all 179 tests pass).

Do-not-forget checks:
- Maintain rate limits when querying Gemini and TMDb APIs.
- Keep in-memory caches active to optimize vector similarity query times.
- Ensure the Docker-to-host bridge routing via `host.docker.internal` remains active.
