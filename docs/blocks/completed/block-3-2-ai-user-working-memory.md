# Block 3-2: AI User Working Memory & Plex Mapping

> Status: Implemented on 2026-06-05.
> Result: Implemented.
> Verification: `pytest tests/test_discord_app.py` and `pytest tests/test_user_profile.py` - passed.
> Notes: Implemented user profiles, Plex claim locking, taste modals, organic memory extraction, and conversational RAG tailoring based on active preferences.

## Goal

Introduce user-aware memory to the media-bot. The bot will identify the user asking a question, link their Discord identity to their Plex/Tautulli watch profile, log their recent questions to form a rolling taste profile, and customize conversational RAG search results accordingly.

## Scope

- **Database Enhancements:**
  - Add a `user_profiles` table mapping Discord User IDs to Plex usernames, containing an LLM-compiled `taste_summary`, `explicit_interests` (JSON list), `explicit_disinterests` (JSON list), `custom_taste_notes` (TEXT), and configuration preferences.
  - Add a `user_interaction_memory` table logging recent conversational inputs and outputs per Discord user.
  - Apply claim locking (first-come, first-served) to prevent unauthorized Plex account hijacking.
  - Implement rolling TTL: prune query logs to retain only the last 30 entries per user.
- **Core Memory & Profiling Logic:**
  - Implement a `UserMemoryManager` to build user taste profiles by aggregating Tautulli watch history (favorite genres, directors, watch history), explicit preferences, and query history.
  - Implement **Organic Memory Extraction**: Detect natural language declarations of taste (e.g., *"Remember that I love Canadian movies"* or *"I hate horror"*) during conversational RAG queries, update the user profile's `taste_summary` database record, and output a confirmation to the user.
  - Dynamically retrieve the active user's taste summary and explicit taste preferences, injecting them into conversational RAG prompts.
- **Discord Presentation Layer:**
  - Implement the `/profile` slash command to display user profile details.
  - Add interactive button inputs to the `/profile` command:
    - `✏️ Edit Plex Username`: Opens a Discord modal (`EditPlexModal`) for self-service Plex handle linking.
    - `🎭 Edit Taste Preferences`: Opens a Discord modal (`EditTasteModal`) with fields to edit explicit interests, disinterests, and custom taste notes.
    - `🧠 Toggle Memory`: Turns interaction history logging ON or OFF.
    - `🗑️ Reset Memory`: Purges all query logs for the user.
  - Implement administrator-only command capabilities to link or unlink users.
  - Implement rate limiting (e.g. max 5 queries per user per minute).
- **Testing & Verification:**
  - Unit tests to verify database profile management, claim locking, and rolling interaction TTL.
  - Integration tests verifying conversational RAG uses the active user's watch history and taste.

## Out Of Scope

- Multi-user thread history parsing or cross-user context (moved to Block 3-4).
- Suggesting external movies not in the local database or displaying `🔍 Search & Add` buttons (moved to Block 3-3).

## Likely Files Or Areas

- `src/moviebot/db/connection.py`
- `src/moviebot/db/user_profile_repository.py` [NEW]
- `src/moviebot/core/user_memory_manager.py` [NEW]
- `src/moviebot/core/conversational_rag.py`
- `src/moviebot/bot/discord_app.py`
- `tests/test_user_profile.py` [NEW]

## Acceptance Criteria

- Running `/profile` displays the profile embed with buttons to edit username, edit taste preferences, toggle memory, and reset memory.
- Attempting to claim a Plex username that is already linked to another Discord user displays a lock error.
- Clicking `✏️ Edit Plex Username` opens a Modal input, and submitting it successfully updates the database.
- Clicking `🎭 Edit Taste Preferences` opens a Modal with fields for interests, disinterests, and custom taste notes, and submitting updates the user profile database.
- Typing natural language declarations (e.g. *"Remember that I love Canadian movies"*) successfully triggers a taste profile update, saves it to the database, and returns a confirmation to the user.
- `/ask` queries utilize the user's Plex watch history, explicit interests/disinterests, and custom taste notes to tailor results (e.g. downranking or upranking recommendations).
- All new tests pass.

## Verification

- `pytest tests/test_user_profile.py` passes.
