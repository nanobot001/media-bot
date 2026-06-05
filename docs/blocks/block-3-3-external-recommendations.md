# Block 3-3: External Parametric Recommendations & Search Integration

> Status: Implemented on 2026-06-05.
> Result: Implemented.
> Verification: `py -3.12 -m pytest tests/test_external_recommendations.py -q` - passed.
> Notes: Added external recommendation parsing, TMDb content gating, strict title sanitization, and Discord Search & Add confirmation before indexer search.

## Goal

Extend the bot's intelligence to handle questions about movies *not* in the local database. Allow the bot to suggest additions using its parametric knowledge, verify the safety/age-appropriateness of those suggestions, and provide immediate buttons for users to search, resolve, and add those movies to their downloads.

## Scope

- **Core RAG Extensions:**
  - Update system prompts to allow and format external suggestions when asked for additions (e.g., `[External Recommendation: Title (Year)]`).
  - Restrict general non-movie queries (domain lock: refuse non-media queries).
- **Safety & Content Gate:**
  - Implement a check against TMDb API or local metadata to verify the age rating/content warnings of suggested external movies before displaying them.
  - Exclude external recommendations that violate the active user's profile rating/genre filters.
- **Search & Add Button Flow:**
  - Sanitize the recommended movie title using strict regex to prevent command or query injections.
  - Display `🔍 Search & Add: [Title]` buttons next to cited movies for any external suggestions.
  - When clicked, present a confirmation step (e.g., interactive Yes/No buttons) to prevent accidental execution from errant button presses.
  - Upon user confirmation, trigger the Prowlarr/AllDebrid search flow and display matching magnets/torrents directly within the thread.
- **Testing & Verification:**
  - Mock TMDb API calls and test content gate filtration.
  - Write unit/integration tests verifying title parsing and regex sanitization.

## Out Of Scope

- Shared/multi-user recommendations and thread context (moved to Block 3-4).

## Likely Files Or Areas

- `src/moviebot/core/conversational_rag.py`
- `src/moviebot/bot/discord_app.py`
- `tests/test_external_recommendations.py` [NEW]

## Acceptance Criteria

- Asking the bot what to add next results in external movie suggestions.
- Mature or excluded content recommendations are filtered out by the TMDb content gate.
- Alphanumeric-only sanitization is applied to titles before search query execution.
- Clicking `🔍 Search & Add` prompts the user for confirmation (e.g., interactive Yes/No buttons).
- Confirming the prompt triggers the search and opens the result panel in the thread, while cancelling aborts the flow.

## Verification

- `pytest tests/test_external_recommendations.py` passes.
