from __future__ import annotations
import re
import logging
import datetime
from typing import Any, Optional, Dict, List, Tuple
import discord

from moviebot.config import settings
from moviebot.db.repositories import DownloadJobRepository, LibraryItemRepository, SearchResultRepository, KeyValueRepository
from moviebot.adapters.media_watcher_client import MediaWatcherClient
from moviebot.adapters.alldebrid_client import AllDebridClient
from moviebot.core.dedupe import normalize_title
from moviebot.adapters.plex_client import PlexClient

logger = logging.getLogger(__name__)


class PipelineStage:
    DEBRID = "debrid"
    DOWNLOADING = "downloading"
    IN_FOLDER = "in_folder"
    FILEBOT = "filebot"
    IN_PLEX = "in_plex"
    ERROR = "error"


class PipelineStatus:
    def __init__(
        self,
        job_id: str,
        stage: str,
        status_text: str,
        progress: Optional[float] = None,
        error_message: Optional[str] = None,
        file_name: Optional[str] = None,
        title: Optional[str] = None,
        year: Optional[int] = None,
        updated_at: Optional[str] = None,
        created_at: Optional[str] = None
    ) -> None:
        self.job_id = job_id
        self.stage = stage
        self.status_text = status_text
        self.progress = progress
        self.error_message = error_message
        self.file_name = file_name
        self.title = title
        self.year = year
        self.updated_at = updated_at or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"
        self.created_at = created_at


