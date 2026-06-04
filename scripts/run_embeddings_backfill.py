#!/usr/bin/env python3
"""
Python script to perform batch composite embedding backfill on library items.
Runs rate-limited calls to Gemini/Ollama to update search embeddings and hashes.
"""

import sys
import os
import argparse
import time
import asyncio
import traceback
import json
from pathlib import Path

# Add src directory to path to ensure moviebot can be imported
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from moviebot.db.connection import get_db_connection
from moviebot.db.repositories import LibraryItemRepository
from moviebot.core.embeddings import (
    build_composite_document,
    get_composite_document_hash,
    get_embedding_result,
    encode_vector,
    get_configured_model
)

def load_tags(val) -> list:
    if not val:
        return []
    if isinstance(val, list):
        return val
    try:
        parsed = json.loads(val)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass
    # If it's a comma-separated string, split it
    if isinstance(val, str) and "," in val:
        return [x.strip() for x in val.split(",") if x.strip()]
    return [val]

async def main():
    parser = argparse.ArgumentParser(description="Backfill composite search embeddings in media-bot database.")
    parser.add_argument("--limit", type=int, default=None, help="Max items to process in this run.")
    parser.add_argument("--delay", type=float, default=4.0, help="Delay in seconds between API calls to avoid rate limits.")
    parser.add_argument("--dry-run", action="store_true", help="Print actions but do not write to DB or fetch API embeddings.")
    parser.add_argument("--force", action="store_true", help="Force embedding regeneration for all matches even if hashes match.")
    parser.add_argument("--json", action="store_true", help="Output final summary as JSON.")
    args = parser.parse_args()

    # Load configured model
    configured_model = get_configured_model()
    
    if not args.json:
        mode_str = "[DRY-RUN]" if args.dry_run else "[REAL MODE]"
        print(f"=== Starting Composite Embeddings Backfill in {mode_str} ===")
        print(f"Configured embedding model: {configured_model}")
        print(f"API Delay: {args.delay} seconds")
        if args.limit:
            print(f"Limit: {args.limit} items")
        if args.force:
            print("Force flag is enabled: regenerating all embeddings.")

    # 1. Fetch library items
    try:
        with get_db_connection() as conn:
            cursor = conn.execute("SELECT id, title, year, genres, tone_tags, theme_tags, synopsis, synopsis_hash, synopsis_vector, synopsis_vector_model, synopsis_vector_dim FROM library_items WHERE source = 'plex'")
            items = [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        if args.json:
            print(json.dumps({"ok": False, "error": {"code": "DB_ERROR", "message": f"Failed to fetch library items: {str(e)}"}}))
        else:
            print(f"Error: Failed to fetch library items: {str(e)}", file=sys.stderr)
        sys.exit(1)

    if not items:
        if args.json:
            print(json.dumps({"ok": True, "data": {"processed": 0, "total": 0, "message": "No library items found."}}))
        else:
            print("No Plex library items found in local database.")
        sys.exit(0)

    # 2. Analyze which items need backfill
    candidates = []
    for item in items:
        # Load genres, tones, themes
        genres = load_tags(item.get("genres"))
        tones = load_tags(item.get("tone_tags"))
        themes = load_tags(item.get("theme_tags"))
        synopsis = item.get("synopsis") or ""

        # Build composite document
        composite_doc = build_composite_document(
            title=item.get("title") or "",
            year=item.get("year"),
            genres=genres,
            tones=tones,
            themes=themes,
            synopsis=synopsis
        )
        new_hash = get_composite_document_hash(composite_doc)

        existing_hash = item.get("synopsis_hash")
        existing_vector = item.get("synopsis_vector")
        existing_model = item.get("synopsis_vector_model")
        existing_dim = item.get("synopsis_vector_dim")

        needs_embedding = False
        reason = ""

        if args.force:
            needs_embedding = True
            reason = "Force flag specified"
        elif not existing_vector:
            needs_embedding = True
            reason = "No existing vector"
        elif existing_hash != new_hash:
            needs_embedding = True
            reason = f"Hash mismatch (old: {existing_hash[:8] if existing_hash else 'None'} vs new: {new_hash[:8]})"
        elif existing_model != configured_model:
            needs_embedding = True
            reason = f"Model changed (old: {existing_model} vs new: {configured_model})"
        elif existing_dim != 768:
            needs_embedding = True
            reason = f"Dimension mismatch (old: {existing_dim} vs new: 768)"

        if needs_embedding:
            candidates.append({
                "id": item["id"],
                "title": item["title"],
                "year": item["year"],
                "composite_doc": composite_doc,
                "new_hash": new_hash,
                "reason": reason,
                "genres": genres,
                "tones": tones,
                "themes": themes
            })

    total_candidates = len(candidates)
    if args.limit:
        candidates = candidates[:args.limit]
    
    to_process_count = len(candidates)

    if not args.json:
        print(f"Total Plex items in DB: {len(items)}")
        print(f"Items needing embedding update: {total_candidates}")
        print(f"Items to process in this run (limit applied): {to_process_count}")

    if to_process_count == 0:
        if args.json:
            print(json.dumps({"ok": True, "data": {"processed": 0, "total": len(items), "message": "All items are already up-to-date."}}))
        else:
            print("All items are already up-to-date. No work to do.")
        sys.exit(0)

    # 3. Process candidate items
    success_count = 0
    fail_count = 0
    skipped_count = 0
    processed_items = []

    for idx, cand in enumerate(candidates, 1):
        log_title = f"{cand['title']} ({cand['year'] or 'Unknown Year'})"
        if not args.json:
            print(f"[{idx}/{to_process_count}] Processing: {log_title}")
            print(f"  Reason: {cand['reason']}")
            # Show what is being added to the embedding:
            meta_parts = []
            if cand["genres"]:
                meta_parts.append(f"Genres: {', '.join(cand['genres'])}")
            if cand["tones"]:
                meta_parts.append(f"Tones: {', '.join(cand['tones'])}")
            if cand["themes"]:
                meta_parts.append(f"Themes: {', '.join(cand['themes'])}")
            
            meta_desc = " | ".join(meta_parts) if meta_parts else "No enriched tags"
            print(f"  Enrichment packaged: {meta_desc}")
            
            # Print a snippet of the composite document itself
            doc_preview = cand["composite_doc"].replace("\n", " ").strip()
            if len(doc_preview) > 120:
                doc_preview = doc_preview[:117] + "..."
            print(f"  Composite Preview:   \"{doc_preview}\"")

        if args.dry_run:
            if not args.json:
                print(f"  [DRY-RUN] Would fetch embedding for hash: {cand['new_hash'][:8]}")
            success_count += 1
            processed_items.append({
                "id": cand["id"],
                "title": cand["title"],
                "status": "dry-run",
                "reason": cand["reason"]
            })
            continue

        try:
            # Fetch embedding
            embedding_result = await get_embedding_result(cand["composite_doc"])
            
            # Save to database
            encoded = encode_vector(embedding_result.vector)
            LibraryItemRepository.update_vector_and_hash(
                id=cand["id"],
                synopsis_vector=encoded,
                synopsis_vector_model=embedding_result.model,
                synopsis_vector_dim=embedding_result.dim,
                synopsis_hash=cand["new_hash"]
            )
            
            success_count += 1
            processed_items.append({
                "id": cand["id"],
                "title": cand["title"],
                "status": "success",
                "model": embedding_result.model,
                "source": embedding_result.source,
                "fallback": embedding_result.fallback
            })
            
            if not args.json:
                fb_str = " (FALLBACK)" if embedding_result.fallback else ""
                print(f"  [OK] Saved composite embedding using {embedding_result.source}:{embedding_result.model}{fb_str}")

            # Sleep between requests if not the last item
            if idx < to_process_count and args.delay > 0:
                if not args.json:
                    print(f"  Sleeping for {args.delay}s...")
                await asyncio.sleep(args.delay)

        except Exception as err:
            fail_count += 1
            processed_items.append({
                "id": cand["id"],
                "title": cand["title"],
                "status": "failed",
                "error": str(err)
            })
            if not args.json:
                print(f"  [ERROR] Failed to generate/save embedding: {str(err)}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)

    # 4. Output Summary
    if args.json:
        print(json.dumps({
            "ok": True,
            "data": {
                "total_items": len(items),
                "needing_update": total_candidates,
                "limit_applied": args.limit,
                "processed": to_process_count,
                "success": success_count,
                "failed": fail_count,
                "model": configured_model,
                "items": processed_items
            }
        }))
    else:
        print("\n=== Backfill Summary ===")
        print(f"Total library items:  {len(items)}")
        print(f"Needing update:       {total_candidates}")
        print(f"Processed:            {to_process_count}")
        print(f"Success:              {success_count}")
        print(f"Failed:               {fail_count}")
        print("========================")

if __name__ == "__main__":
    asyncio.run(main())
