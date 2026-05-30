import re
import asyncio
from typing import Dict, Any, Optional, Tuple, List
from rapidfuzz import fuzz
from moviebot.adapters.plex_client import PlexClient
from moviebot.db.repositories import LibraryItemRepository, DownloadJobRepository, EventRepository
from moviebot.core.dedupe import normalize_title
from moviebot.config import settings


def extract_year(filename: str) -> Optional[int]:
    """Helper to extract a 4-digit year between 1900 and 2030 from a string."""
    matches = re.findall(r'\b(19\d{2}|20[0-2]\d|2030)\b', filename)
    if matches:
        return int(matches[-1])
    return None


def clean_title(title: str) -> str:
    """Removes noise, years, extensions, and common movie file tags."""
    t = title.lower()
    t = re.sub(r'\.(mkv|mp4|avi|srt)$', '', t)
    t = re.sub(r'\b(19\d{2}|20[0-2]\d|2030)\b.*$', '', t)
    t = re.sub(r'[\._\-:\(\)\[\]\{\}]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t



def check_mismatch(
    job_filename: str, 
    plex_title: str, 
    plex_year: Optional[int]
) -> Tuple[bool, float, Optional[int]]:
    """
    Compares the download job's filename with Plex's matched title and year.
    Returns (is_mismatch, similarity_score, job_year).
    """
    job_clean = clean_title(job_filename)
    plex_clean = clean_title(plex_title)
    
    job_year = extract_year(job_filename)
    
    score = fuzz.token_sort_ratio(job_clean, plex_clean)
    
    is_mismatch = False
    
    # Mismatch if years differ
    if job_year and plex_year and job_year != plex_year:
        is_mismatch = True
    # Mismatch if title similarity score is below 80
    elif score < 80:
        is_mismatch = True
        
    return is_mismatch, score, job_year


class MismatchGuard:
    def __init__(self, plex_client: Optional[PlexClient] = None):
        self.plex = plex_client or PlexClient()

    async def audit_plex_item(self, rating_key: str) -> Dict[str, Any]:
        """
        Audits a Plex library item by matching it to recent download jobs.
        If a mismatch is found, it attempts hybrid auto-correction.
        If auto-correction fails/isn't confident, it returns the conflict details for manual Discord remediation.
        """
        # 1. Fetch item details from Plex
        plex_item = await self.plex.fetch_movie_details(rating_key)
        if not plex_item:
            return {"status": "ignored", "reason": "Plex item details not found."}

        # 2. Get completed and downloading jobs
        all_jobs = DownloadJobRepository.get_all_jobs(limit=30)
        completed_jobs = [j for j in all_jobs if j.get("status") in ("completed", "downloaded")]
        
        if not completed_jobs:
            return {"status": "ignored", "reason": "No completed download jobs found."}

        # 3. Find the most likely download job corresponding to this file
        # We look for the job whose selected_file_name matches or is most similar to the Plex file path or title
        best_job = None
        best_mapping_score = 0.0

        plex_file_name = ""
        if plex_item.get("file_path"):
            # Extract actual filename
            plex_file_name = plex_item["file_path"].split('/')[-1].split('\\')[-1]

        for job in completed_jobs:
            job_file = job.get("selected_file_name") or ""
            if not job_file:
                continue

            # Compare Plex filename vs Job filename
            if plex_file_name:
                mapping_score = fuzz.token_sort_ratio(clean_title(plex_file_name), clean_title(job_file))
            else:
                mapping_score = fuzz.token_sort_ratio(clean_title(plex_item["title"]), clean_title(job_file))

            if mapping_score > best_mapping_score:
                best_mapping_score = mapping_score
                best_job = job

        # If best mapping score is too low, we can't reliably associate this Plex item to any download job
        if not best_job or best_mapping_score < 50:
            return {
                "status": "ignored",
                "reason": "Could not map Plex item to any recent download job.",
                "best_mapping_score": best_mapping_score
            }

        job_filename = best_job["selected_file_name"]
        is_mismatch, similarity, job_year = check_mismatch(
            job_filename=job_filename,
            plex_title=plex_item["title"],
            plex_year=plex_item["year"]
        )

        if not is_mismatch:
            return {
                "status": "correct",
                "job_id": best_job["id"],
                "plex_title": plex_item["title"],
                "similarity": similarity
            }

        # We have a mismatch! Let's try hybrid auto-correction first.
        auto_corrected = await self._attempt_auto_correction(rating_key, job_filename, job_year)
        if auto_corrected:
            # Sync metadata back to DB
            updated_item = await self.plex.fetch_movie_details(rating_key)
            if updated_item:
                LibraryItemRepository.upsert(
                    id=updated_item["id"],
                    source=updated_item["source"],
                    rating_key=updated_item["rating_key"],
                    title=updated_item["title"],
                    normalized_title=normalize_title(updated_item["title"]),
                    year=updated_item["year"],
                    imdb_id=updated_item["imdb_id"],
                    file_path=updated_item["file_path"],
                    size_bytes=updated_item["size_bytes"]
                )
            
            EventRepository.insert(
                event_type="mismatch_auto_correct",
                source="mismatch_guard",
                title=plex_item["title"],
                summary=f"Auto-corrected mismatch. Rematched '{plex_item['title']}' to expected title from job.",
                entity_type="movie",
                entity_id=rating_key,
                status="success"
            )
            return {
                "status": "auto_corrected",
                "job_id": best_job["id"],
                "old_title": plex_item["title"],
                "new_title": updated_item["title"] if updated_item else plex_item["title"]
            }

        # Auto-correction wasn't confident. Return conflict details for Discord manual review.
        return {
            "status": "mismatch_detected",
            "rating_key": rating_key,
            "job_id": best_job["id"],
            "job_filename": job_filename,
            "job_expected_title": clean_title(job_filename),
            "job_expected_year": job_year,
            "plex_matched_title": plex_item["title"],
            "plex_matched_year": plex_item["year"],
            "similarity": similarity
        }

    async def _attempt_auto_correction(
        self, 
        rating_key: str, 
        job_filename: str, 
        job_year: Optional[int]
    ) -> bool:
        """
        Queries Plex matches. If a candidate matches the expected title and year with high confidence,
        it programmatically rematches the Plex item.
        """
        expected_title_clean = clean_title(job_filename)
        
        # 1. Fetch potential matches from Plex search agent
        candidates = await self.plex.get_matches(rating_key)
        if not candidates:
            return False

        best_candidate = None
        best_score = 0.0

        for cand in candidates:
            cand_guid = cand.get("guid")
            cand_name = cand.get("name") or ""
            cand_year = cand.get("year")
            cand_plex_score = cand.get("score") or 0 # Plex search agent score

            if not cand_guid or not cand_name:
                continue

            # Compare clean expected title with candidate name
            sim_score = fuzz.token_sort_ratio(expected_title_clean, clean_title(cand_name))

            # Auto-match rules:
            # - Candidate must have a high Plex search score (>= 80)
            # - Similarity between expected title and candidate title must be very high (>= 90)
            # - Year must match if expected year is known
            if sim_score >= 90 and cand_plex_score >= 80:
                if not job_year or not cand_year or job_year == cand_year:
                    if sim_score > best_score:
                        best_score = sim_score
                        best_candidate = cand

        if best_candidate:
            # Break match first
            unmatch_ok = await self.plex.unmatch_item(rating_key)
            if not unmatch_ok:
                return False
            
            # Wait briefly to let Plex unmatch register
            await asyncio.sleep(1.0)

            # Match to correct GUID
            match_ok = await self.plex.match_item(
                rating_key=rating_key,
                guid=best_candidate["guid"],
                name=best_candidate["name"]
            )
            return match_ok

        return False