class PipelineStatusService:
    """Service to aggregate and compute pipeline statuses for download jobs."""

    def __init__(
        self,
        watcher_client: Optional[MediaWatcherClient] = None,
        alldebrid_client: Optional[AllDebridClient] = None,
        plex_client: Optional[PlexClient] = None
    ) -> None:
        self.watcher_client = watcher_client or MediaWatcherClient()
        self.alldebrid_client = alldebrid_client or AllDebridClient()
        self.plex_client = plex_client or PlexClient()

    def parse_title_year(self, name: str) -> Tuple[Optional[str], Optional[int]]:
        """Extracts title and year from a release name or file name."""
        if not name:
            return None, None
            
        # Try matching title and 4-digit year (e.g. Predator.Badlands.2025.1080p)
        match = re.search(r"^(.*?)[.(_ -]+(\d{4})[.(_ -]*", name)
        if match:
            title = match.group(1).replace(".", " ").replace("_", " ").strip()
            # Clean up double spaces or brackets
            title = re.sub(r"\s+", " ", title)
            try:
                year = int(match.group(2))
                if 1900 <= year <= 2100:
                    return title, year
                else:
                    return title, None
            except ValueError:
                pass
                
        # If no year found, just clean up dots and return
        cleaned_name = name
        if "." in name:
            cleaned_name = re.sub(r"\.[a-zA-Z0-9]{3,4}$", "", name)
        title = cleaned_name.replace(".", " ").replace("_", " ").strip()
        title = re.sub(r"\s+", " ", title)
        return title, None

    async def get_status(self, job_id: str) -> PipelineStatus:
        """Retrieves and computes the pipeline status of a download job."""
        job = DownloadJobRepository.get_job(job_id)
        if not job:
            raise ValueError(f"Job with ID {job_id} not found in database.")

        created_at = job.get("created_at")

        # 1. Fallback Plex Direct check (runs BEFORE raw status check so if Plex already matched it, we immediately return IN_PLEX stage)
        title, year = None, None
        search_res = SearchResultRepository.get_by_id(job_id)
        if search_res:
            title, year = self.parse_title_year(search_res.get("title", ""))

        selected_file_name = job.get("selected_file_name")
        if not title and selected_file_name:
            title, year = self.parse_title_year(selected_file_name)

        if not title and search_res:
            title, year = self.parse_title_year(search_res.get("query_string", ""))

        if title:
            norm = normalize_title(title)
            db_matches = LibraryItemRepository.search_by_normalized_title(norm)
            if year:
                db_matches = [m for m in db_matches if m.get("year") == year]

            if not db_matches:
                # Direct query Plex fallback
                try:
                    plex_matches = await self.plex_client.search_movie(title, year)
                    if plex_matches:
                        m = plex_matches[0]
                        LibraryItemRepository.upsert(
                            id=m["id"],
                            source=m["source"],
                            rating_key=m["rating_key"],
                            title=m["title"],
                            normalized_title=normalize_title(m["title"]),
                            year=m["year"],
                            imdb_id=m["imdb_id"],
                            file_path=m["file_path"],
                            size_bytes=m["size_bytes"],
                            genres=m.get("genres"),
                            directors=m.get("directors"),
                            studios=m.get("studios"),
                            writers=m.get("writers"),
                            producers=m.get("producers"),
                            cast=m.get("cast"),
                            countries=m.get("countries"),
                            content_rating=m.get("content_rating"),
                            audience_rating=m.get("audience_rating"),
                            tagline=m.get("tagline"),
                            originally_available_at=m.get("originally_available_at"),
                            labels=m.get("labels"),
                            rating=m.get("rating"),
                            runtime=m.get("runtime"),
                            collections=m.get("collections"),
                            resolution=m.get("resolution"),
                            bitrate_kbps=m.get("bitrate_kbps"),
                            watch_status=m.get("watch_status"),
                            watch_count=m.get("watch_count", 0),
                            last_watched_at=m.get("last_watched_at"),
                            synopsis=m.get("synopsis"),
                            synopsis_hash=m.get("synopsis_hash")
                        )
                except Exception as e:
                    logger.warning(f"Direct Plex search fallback failed for job {job_id}: {e}")

        # 2. Get raw status
        status = await self._get_status_raw(job_id)
        status.created_at = created_at

        # 3. Check for Plex refresh trigger
        # If watcher_status is processed, but it's not yet in Plex, trigger refresh once.
        watcher_status = "unknown"
        if selected_file_name:
            watcher_status, _ = self.watcher_client.get_file_status(selected_file_name)

        if watcher_status == "processed" and status.stage != PipelineStage.IN_PLEX:
            scan_key = f"plex_scan_triggered:{job_id}"
            if not KeyValueRepository.get(scan_key):
                try:
                    await self.plex_client.refresh_movie_sections()
                    KeyValueRepository.set(scan_key, "true")
                    logger.info(f"Triggered Plex library scan for job {job_id} after processed status.")
                except Exception as e:
                    logger.warning(f"Failed to trigger Plex scan for job {job_id}: {e}")

        return status

    async def _get_status_raw(self, job_id: str) -> PipelineStatus:
        """Retrieves and computes the pipeline status of a download job."""
        job = DownloadJobRepository.get_job(job_id)
        if not job:
            raise ValueError(f"Job with ID {job_id} not found in database.")

        status_val = job.get("status", "pending")
        selected_file_name = job.get("selected_file_name")
        magnet_id = job.get("alldebrid_magnet_id")
        
        # 1. Parse Title / Year
        title, year = None, None
        search_res = SearchResultRepository.get_by_id(job_id)
        if search_res:
            title, year = self.parse_title_year(search_res.get("title", ""))
        
        if not title and selected_file_name:
            title, year = self.parse_title_year(selected_file_name)
            
        if not title and search_res:
            title, year = self.parse_title_year(search_res.get("query_string", ""))

        # 2. Check if already matched in Plex
        if title:
            norm = normalize_title(title)
            db_matches = LibraryItemRepository.search_by_normalized_title(norm)
            if year:
                db_matches = [m for m in db_matches if m.get("year") == year]
            if db_matches:
                return PipelineStatus(
                    job_id=job_id,
                    stage=PipelineStage.IN_PLEX,
                    status_text="Successfully imported and matched in Plex Library.",
                    file_name=selected_file_name or db_matches[0].get("file_path"),
                    title=db_matches[0].get("title") or title,
                    year=db_matches[0].get("year") or year
                )

        # 3. Check Media Watcher state
        watcher_status = "unknown"
        watcher_err = None
        watcher_stable = False
        if selected_file_name:
            watcher_status, watcher_err = self.watcher_client.get_file_status(selected_file_name)
            # Find the active tracked file to get stable flag
            for tf in self.watcher_client.get_tracked_files():
                if tf.get("filename", "").lower() == selected_file_name.lower():
                    watcher_stable = tf.get("stable", False)
                    break

        # 4. Check DB status
        if status_val == "failed":
            return PipelineStatus(
                job_id=job_id,
                stage=PipelineStage.ERROR,
                status_text="Job failed.",
                error_message="Job was marked as failed in the database.",
                file_name=selected_file_name,
                title=title,
                year=year
            )

        if watcher_status == "failed":
            return PipelineStatus(
                job_id=job_id,
                stage=PipelineStage.ERROR,
                status_text="FileBot processing failed.",
                error_message=watcher_err or "FileBot process failed to rename or copy.",
                file_name=selected_file_name,
                title=title,
                year=year
            )

        # 5. Handle active/pending states
        if status_val == "requires_selection":
            return PipelineStatus(
                job_id=job_id,
                stage=PipelineStage.DEBRID,
                status_text="Waiting for file selection (multi-file torrent).",
                file_name=selected_file_name,
                title=title,
                year=year
            )

        if status_val == "pending":
            # Check AllDebrid magnet status for extra detail
            progress = None
            status_text = "Waiting for AllDebrid cache / torrent download."
            if magnet_id and magnet_id != "None":
                try:
                    ad_status = await self.alldebrid_client.get_magnet_status(magnet_id)
                    status_name = ad_status.get("status", "")
                    if status_name == "downloading":
                        progress = ad_status.get("progress", 0.0)
                        status_text = f"AllDebrid active download: {status_name.capitalize()}."
                    elif status_name == "ready":
                        status_text = "AllDebrid cached ready, transferring to IDM."
                    elif status_name == "error":
                        return PipelineStatus(
                            job_id=job_id,
                            stage=PipelineStage.ERROR,
                            status_text="AllDebrid processing failed.",
                            error_message=ad_status.get("error_str") or "Magnet download error.",
                            file_name=selected_file_name,
                            title=title,
                            year=year
                        )
                except Exception as e:
                    logger.warning(f"Error getting magnet status: {e}")
            return PipelineStatus(
                job_id=job_id,
                stage=PipelineStage.DEBRID,
                status_text=status_text,
                progress=progress,
                file_name=selected_file_name,
                title=title,
                year=year
            )

        if status_val == "downloading":
            # If watcher is already tracking, download to local is finished and it is in folder
            if watcher_status == "tracking":
                if watcher_stable:
                    return PipelineStatus(
                        job_id=job_id,
                        stage=PipelineStage.FILEBOT,
                        status_text="File is stable. Currently processing via FileBot.",
                        file_name=selected_file_name,
                        title=title,
                        year=year
                    )
                else:
                    return PipelineStatus(
                        job_id=job_id,
                        stage=PipelineStage.IN_FOLDER,
                        status_text="Download finished. File detected in intake, waiting to stabilize.",
                        file_name=selected_file_name,
                        title=title,
                        year=year
                    )
            elif watcher_status == "processed":
                return PipelineStatus(
                    job_id=job_id,
                    stage=PipelineStage.FILEBOT,
                    status_text="FileBot processing complete. Waiting for Plex library match.",
                    file_name=selected_file_name,
                    title=title,
                    year=year
                )
            else:
                # Active IDM downloading
                # In IDM downloading stage
                progress = None
                if magnet_id and magnet_id != "None":
                    try:
                        ad_status = await self.alldebrid_client.get_magnet_status(magnet_id)
                        if ad_status.get("status") == "downloading":
                            progress = ad_status.get("progress", 0.0)
                    except Exception:
                        pass
                return PipelineStatus(
                    job_id=job_id,
                    stage=PipelineStage.DOWNLOADING,
                    status_text="Actively downloading via IDM / AllDebrid.",
                    progress=progress,
                    file_name=selected_file_name,
                    title=title,
                    year=year
                )

        if status_val == "completed":
            # Mark completed in DB but shortcut Plex check failed
            if watcher_status == "tracking":
                if watcher_stable:
                    return PipelineStatus(
                        job_id=job_id,
                        stage=PipelineStage.FILEBOT,
                        status_text="File is stable. Currently processing via FileBot.",
                        file_name=selected_file_name,
                        title=title,
                        year=year
                    )
                else:
                    return PipelineStatus(
                        job_id=job_id,
                        stage=PipelineStage.IN_FOLDER,
                        status_text="Download finished. File detected in intake, waiting to stabilize.",
                        file_name=selected_file_name,
                        title=title,
                        year=year
                    )
            elif watcher_status == "processed":
                return PipelineStatus(
                    job_id=job_id,
                    stage=PipelineStage.FILEBOT,
                    status_text="FileBot processing complete. Waiting for Plex library match.",
                    file_name=selected_file_name,
                    title=title,
                    year=year
                )
            else:
                return PipelineStatus(
                    job_id=job_id,
                    stage=PipelineStage.FILEBOT,
                    status_text="Download finished. Waiting for media watcher to detect file.",
                    file_name=selected_file_name,
                    title=title,
                    year=year
                )

        return PipelineStatus(
            job_id=job_id,
            stage=PipelineStage.ERROR,
            status_text="Unknown status stage.",
            file_name=selected_file_name,
            title=title,
            year=year
        )


