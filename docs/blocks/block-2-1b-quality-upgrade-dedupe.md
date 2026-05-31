# Block 2-1b: Quality Upgrade-Aware Deduplication

> Status: Proposed
> Result: Pending
> Verification: Run `pytest tests/test_dedupe.py -k "test_quality_upgrade"`

## Goal
Allow intentional quality upgrades while preserving the existing duplicate-protection behavior for normal movie requests.

## Scope
* Refactor `evaluate_deduplication` in `moviebot/core/dedupe.py` to accept optional incoming quality context:
  * `incoming_resolution`
  * `incoming_size_bytes`
  * `incoming_bitrate_kbps`
* Compare incoming releases against stored `resolution`, `size_bytes`, and `bitrate_kbps` values from `library_items`.
* Return `action = "allow"` and `tier = "upgrade_eligible"` only when the incoming release is conservatively better than the owned copy.
* Preserve the normal duplicate block result when quality evidence is missing, ambiguous, or worse.
* Emit a meaningful local domain event when an owned title is allowed because it is upgrade-eligible.

## Out Of Scope
* Search result ranking changes.
* Discord UI changes.
* Embedding or recommendation behavior.

## Implementation Instructions
1. Add a small quality comparison helper rather than burying resolution and bitrate parsing in the dedupe control flow.
2. Treat resolution as a coarse signal and bitrate/size as secondary evidence. Avoid allowing upgrades solely because a release claims a higher resolution.
3. Keep the public JSON output stable and add the upgrade metadata under an additive `data` field.
4. Add focused tests for higher quality, same quality, lower quality, and missing quality evidence.

## Acceptance Criteria
* Ingesting a 2160p version of a movie when only a materially lower-quality 1080p copy exists returns `upgrade_eligible` instead of blocking.
* A low-bitrate or suspiciously small 2160p release does not bypass duplicate protection.
* Existing dedupe tests continue to pass unchanged unless they explicitly assert the new optional metadata.

## Verification Commands
```powershell
$env:PYTHONPATH="src"
pytest tests/test_dedupe.py -k "test_quality_upgrade"
pytest tests/test_dedupe.py
```
