# Block 4-2: Plex Section Domain Mapping

> Status: Complete.
> Result: Implemented Plex section-to-domain mapping, preview command, FastMCP endpoint, and regression tests.
> Notes: Maps Plex library sections to media domains before anime sync work begins.

## Goal

Let operators map Plex sections to `movies`, `anime`, `tv`, and `tv_classic` so sync logic can route media into the correct domain database. This block should prepare the sync boundary without implementing full anime/TV schemas.

## Scope

- Add configuration for Plex section-to-domain mapping by section title and/or section key.
- Preserve `ignored_plex_sections` behavior.
- Add a Plex section discovery helper that reports section title, key, Plex type, and inferred/configured domain.
- Add a dry-run sync preview that shows where each Plex section would route without writing library rows.
- Record a structured event only for non-dry-run administrative mapping/sync actions, if any are introduced.
- Update docs/tool manifest entries only as needed to describe the mapping or preview command.

## Out Of Scope

- Do not implement anime show/episode persistence; that belongs to Block 5-1.
- Do not change existing movie library sync semantics except to keep movie sections routed to the movie domain.
- Do not add Prowlarr category routing or download changes.
- Do not expose private file paths, Plex tokens, or raw sensitive payloads in public-read outputs.

## Likely Files Or Areas

- `src/moviebot/config.py`
- `src/moviebot/adapters/plex_client.py`
- `src/moviebot/cli/tool_cli.py`
- `src/moviebot/tools/`
- `tests/test_plex_domain_mapping.py`

## Acceptance Criteria

- Plex sections can be mapped to `movies`, `anime`, `tv`, or `tv_classic`.
- A dry-run preview returns structured JSON showing section keys/titles and target domains.
- Existing movie section discovery and sync tests still pass.
- Ignored Plex sections remain ignored even if a mapping would otherwise match.
- Public-read preview output does not expose secrets or private local media paths.

## Verification

- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_plex_domain_mapping.py -q`
- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_plex_client.py tests/test_discord_app.py -q --basetemp data\\pytesttmp-plex-domain`