def create_status_embed(status: PipelineStatus) -> discord.Embed:
    """Generates a rich, premium status card embed for Discord."""
    title_display = f"{status.title} ({status.year})" if status.year else (status.title or "Unknown Media")
    
    # Stage Indicators
    stages = {
        "debrid": ("Debrid Cache", "⚪ Waiting"),
        "downloading": ("Downloading (IDM)", "⚪ Waiting"),
        "in_folder": ("Intake & Stabilize", "⚪ Waiting"),
        "filebot": ("FileBot Import", "⚪ Waiting"),
        "plex": ("Plex Library", "⚪ Waiting")
    }

    # Progress formatting
    prog_str = ""
    if status.progress is not None:
        filled = int(status.progress // 10)
        empty = 10 - filled
        prog_str = f" ({status.progress:.1f}% `[{'█' * filled}{'░' * empty}]`)"

    color = discord.Color.blue()
    
    if status.stage == PipelineStage.DEBRID:
        stages["debrid"] = ("Debrid Cache", "🟡 Active" + prog_str)
        color = discord.Color.gold()
    elif status.stage == PipelineStage.DOWNLOADING:
        stages["debrid"] = ("Debrid Cache", "🟢 Completed")
        stages["downloading"] = ("Downloading (IDM)", "🟡 Active" + prog_str)
        color = discord.Color.blue()
    elif status.stage == PipelineStage.IN_FOLDER:
        stages["debrid"] = ("Debrid Cache", "🟢 Completed")
        stages["downloading"] = ("Downloading (IDM)", "🟢 Completed")
        stages["in_folder"] = ("Intake & Stabilize", "🟡 Active")
        color = discord.Color.orange()
    elif status.stage == PipelineStage.FILEBOT:
        stages["debrid"] = ("Debrid Cache", "🟢 Completed")
        stages["downloading"] = ("Downloading (IDM)", "🟢 Completed")
        stages["in_folder"] = ("Intake & Stabilize", "🟢 Completed")
        stages["filebot"] = ("FileBot Import", "🟡 Active")
        color = discord.Color.purple()
    elif status.stage == PipelineStage.IN_PLEX:
        stages["debrid"] = ("Debrid Cache", "🟢 Completed")
        stages["downloading"] = ("Downloading (IDM)", "🟢 Completed")
        stages["in_folder"] = ("Intake & Stabilize", "🟢 Completed")
        stages["filebot"] = ("FileBot Import", "🟢 Completed")
        stages["plex"] = ("Plex Library", "🟢 Completed")
        color = discord.Color.green()
    elif status.stage == PipelineStage.ERROR:
        color = discord.Color.red()
        job = DownloadJobRepository.get_job(status.job_id)
        db_status = job.get("status", "") if job else ""
        if db_status == "failed":
            stages["downloading"] = ("Downloading (IDM)", "🔴 Failed")
        elif "FileBot" in (status.error_message or ""):
            stages["debrid"] = ("Debrid Cache", "🟢 Completed")
            stages["downloading"] = ("Downloading (IDM)", "🟢 Completed")
            stages["in_folder"] = ("Intake & Stabilize", "🟢 Completed")
            stages["filebot"] = ("FileBot Import", "🔴 Failed")
        else:
            stages["debrid"] = ("Debrid Cache", "🔴 Failed")

    # Format the vertical monospace table rows
    def format_stage_row(label: str, status_text: str) -> str:
        padded = label.ljust(18)
        return f"`{padded} |` {status_text}"

    rows = []
    for key, (label, val) in stages.items():
        rows.append(format_stage_row(label, val))

    # Calculate elapsed time and format ticks
    elapsed_display = ""
    if status.created_at:
        try:
            created_str = status.created_at.split(".")[0]
            dt = datetime.datetime.strptime(created_str, "%Y-%m-%d %H:%M:%S")
            now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            diff = now - dt
            seconds = int(diff.total_seconds())
            if seconds < 0:
                seconds = 0
            
            minutes = seconds // 60
            remaining_seconds = seconds % 60
            
            num_ticks = max(1, min(10, minutes + 1))
            ticks_str = "▰" * num_ticks
            
            if status.stage == PipelineStage.IN_PLEX:
                elapsed_display = format_stage_row("Elapsed Time", f"⏱️ Finished in {minutes}m {remaining_seconds}s")
            elif status.stage == PipelineStage.ERROR:
                elapsed_display = format_stage_row("Elapsed Time", f"⏱️ Failed after {minutes}m {remaining_seconds}s")
            else:
                elapsed_display = format_stage_row("Elapsed Time", f"⏱️ {minutes}m {remaining_seconds}s ({ticks_str})")
        except Exception as e:
            logger.warning(f"Error calculating elapsed time: {e}")

    table_content = "\n".join(rows)
    if elapsed_display:
        table_content += f"\n{elapsed_display}"

    # Build description with the stages table
    desc_text = (
        f"**Current Status:** {status.status_text}\n"
        f"{f'**Error Details:** `{status.error_message}`' if status.error_message else ''}\n\n"
        f"**Pipeline Stages:**\n"
        f"{table_content}"
    )

    # Construct the Embed
    embed = discord.Embed(
        title=f"⏳ Ingestion Pipeline: {title_display}",
        description=desc_text,
        color=color
    )
    
    if status.file_name:
        # Truncate long file names
        fn_display = status.file_name
        if len(fn_display) > 60:
            fn_display = fn_display[:28] + "..." + fn_display[-28:]
        embed.add_field(name="📦 Targeted File", value=f"`{fn_display}`", inline=False)

    # Empty field for layout alignment if needed (or just list updated_at)
    embed.set_footer(text=f"Job ID: {status.job_id} | Refreshed at: {status.updated_at.split('.')[0]}")
    return embed
