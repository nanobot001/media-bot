# Block 3-4: Multi-User Context & Privacy Guards

> Status: Planned.
> Notes: Implements multi-user thread history parsing with speaker identities, local privacy filters preventing cross-user history queries, and a consent-based shared session joining system for joint recommendations.

## Goal

Ensure the media-bot operates securely and transparently in shared Discord channels. Enable multi-turn conversations featuring multiple users, prevent users from snooping on other users' histories, and support collaborative recommendations where users must explicitly consent to merge their taste profiles.

## Scope

- **Multi-User History Construction:**
  - Update thread message parser to reconstruct context logs keeping track of speaker identities (e.g., `<User_1>`, `<User_2>`).
  - Anonymize usernames sent to Gemini (PII masking), and reconstruct the real mentions locally.
- **Privacy Interceptor:**
  - Build local deterministic validation checking if a user query targets another user's personal details (e.g. asking about another user's watch history).
  - Intercept and block unauthorized cross-user data requests *before* sending to the LLM.
- **Joint Consent Session:**
  - Create a joint recommendation flow where Bob asks: *"Suggest a movie Alice and I would like."*
  - The bot replies with a session invitation showing a `✅ Join Session` button for Alice.
  - Once Alice clicks the button, her watch history and taste profiles are temporarily merged into the RAG context for that recommendation.
- **Testing & Verification:**
  - Write integration tests simulating multi-user threads with correct speaker context.
  - Test local privacy blockers for cross-user queries.
  - Test shared session consent validation.

## Out Of Scope

- Persistent shared group watchlists.

## Likely Files Or Areas

- `src/moviebot/bot/discord_app.py`
- `src/moviebot/core/conversational_rag.py`
- `tests/test_multi_user_rag.py` [NEW]

## Acceptance Criteria

- Thread history accurately delineates who said what without leaking PII to Gemini.
- Asking about another user's history results in a local privacy rejection embed.
- Combined recommendations require both users to join the active session.
- All new tests pass.

## Verification

- `pytest tests/test_multi_user_rag.py` passes.
