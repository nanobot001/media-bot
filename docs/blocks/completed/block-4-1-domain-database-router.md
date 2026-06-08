# Block 4-1: Domain Database Router

> Status: Implemented on 2026-06-08.
> Result: Implemented.
> Verification: `pytest tests/test_domain_database_router.py -v` and `pytest` - passed.
> Notes: Configured per-domain SQLite DB paths in settings and routed connections and initializations safely, keeping backward compatibility.

## Goal

Add a small domain-aware database routing layer so future tools can choose the correct SQLite state file for `movies`, `anime`, `tv`, or `tv_classic`. Existing movie behavior must remain unchanged and existing movie tools should keep using the current database path unless explicitly routed otherwise.

## Scope

- Define canonical domain names: `movies`, `anime`, `tv`, and `tv_classic`.
- Add settings for per-domain SQLite paths with the current `database_path` remaining the movie default.
- Add a domain routing helper that returns the correct SQLite path/connection for a requested domain.
- Add validation for unknown domains with structured errors.
- Preserve existing `get_db_connection()` behavior for the movie baseline.
- Add focused tests proving that each domain resolves to the intended path and that movie compatibility remains intact.

## Out Of Scope

- Do not create anime, TV, or TV Classic schemas beyond minimal initialization needed by the router tests.
- Do not migrate existing movie data.
- Do not update all tools to accept a domain yet.
- Do not add Plex section mapping; that belongs to Block 4-2.

## Likely Files Or Areas

- `src/moviebot/config.py`
- `src/moviebot/db/connection.py`
- `tests/test_domain_database_router.py`
- `docs/tool-surface.md`
- `docs/tool-manifest.yaml`

## Acceptance Criteria

- `settings` exposes stable DB path configuration for all four domains.
- The router resolves `movies` to the existing movie DB path by default.
- Unknown domains fail with a structured, non-secret error.
- Existing movie tests using `get_db_connection()` continue to pass without passing a domain.
- Tool-facing docs mention the domain concept without removing existing movie tools.

## Verification

- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_domain_database_router.py -q`
- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_intelligence.py tests/test_mcp_server.py -q --basetemp data\\pytesttmp-domain-router`
