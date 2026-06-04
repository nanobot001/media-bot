# Block 2-5: Structured Enrichment Metadata

> Status: Implemented on 2026-05-31.
> Result: Implemented with limitations.
> Verification: `py -3.12 -m pytest tests/test_mcp_server.py tests/test_intelligence.py tests/test_discord_app.py::test_slash_library_success -q --basetemp data\pytesttmp` - passed (30 passed).
> Notes: Added structured metadata storage, deterministic evidence-backed enrichment, dry-run-safe `sync_enrichment`, structured query filters, and conservative content-warning exclusions. This first pass uses rule-based extraction rather than LLM JSON enrichment.

## Goal

Add a durable enrichment layer that defines what a movie is or is not across setting, premise, characters, themes, tone, craft, and content warnings. The outcome is a queryable metadata surface that prevents factual semantic-search misses such as loose matches for "takes place in Canada" while still supporting softer discovery queries like "warm family adventure" or "visually stylish sci-fi."

## Scope

- Add storage for structured enrichment metadata on library items, preserving existing vectors and FTS behavior.
- Lock the primary enrichment categories:
  - `setting`: locations, environment, time period, fictional/real world, setting scope.
  - `premise`: plot engine, central conflict, stakes, protagonist goal, premise tags.
  - `characters`: protagonist types, antagonist types, relationship focus, ensemble shape, occupation/archetype tags.
  - `themes`: social topics, philosophical topics, emotional core, moral/message tags.
  - `tone`: moods, intensity, pacing, humor style, comfort-watch fit.
  - `craft`: visual style, narrative structure, dialogue style, music style, effects/aesthetic tags.
  - `content_warnings`: warning tags and levels for violence, gore, sexual content, child/animal harm, self-harm, grief, addiction, hate speech, medical trauma, and other exclusions.
- Store the full model output in an `enrichment_json` payload and expose frequently queried helper fields such as `setting_locations`, `premise_tags`, `character_tags`, `theme_tags`, `tone_tags`, `craft_tags`, and `content_warning_tags`.
- Require `field_confidence_json` and `field_evidence_json` for extracted factual or safety-sensitive claims.
- Add a dry-run-safe enrichment command that can preview and then persist enrichment for a bounded number of library items.
- Ensure factual fields distinguish `unknown` from `none`, especially for content warnings and safety filters.
- Version the enrichment schema and prompt/model used with fields such as `enrichment_version`, `enrichment_model`, and `enrichment_updated_at`.

## Out Of Scope

- Building the full conversational RAG answer layer.
- Replacing existing `/library` semantic search behavior entirely.
- Treating LLM-inferred content warnings as authoritative without evidence, confidence, or manual override support.
- Adding destructive cleanup or deleting existing synopsis vectors.
- Implementing multi-user preference profiles or quotas.

## Likely Files Or Areas

- `src/moviebot/db/connection.py`
- `src/moviebot/db/repositories.py`
- `src/moviebot/cli/tool_cli.py`
- `src/moviebot/core/`
- `src/moviebot/tools/query_library_tool.py`
- `docs/tool-surface.md`
- `docs/tool-manifest.yaml`
- `tests/test_intelligence.py`

## Data Shape Guidance

Store category payloads inside `enrichment_json` using stable keys:

```json
{
  "setting": {
    "locations": ["Newfoundland", "Canada"],
    "environment": ["small town"],
    "time_period": ["September 2001"],
    "world_type": ["realistic"],
    "confidence": 0.92,
    "evidence": "Synopsis says passengers are stranded in a small town in Newfoundland."
  },
  "premise": {
    "plot_engine": ["stranded travelers", "community response"],
    "stakes": ["emotional survival"],
    "tags": ["9/11 aftermath", "unexpected hospitality"]
  },
  "characters": {
    "protagonist_types": ["travelers", "town residents"],
    "relationship_focus": ["strangers helping strangers", "community"]
  },
  "themes": {
    "values": ["grief", "resilience", "kindness", "belonging"]
  },
  "tone": {
    "values": ["warm", "hopeful", "bittersweet"]
  },
  "craft": {
    "narrative_structure": ["stage musical recording"],
    "music_style": ["musical theatre"]
  },
  "content_warnings": {
    "violence": {
      "level": "unknown",
      "confidence": 0.0,
      "evidence": null
    },
    "grief": {
      "level": "moderate",
      "confidence": 0.7,
      "evidence": "The synopsis references the aftermath of 9/11."
    }
  }
}
```

Content warning levels should use:

```text
none | mild | moderate | strong | extreme | unknown
```

For factual and sensitive fields, `unknown` must not be treated as `none`.

## Acceptance Criteria

- SQLite migration adds enrichment storage and searchable helper columns without losing existing library item data.
- The enrichment command supports dry-run by default and only writes when explicitly requested.
- Enrichment output records schema version, model/prompt identity, update timestamp, confidence, and evidence.
- Query routing can use structured helper fields for factual phrases such as "takes place in Canada" before falling back to vector similarity.
- Content warning exclusions can filter results conservatively, with configurable treatment for `unknown`.
- Public-read tool output does not expose file paths, secrets, raw prompts with private paths, or sensitive local details.
- Existing `/library`, `query-library`, recommendation, FTS, and vector tests still pass.

## Verification

```powershell
$env:PYTHONPATH="src"
py -3.12 -m moviebot.cli.tool_cli sync-intelligence --help
py -3.12 -m moviebot.cli.tool_cli query-library --semantic-query "takes place in Canada" --limit 10 --json
py -3.12 -m pytest tests/test_intelligence.py
```
