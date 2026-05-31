import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import uuid
import json
import hashlib
from moviebot.config import settings
from moviebot.tools.search_library_tool import search_library_tool
from moviebot.tools.dedupe_check_tool import dedupe_check_tool
from moviebot.tools.search_sources_tool import search_sources_tool
from moviebot.tools.enqueue_download_tool import enqueue_download_tool
from moviebot.tools.query_watch_history_tool import query_watch_history_tool
from moviebot.db.connection import init_db
from moviebot.adapters.plex_client import PlexClient
from moviebot.db.repositories import LibraryItemRepository, SearchResultRepository, ErrorLogRepository
from moviebot.core.dedupe import normalize_title
import traceback
from discord.ext import tasks
from moviebot.tools.get_download_jobs_tool import get_download_jobs_tool
from moviebot.tools.resolve_pending_jobs_tool import resolve_pending_jobs_tool
from moviebot.tools.get_error_logs_tool import get_error_logs_tool
from moviebot.tools.check_movie_state_tool import check_movie_state_tool
from moviebot.tools.get_system_health_tool import get_system_health_tool
from moviebot.tools.get_recent_events_tool import get_recent_events_tool
from moviebot.tools.tail_logs_tool import tail_logs_tool
from moviebot.tools.query_library_tool import query_library_tool
from moviebot.tools.recommend_movies_tool import recommend_movies_tool
from moviebot.tools.audit_collections_tool import audit_collections_tool
from typing import Literal, Optional, Dict, Any
from moviebot.core.pipeline_status import PipelineStatusService, create_status_embed


class PipelineStatusView(discord.ui.View):
    """View with a Refresh button for the ingestion pipeline status card."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, custom_id="pipeline_status_refresh")
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        embed = interaction.message.embeds[0]
        footer_text = embed.footer.text if embed.footer else ""
        if "Job ID: " not in footer_text:
            await interaction.followup.send("❌ Could not resolve Job ID from status card.", ephemeral=True)
            return

        parts = footer_text.split(" | ")
        job_id = parts[0].replace("Job ID: ", "").strip()

        try:
            service = PipelineStatusService()
            status = await service.get_status(job_id)
            new_embed = create_status_embed(status)
            await interaction.message.edit(embed=new_embed, view=self)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to refresh status: {str(e)}", ephemeral=True)


class MovieBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Register commands to guild if configured (speeds up local command sync)
        if settings.discord_guild_id:
            guild = discord.Object(id=settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"[Bot] Commands synced to guild: {settings.discord_guild_id}")
        else:
            await self.tree.sync()
            print("[Bot] Commands synced globally.")

        # Register persistent views
        self.add_view(PipelineStatusView())

        # Configure and start background resolver loop
        self.auto_resolve_pending_loop.change_interval(seconds=settings.job_resolver_poll_interval)
        self.auto_resolve_pending_loop.start()

    @tasks.loop(seconds=60)
    async def auto_resolve_pending_loop(self):
        try:
            print("[Background Resolver] Starting auto-resolution sweep...")
            res = await resolve_pending_jobs_tool(dry_run=False)
            if res["ok"]:
                data = res["data"]
                resolved = data.get("resolved", [])
                ambiguous = data.get("ambiguous_requires_selection", [])
                failed = data.get("failed", [])
                if resolved or ambiguous or failed:
                    print(f"[Background Resolver] Sweep completed: {len(resolved)} resolved, {len(ambiguous)} require selection, {len(failed)} failed.")
            else:
                print(f"[Background Resolver Warning] Sweep failed: {res.get('error', {}).get('message')}")
        except Exception as e:
            print(f"[Background Resolver Error] Unhandled exception: {str(e)}")

        try:
            await self.sweep_and_update_status_cards()
        except Exception as e:
            print(f"[Background Resolver Error] Status card update sweep failed: {str(e)}")

    async def sweep_and_update_status_cards(self):
        """
        Queries all active status cards and updates them in place.
        """
        from moviebot.db.connection import get_db_connection
        active_jobs = []
        with get_db_connection() as conn:
            cursor = conn.execute(
                "SELECT id, discord_message_id FROM download_jobs WHERE discord_message_id IS NOT NULL AND discord_message_id NOT LIKE 'done:%'"
            )
            active_jobs = [dict(row) for row in cursor.fetchall()]
            
        if not active_jobs:
            return
            
        print(f"[Background Resolver] Sweeping status cards for {len(active_jobs)} active jobs...")
        
        service = PipelineStatusService()
        view = PipelineStatusView()
        
        for job_info in active_jobs:
            job_id = job_info["id"]
            msg_id_str = job_info["discord_message_id"]
            try:
                msg_id = int(msg_id_str)
            except ValueError:
                from moviebot.db.repositories import DownloadJobRepository
                DownloadJobRepository.update_discord_message_id(job_id, f"done:{msg_id_str}")
                continue
                
            try:
                status = await service.get_status(job_id)
                embed = create_status_embed(status)
                
                success = await find_and_edit_status_message(self, msg_id, embed, view)
                if not success:
                    print(f"[Background Resolver] Could not find status card message {msg_id} for job {job_id}.")
                    from moviebot.db.repositories import DownloadJobRepository
                    DownloadJobRepository.update_discord_message_id(job_id, f"done:{msg_id_str}")
                    continue
                
                from moviebot.core.pipeline_status import PipelineStage
                if status.stage in (PipelineStage.IN_PLEX, PipelineStage.ERROR):
                    from moviebot.db.repositories import DownloadJobRepository
                    DownloadJobRepository.update_discord_message_id(job_id, f"done:{msg_id_str}")
                    print(f"[Background Resolver] Job {job_id} reached terminal stage {status.stage}. Marked status card as done.")
            except Exception as e:
                print(f"[Background Resolver] Error updating status card for job {job_id}: {e}")

    @auto_resolve_pending_loop.before_loop
    async def before_auto_resolve_pending_loop(self):
        await self.wait_until_ready()


bot = MovieBot()


async def channel_check_predicate(interaction: discord.Interaction) -> bool:
    allowed_channels = settings.allowed_channels_list
    if not allowed_channels:
        return True
    if interaction.channel_id in allowed_channels:
        return True

    embed = discord.Embed(
        title="🚫 Access Restricted",
        description=(
            f"This command cannot be used in <#{interaction.channel_id}>.\n"
            f"Please run it in one of the allowed channels: "
            f"{', '.join(f'<#{cid}>' for cid in allowed_channels)}."
        ),
        color=discord.Color.red()
    )
    if not interaction.response.is_done():
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(embed=embed, ephemeral=True)
    return False


def in_allowed_channel():
    return app_commands.check(channel_check_predicate)


def is_bot_manager(interaction: discord.Interaction) -> bool:
    """
    Checks if the user invoking the interaction is authorized as a bot manager.
    """
    user_id = interaction.user.id
    manager_users = settings.bot_manager_users_list
    manager_roles = settings.bot_manager_roles_list

    # 1. Check user ID
    if user_id in manager_users:
        return True

    # 2. Check roles
    if hasattr(interaction.user, "roles"):
        member_role_ids = [r.id for r in interaction.user.roles]
        if any(rid in manager_roles for rid in member_role_ids):
            return True

    # 3. Fallback check: ManageGuild permission if no lists configured
    if not manager_users and not manager_roles:
        permissions = interaction.permissions
        if permissions and permissions.manage_guild:
            return True

    return False


def is_bot_manager_check():
    async def predicate(interaction: discord.Interaction) -> bool:
        if is_bot_manager(interaction):
            return True

        embed = discord.Embed(
            title="🚫 Access Restricted",
            description="You do not have the required Bot Manager permissions to execute this command.",
            color=discord.Color.red()
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)
        return False

    return app_commands.check(predicate)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        return

    # Extract original exception if wrapped
    cause = getattr(error, "original", None) or error.__cause__ or error
    tb_str = "".join(traceback.format_exception(type(cause), cause, cause.__traceback__))

    command_name = interaction.command.name if interaction.command else "unknown"
    user_id = str(interaction.user.id)
    user_name = interaction.user.name
    error_msg = str(cause)

    # Log to database
    try:
        ErrorLogRepository.insert(
            command_name=command_name,
            user_id=user_id,
            user_name=user_name,
            error_message=error_msg,
            stack_trace=tb_str
        )
        ErrorLogRepository.prune(max_errors=500)
    except Exception as db_err:
        print(f"[Error Logging Failed] SQLite write failed: {str(db_err)}")

    # Ephemeral message to user
    embed_user = discord.Embed(
        title="❌ Execution Error",
        description="An unexpected error occurred while executing this command. The issue has been logged.",
        color=discord.Color.red()
    )
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed_user, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed_user, ephemeral=True)
    except Exception:
        pass

    # Send admin warning embed
    if settings.discord_error_channel_id:
        try:
            error_channel = bot.get_channel(settings.discord_error_channel_id)
            if not error_channel:
                error_channel = await bot.fetch_channel(settings.discord_error_channel_id)

            if error_channel:
                embed_admin = discord.Embed(
                    title="⚠️ Command Runtime Exception Logged",
                    description=f"**Command:** `/{command_name}`\n**User:** {user_name} ({user_id})\n**Channel:** <#{interaction.channel_id}>",
                    color=discord.Color.dark_red()
                )
                embed_admin.add_field(name="Error Message", value=f"`{error_msg[:1000]}`", inline=False)
                tb_truncated = tb_str[:1000]
                if len(tb_str) > 1000:
                    tb_truncated += "\n... (truncated)"
                embed_admin.add_field(name="Traceback", value=f"```python\n{tb_truncated}```", inline=False)

                await error_channel.send(embed=embed_admin)
        except Exception as alert_err:
            print(f"[Error Logging Failed] Admin Discord notification failed: {str(alert_err)}")



async def post_pipeline_status_card(interaction: discord.Interaction, job_id: str):
    """
    Sends the initial status card embed to a channel, and stores the message ID in the DB.
    """
    try:
        from moviebot.core.pipeline_status import PipelineStatusService, create_status_embed
        from moviebot.db.repositories import DownloadJobRepository
        service = PipelineStatusService()
        status = await service.get_status(job_id)
        embed = create_status_embed(status)
        view = PipelineStatusView()
        
        # Send message to the interaction's channel to make it public
        msg = await interaction.channel.send(embed=embed, view=view)
            
        # Update the download job record with the message ID
        DownloadJobRepository.update_discord_message_id(job_id, str(msg.id))
    except Exception as e:
        print(f"[Bot] Error posting initial pipeline status card: {e}")
        try:
            ErrorLogRepository.insert(
                command_name="post_pipeline_status_card",
                user_id=str(interaction.user.id),
                user_name=interaction.user.name,
                error_message=f"Failed to post pipeline status card: {str(e)}",
                stack_trace=traceback.format_exc()
            )
        except Exception:
            pass


async def find_and_edit_status_message(bot, discord_message_id: int, embed: discord.Embed, view: discord.ui.View):
    """
    Attempts to find a Discord message by ID across channels and edits it.
    """
    channel_ids = list(settings.allowed_channels_list)
    
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.id not in channel_ids:
                channel_ids.append(channel.id)
                
    for channel_id in channel_ids:
        try:
            channel = bot.get_channel(channel_id)
            if not channel:
                channel = await bot.fetch_channel(channel_id)
            
            if channel:
                message = await channel.fetch_message(discord_message_id)
                if message:
                    await message.edit(embed=embed, view=view)
                    return True
        except discord.NotFound:
            continue
        except Exception as e:
            print(f"[Bot] Error searching channel {channel_id} for message {discord_message_id}: {e}")
            continue
            
    return False


class StatusDropdown(discord.ui.Select):
    def __init__(self, options: list):
        super().__init__(placeholder="Select a job to view status...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        job_id = self.values[0]
        try:
            service = PipelineStatusService()
            status = await service.get_status(job_id)
            embed = create_status_embed(status)
            view = PipelineStatusView()
            await interaction.edit_original_response(content=None, embed=embed, view=view)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to fetch status: {str(e)}", ephemeral=True)


class StatusSelectView(discord.ui.View):
    def __init__(self, jobs: list):
        super().__init__(timeout=180.0)
        options = []
        for job in jobs[:25]:
            file_name = job.get("selected_file_name") or "Unknown File"
            created_at = job.get("created_at", "").split(".")[0] or "Unknown Time"
            
            label = file_name
            if len(label) > 100:
                label = label[:47] + "..." + label[-47:]
            
            options.append(discord.SelectOption(
                label=label,
                description=f"Queued: {created_at} | Status: {job.get('status')}",
                value=str(job["id"])
            ))
        self.add_item(StatusDropdown(options))


# Helper Views for Discord UI Interactions

class FileSelectView(discord.ui.View):
    """Dropdown selection view shown when multiple files are within the 10% size window."""
    def __init__(self, reference_id: str, candidates: list, is_dry_run: bool):
        super().__init__(timeout=180.0)
        self.reference_id = reference_id
        self.is_dry_run = is_dry_run
        
        # Populate Select Option dropdown
        options = []
        for file in candidates[:25]:  # Discord limits to 25 items
            size_gb = file["size"] / (1024 ** 3)
            options.append(discord.SelectOption(
                label=file["name"][:100],
                description=f"Size: {size_gb:.2f} GB",
                value=str(file["id"])
            ))

        self.add_item(FileDropdown(options, self.reference_id, self.is_dry_run))


class FileDropdown(discord.ui.Select):
    def __init__(self, options: list, reference_id: str, is_dry_run: bool):
        super().__init__(placeholder="Select the main video file to queue...", min_values=1, max_values=1, options=options)
        self.reference_id = reference_id
        self.is_dry_run = is_dry_run

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        selected_id = self.values[0]
        
        # Call tool with explicit file choice
        res = await enqueue_download_tool(
            reference_id=self.reference_id,
            dry_run=self.is_dry_run,
            selected_file_id=selected_id
        )

        if not res["ok"]:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Download Error",
                    description=res["error"]["message"],
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        data = res["data"]
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ File Selected & Queued",
                description=f"**File:** {data.get('selected_file')}\n**Status:** {data.get('status')}\n**Routing:** {data.get('idm_routing', {}).get('message')}",
                color=discord.Color.green()
            ),
            ephemeral=True
        )

        job_id = data.get("job_id")
        if job_id:
            await post_pipeline_status_card(interaction, job_id)


class SearchResultView(discord.ui.View):
    """Button selection views for indexer search outputs."""
    def __init__(self, results: list):
        super().__init__(timeout=300.0)
        # Create buttons for the top 5 results
        for idx, item in enumerate(results[:5]):
            size_gb = item['size_bytes'] / (1024 ** 3)
            button_label = f"#{idx+1} ({size_gb:.1f}GB)"
            self.add_item(DownloadButton(
                label=button_label,
                reference_id=item["reference_id"],
                title=item["title"]
            ))


class DownloadButton(discord.ui.Button):
    def __init__(self, label: str, reference_id: str, title: str):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.reference_id = reference_id
        self.title = title

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Invoke download tool
        res = await enqueue_download_tool(reference_id=self.reference_id, dry_run=False)
        
        if not res["ok"]:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Error Queueing",
                    description=res["error"]["message"],
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        data = res["data"]
        status = data.get("status")
        
        if status == "requires_file_selection":
            # Display dropdown to let the user select the file
            candidates = data["candidates"]
            view = FileSelectView(
                reference_id=self.reference_id,
                candidates=candidates,
                is_dry_run=False
            )
            await interaction.followup.send(
                content="Multiple files match size metrics. Please pick the correct file:",
                view=view,
                ephemeral=True
            )
            return

        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ Download Sent to IDM",
                description=f"**File:** {data.get('selected_file')}\n**Status:** {data.get('status')}\n**Routing:** {data.get('idm_routing', {}).get('message')}",
                color=discord.Color.green()
            ),
            ephemeral=True
        )

        job_id = data.get("job_id")
        if job_id:
            await post_pipeline_status_card(interaction, job_id)


class CollectionAuditView(discord.ui.View):
    """View showing buttons to trigger search for missing collection movies."""
    def __init__(self, missing_movies: list):
        super().__init__(timeout=300.0)
        # Discord allows up to 5 buttons per row. We display up to the first 5 missing items.
        for movie in missing_movies[:5]:
            self.add_item(SearchMissingButton(
                label=f"🔍 Search: {movie['title']}",
                movie_title=movie['title']
            ))


class SearchMissingButton(discord.ui.Button):
    def __init__(self, label: str, movie_title: str):
        # Truncate label if it exceeds Discord button label limit of 80 characters
        short_label = label
        if len(short_label) > 80:
            short_label = short_label[:77] + "..."
        super().__init__(label=short_label, style=discord.ButtonStyle.secondary)
        self.movie_title = movie_title

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # 1. Run local deduplication pre-flight check
        norm = normalize_title(self.movie_title)
        matches = LibraryItemRepository.search_by_normalized_title(norm)
        embed_warning = None
        if matches:
            match_info = "\n".join([f"• {m['title']} ({m['year']}) [{m['source']}]" for m in matches])
            embed_warning = discord.Embed(
                title="🔍 Local Match Alert",
                description=f"Found existing items in database:\n{match_info}\n\nDo you still want to search indexers?",
                color=discord.Color.orange()
            )

        # 2. Query indexers
        res = await search_sources_tool(query=self.movie_title)
        if not res["ok"]:
            await interaction.followup.send(content=f"❌ Search failed: {res['error']['message']}", ephemeral=True)
            return

        results = res["data"]["results"]
        if not results:
            await interaction.followup.send(content=f"No results found on indexers for '{self.movie_title}'.", ephemeral=True)
            return

        # 3. Render results
        embed_results = discord.Embed(
            title=f"🎬 Indexer Results for: {self.movie_title}",
            color=discord.Color.blue()
        )
        
        description_lines = []
        for idx, item in enumerate(results[:5]):
            size_gb = item["size_bytes"] / (1024 ** 3)
            description_lines.append(
                f"**#{idx+1}** {item['title'][:70]}...\n"
                f"   Size: {size_gb:.2f} GB | Seeders: {item['seeders']} | Indexer: {item['indexer']}"
            )
        
        embed_results.description = "\n\n".join(description_lines)
        view = SearchResultView(results)
        
        if embed_warning:
            await interaction.followup.send(embeds=[embed_warning, embed_results], view=view, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed_results, view=view, ephemeral=True)


# Slash Command Definitions

@bot.tree.command(name="search", description="Search Prowlarr indexers for a movie")
@app_commands.describe(query="Title of the movie to search")
@in_allowed_channel()
async def slash_search(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    
    # 1. Run Deduplication Pre-flight Check
    # (Extract potential year from query if user included it, or check database matches)
    norm = normalize_title(query)
    matches = LibraryItemRepository.search_by_normalized_title(norm)
    
    if matches:
        match_info = "\n".join([f"• {m['title']} ({m['year']}) [{m['source']}]" for m in matches])
        embed = discord.Embed(
            title="🔍 Local Match Alert",
            description=f"Found existing items in database:\n{match_info}\n\nDo you still want to search indexers?",
            color=discord.Color.orange()
        )
    else:
        embed = None

    # 2. Query indexers via tool
    res = await search_sources_tool(query=query)
    if not res["ok"]:
        err_msg = res["error"]["message"]
        await interaction.followup.send(content=f"❌ Search failed: {err_msg}")
        return

    results = res["data"]["results"]
    if not results:
        await interaction.followup.send(content=f"No results found on indexers for '{query}'.")
        return

    # 3. Render Results
    embed_results = discord.Embed(
        title=f"🎬 Indexer Results for: {query}",
        color=discord.Color.blue()
    )
    
    description_lines = []
    for idx, item in enumerate(results[:5]):
        size_gb = item["size_bytes"] / (1024 ** 3)
        description_lines.append(
            f"**#{idx+1}** {item['title'][:70]}...\n"
            f"   Size: {size_gb:.2f} GB | Seeders: {item['seeders']} | Indexer: {item['indexer']}"
        )
    
    embed_results.description = "\n\n".join(description_lines)
    view = SearchResultView(results)
    
    if embed:
        # Show both warnings and results
        await interaction.followup.send(embeds=[embed, embed_results], view=view)
    else:
        await interaction.followup.send(embed=embed_results, view=view)


@bot.tree.command(name="check", description="Evaluate a movie against the library database")
@app_commands.describe(title="Movie title", year="Release year")
@in_allowed_channel()
async def slash_check(interaction: discord.Interaction, title: str, year: int):
    await interaction.response.defer()
    
    res = await dedupe_check_tool(title=title, year=year)
    if not res["ok"]:
        await interaction.followup.send(content=f"❌ Check failed: {res['error']['message']}")
        return

    data = res["data"]
    color = discord.Color.green() if data["action"] == "allow" else (discord.Color.red() if data["action"] == "block" else discord.Color.orange())
    
    embed = discord.Embed(
        title="📊 Library Check Results",
        description=f"**Title:** {title} ({year})\n**Action:** {data['action'].upper()}\n**Details:** {data['details']}",
        color=color
    )
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="sync", description="Sync local database state with Plex server")
@in_allowed_channel()
async def slash_sync(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        client = PlexClient()
        movies = await client.fetch_all_movies()
        for m in movies:
            LibraryItemRepository.upsert(
                id=m["id"],
                source=m["source"],
                rating_key=m["rating_key"],
                title=m["title"],
                normalized_title=normalize_title(m["title"]),
                year=m["year"],
                imdb_id=m["imdb_id"],
                file_path=m["file_path"],
                size_bytes=m["size_bytes"]
            )
            
        # Clean up database records of Plex movies that were not in this sync
        from moviebot.db.connection import get_db_connection
        synced_ids = [m["id"] for m in movies]
        with get_db_connection() as conn:
            if synced_ids:
                placeholders = ",".join("?" for _ in synced_ids)
                conn.execute(
                    f"DELETE FROM library_items WHERE source = 'plex' AND id NOT IN ({placeholders})",
                    synced_ids
                )
            else:
                conn.execute("DELETE FROM library_items WHERE source = 'plex'")
            conn.commit()
            
        await interaction.followup.send(content=f"✅ Plex sync completed. Imported {len(movies)} movie logs.")
    except Exception as e:
        await interaction.followup.send(content=f"❌ Sync failed: {str(e)}")


@bot.tree.command(name="history", description="Query Plex/Tautulli watch history")
@app_commands.describe(
    user="Filter by username (optional)",
    title="Filter by movie title (optional)",
    limit="Max number of items to return (default 10)"
)
@in_allowed_channel()
async def slash_history(
    interaction: discord.Interaction,
    user: str = None,
    title: str = None,
    limit: int = 10
):
    await interaction.response.defer()
    
    res = await query_watch_history_tool(user=user, title=title, limit=limit)
    if not res["ok"]:
        await interaction.followup.send(content=f"❌ History query failed: {res['error']['message']}")
        return

    history = res["data"]["history"]
    if not history:
        await interaction.followup.send(content="No matching watch logs found.")
        return

    resolved_user = res["data"].get("resolved_user")
    title_suffix = f" (User: {resolved_user})" if resolved_user else ""
    embed = discord.Embed(
        title=f"🎬 Plex Watch History{title_suffix}",
        color=discord.Color.purple()
    )

    lines = []
    for idx, log in enumerate(history):
        percent = f" ({log['percent_complete']}% watched)" if log.get("percent_complete") else ""
        lines.append(
            f"**#{idx+1}** {log['user']} watched **{log['title']}**\n"
            f"   📅 {log['date']} | 📺 {log['player']}{percent}"
        )

    embed.description = "\n\n".join(lines)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="status", description="Get the status of an ingestion pipeline job")
@app_commands.describe(title="Optional movie title to search for")
@in_allowed_channel()
async def slash_status(interaction: discord.Interaction, title: Optional[str] = None):
    await interaction.response.defer(ephemeral=False)
    
    if not title:
        from moviebot.db.repositories import DownloadJobRepository
        jobs = DownloadJobRepository.get_all_jobs(limit=5)
        if not jobs:
            await interaction.followup.send("❌ No recent download jobs found in database.", ephemeral=True)
            return
        
        view = StatusSelectView(jobs)
        await interaction.followup.send("Select a job from the list below to view its status:", view=view)
        return
        
    from moviebot.db.repositories import DownloadJobRepository
    jobs = DownloadJobRepository.search_by_title(title)
    if not jobs:
        await interaction.followup.send(f"❌ No jobs found matching `{title}`.", ephemeral=True)
        return
        
    if len(jobs) == 1:
        job_id = jobs[0]["id"]
        try:
            service = PipelineStatusService()
            status = await service.get_status(job_id)
            embed = create_status_embed(status)
            view = PipelineStatusView()
            await interaction.followup.send(embed=embed, view=view)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to fetch status: {str(e)}", ephemeral=True)
    else:
        view = StatusSelectView(jobs[:25])
        await interaction.followup.send(f"Multiple jobs matched `{title}`. Please select one:", view=view)


@bot.tree.command(name="download", description="Queue a magnet link or torrent URL directly to IDM")
@app_commands.describe(url="Magnet link or direct torrent URL to download")
@in_allowed_channel()
async def slash_download(interaction: discord.Interaction, url: str):
    await interaction.response.defer(ephemeral=True)
    
    # Generate a temporary reference id and hash the URL for audit trail
    ref_id = str(uuid.uuid4())
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
    
    try:
        SearchResultRepository.insert(
            id=ref_id,
            query_string="manual_download",
            indexer="manual",
            title="Manual Direct Download",
            size_bytes=None,
            seeders=None,
            magnet_uri_hash=url_hash,
            raw_json_payload=json.dumps({"downloadUrl": url})
        )
    except Exception as e:
        await interaction.followup.send(
            embed=discord.Embed(
                title="❌ Database Error",
                description=f"Failed to cache download reference: {str(e)}",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
        return
    
    res = await enqueue_download_tool(reference_id=ref_id, dry_run=False)
    if not res["ok"]:
        await interaction.followup.send(
            embed=discord.Embed(
                title="❌ Error Queueing",
                description=res["error"]["message"],
                color=discord.Color.red()
            ),
            ephemeral=True
        )
        return

    data = res["data"]
    status = data.get("status")
    
    if status == "requires_file_selection":
        candidates = data["candidates"]
        view = FileSelectView(
            reference_id=ref_id,
            candidates=candidates,
            is_dry_run=False
        )
        await interaction.followup.send(
            content="Multiple files match size metrics. Please pick the correct file:",
            view=view,
            ephemeral=True
        )
        return

    await interaction.followup.send(
        embed=discord.Embed(
            title="✅ Direct Download Sent to IDM",
            description=f"**File:** {data.get('selected_file')}\n**Status:** {data.get('status')}\n**Routing:** {data.get('idm_routing', {}).get('message')}",
            color=discord.Color.green()
        ),
        ephemeral=True
    )

    job_id = data.get("job_id")
    if job_id:
        await post_pipeline_status_card(interaction, job_id)


@bot.tree.command(name="jobs", description="List active or recent download jobs")
@app_commands.describe(
    active_only="List only pending/downloading/requires_selection jobs",
    limit="Maximum number of historical jobs to return"
)
@in_allowed_channel()
async def slash_jobs(interaction: discord.Interaction, active_only: bool = True, limit: int = 10):
    await interaction.response.defer()
    res = await get_download_jobs_tool(active_only=active_only, limit=limit)
    if not res["ok"]:
        await interaction.followup.send(content=f"❌ Failed to fetch jobs: {res['error']['message']}")
        return

    jobs = res["data"]["jobs"]
    if not jobs:
        status_str = "active " if active_only else ""
        await interaction.followup.send(content=f"No {status_str}download jobs found in the database.")
        return

    embed = discord.Embed(
        title="📥 Download Jobs" + (" (Active Only)" if active_only else ""),
        color=discord.Color.blue()
    )

    for idx, job in enumerate(jobs[:25]):  # Embed fields max 25
        job_id = job["id"]
        status = job["status"].upper()
        file_name = job["selected_file_name"] or "None"
        created = job["created_at"] or "Unknown"
        target = job["target_dir"] or "Unknown"

        status_emoji = "⏳" if status == "PENDING" else "⚙️" if status == "DOWNLOADING" else "⚠️" if status == "REQUIRES_SELECTION" else "✅"

        field_name = f"{status_emoji} Job {idx+1}: {status}"
        field_val = (
            f"**File:** `{file_name}`\n"
            f"**ID:** `{job_id}`\n"
            f"**Target:** `{target}`\n"
            f"**Created:** `{created}`"
        )
        embed.add_field(name=field_name, value=field_val, inline=False)

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="resolve", description="Manually trigger a sweep to resolve pending torrents")
@app_commands.describe(
    dry_run="Perform a dry run check without modifying jobs or triggering IDM"
)
@in_allowed_channel()
async def slash_resolve(interaction: discord.Interaction, dry_run: bool = False):
    await interaction.response.defer()
    res = await resolve_pending_jobs_tool(dry_run=dry_run)
    if not res["ok"]:
        await interaction.followup.send(content=f"❌ Resolve sweep failed: {res['error']['message']}")
        return

    data = res["data"]
    resolved = data.get("resolved", [])
    ambiguous = data.get("ambiguous_requires_selection", [])
    still_pending = data.get("still_pending", [])
    failed = data.get("failed", [])

    embed = discord.Embed(
        title="🔄 Torrent Resolution Sweep Results" + (" (Dry Run)" if dry_run else ""),
        color=discord.Color.green() if not failed else discord.Color.orange()
    )

    embed.add_field(name="✅ Resolved & Sent to IDM", value=str(len(resolved)), inline=True)
    embed.add_field(name="❓ Ambiguous (Requires Selection)", value=str(len(ambiguous)), inline=True)
    embed.add_field(name="⏳ Still Pending (Resolving Metadata)", value=str(len(still_pending)), inline=True)
    embed.add_field(name="❌ Failed", value=str(len(failed)), inline=True)

    if resolved:
        resolved_details = "\n".join(f"• Job `{j['job_id'][:8]}`: {j['selected_file']}" for j in resolved)
        embed.add_field(name="Details: Resolved", value=resolved_details[:1024], inline=False)

    if ambiguous:
        ambiguous_details = "\n".join(f"• Job `{j['job_id'][:8]}` (Magnet: `{j['magnet_id'][:8]}`)" for j in ambiguous)
        embed.add_field(name="Details: Requires Selection", value=ambiguous_details[:1024], inline=False)

    if failed:
        failed_details = "\n".join(f"• Job `{j['job_id'][:8]}`: {j['error']}" for j in failed)
        embed.add_field(name="Details: Failed", value=failed_details[:1024], inline=False)

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="errors", description="List recent diagnostic error logs")
@app_commands.describe(
    limit="Maximum number of errors to display (default 10)"
)
@in_allowed_channel()
@is_bot_manager_check()
async def slash_errors(interaction: discord.Interaction, limit: int = 10):
    await interaction.response.defer(ephemeral=True)
    res = await get_error_logs_tool(limit=limit)
    if not res["ok"]:
        await interaction.followup.send(content=f"❌ Failed to retrieve errors: {res['error']['message']}", ephemeral=True)
        return

    errors = res["data"]["errors"]
    if not errors:
        await interaction.followup.send(content="No recorded errors found in the database.", ephemeral=True)
        return

    embed = discord.Embed(
        title="⚠️ Diagnostic Error Logs",
        description=f"Showing the last {len(errors)} logged command errors.",
        color=discord.Color.dark_red()
    )

    for idx, err in enumerate(errors):
        cmd = err.get("command_name") or "unknown"
        user = err.get("user_name") or "unknown"
        msg = err.get("error_message") or "No message"
        created = err.get("created_at") or ""

        field_name = f"#{idx+1} /{cmd} | User: {user} | {created}"
        field_val = f"**Error:** {msg[:200]}\n"

        if err.get("stack_trace"):
            tb = err["stack_trace"]
            if len(tb) > 300:
                tb = tb[:300] + "\n... (truncated)"
            field_val += f"```python\n{tb}```"
        else:
            field_val += "_No traceback recorded_"

        embed.add_field(name=field_name, value=field_val, inline=False)

    await interaction.followup.send(embed=embed, ephemeral=True)





@bot.tree.command(name="help", description="Show list of available commands and pipeline guide")
@in_allowed_channel()
async def slash_help(interaction: discord.Interaction):
    # Determine if user is a bot manager to show restricted commands
    is_manager = is_bot_manager(interaction)
    
    embed = discord.Embed(
        title="🎬 MovieBot Help & Command Reference",
        description=(
            "Welcome to **MovieBot**! This bot manages the media automation pipeline, "
            "allowing you to search, download, and audit Plex movies directly from Discord.\n\n"
            "**Workflow Overview**:\n"
            "1️⃣ Search for a movie using `/search`.\n"
            "2️⃣ Queue it for download with `/download` (or use search result buttons). *An interactive status card is posted to track the download progress in real-time.*\n"
            "3️⃣ Track progress at any time using `/status [title]` (or use the refresh button on the card).\n"
            "4️⃣ Watch on Plex once all pipeline stages turn green!"
        ),
        color=discord.Color.blue()
    )
    
    # User Commands
    user_commands = (
        "🔍 **Searching & Checking**\n"
        "• `/search <query>`: Search Prowlarr indexers for a movie.\n"
        "• `/check <title> <year>`: Check if a movie is already in Plex or blocked.\n"
        "• `/status <title> [year]`: Check status of a movie in the ingestion pipeline.\n"
        "• `/history [user] [title] [limit]`: View recent Plex watch history.\n\n"
        "⬇️ **Downloading & Syncing**\n"
        "• `/download <url>`: Directly queue a magnet link or torrent URL to IDM.\n"
        "• `/jobs [active_only] [limit]`: List active or recent download jobs.\n"
        "• `/sync`: Sync local SQLite DB with Plex metadata."
    )
    embed.add_field(name="👥 User Commands", value=user_commands, inline=False)
    
    # Manager Commands
    if is_manager:
        manager_commands = (
            "⚙️ **System Operations**\n"
            "• `/health`: Expose stack connectivity, process metrics, and disk space.\n"
            "• `/resolve [dry_run]`: Trigger manual sweep resolving pending/debrid torrents.\n"
            "• `/debug <rating_key>`: Audit a specific Plex rating key via Mismatch Guard.\n\n"
            "📋 **Diagnostics & Logs**\n"
            "• `/events [limit]`: Retrieve recent SQLite system events.\n"
            "• `/errors [limit]`: View recent runtime command exceptions.\n"
            "• `/logs <source> [lines]`: Tail logs for `watcher`, `bot-out`, or `bot-err`."
        )
        embed.add_field(name="🔧 Bot Manager Commands", value=manager_commands, inline=False)
    else:
        embed.set_footer(text="Note: Administrative / diagnostic commands are hidden for non-managers.")

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="health", description="Expose stack connectivity, process metrics, and disk spaces")
@in_allowed_channel()
@is_bot_manager_check()
async def slash_health(interaction: discord.Interaction):
    await interaction.response.defer()
    res = await get_system_health_tool()
    if not res["ok"]:
        await interaction.followup.send(
            embed=discord.Embed(
                title="❌ Error Querying Health",
                description=res["error"]["message"],
                color=discord.Color.red()
            )
        )
        return

    data = res["data"]
    embed = discord.Embed(
        title="🖥️ System Health & Observability",
        color=discord.Color.green()
    )

    # System Info
    timestamp = res.get("timestamp", "Unknown")
    embed.add_field(
        name="Time (UTC)",
        value=timestamp,
        inline=True
    )

    # Connectivity
    services = data.get("services", {})
    conn_lines = []
    for service, info in services.items():
        if not info.get("configured"):
            status_emoji = "⚪"
            status_text = "Not configured"
        elif info.get("connected"):
            status_emoji = "✅"
            status_text = "Online"
        else:
            status_emoji = "❌"
            status_text = f"Offline ({info.get('error') or 'status code ' + str(info.get('status_code'))})"
        conn_lines.append(f"{status_emoji} **{service.upper()}**: {status_text}")
    if conn_lines:
        embed.add_field(name="🔗 Service Connectivity", value="\n".join(conn_lines), inline=False)

    # Storage
    disks = data.get("disks", {})
    storage_lines = []
    for drive_name, info in disks.items():
        if not info.get("exists"):
            storage_lines.append(f"• `{info.get('path')}`: Not mounted")
        elif "error" in info:
            storage_lines.append(f"• `{info.get('path')}`: Error: {info['error']}")
        else:
            write_status = "RW" if info.get("writeable") else "RO"
            storage_lines.append(
                f"• **Drive {drive_name}** (`{info.get('path')}`): "
                f"{info.get('free_gb')} GB free of {info.get('total_gb')} GB ({info.get('percent_free')}% free, {write_status})"
            )
    if storage_lines:
        embed.add_field(name="💾 Disk Storage Health", value="\n".join(storage_lines), inline=False)

    # PM2 Processes
    pm2 = data.get("pm2", {})
    pm2_lines = []
    if pm2.get("ok"):
        for proc in pm2.get("processes", []):
            name = proc.get("name")
            status = proc.get("status")
            cpu = proc.get("cpu_percent", 0)
            mem_mb = proc.get("memory_mb", 0)
            restarts = proc.get("restarts", 0)
            status_emoji = "🟢" if status == "online" else "🔴"
            pm2_lines.append(f"{status_emoji} **{name}**: {status} | Restarts: {restarts} | CPU: {cpu}% | RAM: {mem_mb:.1f} MB")
    else:
        pm2_lines.append(f"⚠️ PM2 connection error: {pm2.get('error')}")
    if pm2_lines:
        embed.add_field(name="⚙️ PM2 Processes", value="\n".join(pm2_lines), inline=False)

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="events", description="Retrieve recent SQLite event log entries")
@app_commands.describe(
    limit="Maximum number of events to display (default 10, max 25)"
)
@in_allowed_channel()
@is_bot_manager_check()
async def slash_events(interaction: discord.Interaction, limit: int = 10):
    await interaction.response.defer(ephemeral=True)
    limit = min(max(1, limit), 25)
    res = await get_recent_events_tool(limit=limit)
    if not res["ok"]:
        await interaction.followup.send(content=f"❌ Failed to retrieve events: {res['error']['message']}", ephemeral=True)
        return

    events = res["data"]["events"]
    if not events:
        await interaction.followup.send(content="No recorded events found in the database.", ephemeral=True)
        return

    embed = discord.Embed(
        title="🔔 Recent System Events",
        description=f"Showing the last {len(events)} logged system events.",
        color=discord.Color.blue()
    )

    for idx, evt in enumerate(events):
        evt_type = evt.get("event_type") or "unknown"
        source = evt.get("source") or "unknown"
        title = evt.get("title") or "N/A"
        summary = evt.get("summary") or "No summary"
        status = evt.get("status") or "N/A"
        severity = evt.get("severity") or "info"
        occurred = evt.get("occurred_at") or evt.get("created_at") or ""
        
        if "T" in occurred:
            occurred = occurred.split(".")[0].replace("T", " ")

        severity_emoji = "ℹ️"
        if severity == "warning":
            severity_emoji = "⚠️"
        elif severity in ("error", "critical"):
            severity_emoji = "🚨"

        field_name = f"#{idx+1} {severity_emoji} {evt_type.upper()} | {source.upper()} | {occurred}"
        field_val = (
            f"**Title:** {title}\n"
            f"**Status:** `{status}`\n"
            f"**Summary:** {summary[:500]}"
        )
        embed.add_field(name=field_name, value=field_val, inline=False)

    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="logs", description="Tail logs for a named source")
@app_commands.describe(
    source="Log file source name (watcher, bot-out, bot-err)",
    lines="Number of lines to tail (default 20, max 100)"
)
@in_allowed_channel()
@is_bot_manager_check()
async def slash_logs(interaction: discord.Interaction, source: Literal["watcher", "bot-out", "bot-err"], lines: int = 20):
    await interaction.response.defer(ephemeral=True)
    lines = min(max(1, lines), 100)
    res = await tail_logs_tool(source=source, lines=lines)
    if not res["ok"]:
        await interaction.followup.send(content=f"❌ Failed to tail logs: {res['error']['message']}", ephemeral=True)
        return

    data = res["data"]
    log_lines = data.get("lines", [])
    if not log_lines:
        await interaction.followup.send(content=f"Log source '{source}' has no lines.", ephemeral=True)
        return

    chunk = ""
    messages = []
    for line in log_lines:
        if len(chunk) + len(line) + 10 > 1900:
            messages.append(f"```log\n{chunk}```")
            chunk = ""
        chunk += line + "\n"
    if chunk:
        messages.append(f"```log\n{chunk}```")

    for idx, msg in enumerate(messages):
        if idx == 0:
            await interaction.followup.send(
                content=f"📋 **Last {lines} lines from `{source}` log:**\n{msg}",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                content=msg,
                ephemeral=True
            )





# Mismatch Guard Observability & Repair UI

class RematchSearchModal(discord.ui.Modal, title="🔧 Fix Plex Match"):
    def __init__(self, rating_key: str, default_title: str, default_year: Optional[int]):
        super().__init__()
        self.rating_key = rating_key
        self.movie_title = discord.ui.TextInput(
            label="Search Query / Movie Title",
            default=default_title,
            placeholder="e.g. Predator Badlands",
            required=True
        )
        self.movie_year = discord.ui.TextInput(
            label="Year (Optional)",
            default=str(default_year) if default_year else "",
            placeholder="e.g. 2025",
            required=False,
            max_length=4
        )
        self.add_item(self.movie_title)
        self.add_item(self.movie_year)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        plex = PlexClient()
        title_val = self.movie_title.value.strip()
        
        # Search candidates
        candidates = await plex.get_matches(self.rating_key)
        
        if not candidates:
            # Try unmatching and fetching again to refresh Plex search
            await plex.unmatch_item(self.rating_key)
            await asyncio.sleep(1.0)
            candidates = await plex.get_matches(self.rating_key)

        if not candidates:
            await interaction.followup.send(f"❌ No matching candidates returned by Plex for '{title_val}'.", ephemeral=True)
            return

        dropdown_view = RematchCandidateSelectView(
            rating_key=self.rating_key,
            candidates=candidates,
            parent_message=interaction.message
        )
        await interaction.followup.send(
            content="Select the correct movie match from the dropdown below:",
            view=dropdown_view,
            ephemeral=True
        )


class RematchCandidateSelect(discord.ui.Select):
    def __init__(self, rating_key: str, candidates: list, parent_message: discord.Message):
        options = []
        for i, c in enumerate(candidates[:25]): # Discord limits to 25 options
            year_str = f" ({c['year']})" if c.get('year') else ""
            score_str = f" [Score: {c.get('score', 0)}]"
            options.append(discord.SelectOption(
                label=f"{c['name']}{year_str}",
                description=f"{score_str} | GUID: {c['guid'][:40]}...",
                value=str(i)
            ))
        super().__init__(placeholder="Choose the correct Plex match...", options=options)
        self.rating_key = rating_key
        self.candidates = candidates
        self.parent_message = parent_message

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        idx = int(self.values[0])
        chosen = self.candidates[idx]
        
        plex = PlexClient()
        # Break match first
        await plex.unmatch_item(self.rating_key)
        await asyncio.sleep(1.0)
        
        # Match item
        success = await plex.match_item(self.rating_key, chosen["guid"], chosen["name"])
        if success:
            # Sync DB
            updated = await plex.fetch_movie_details(self.rating_key)
            if updated:
                LibraryItemRepository.upsert(
                    id=updated["id"],
                    source=updated["source"],
                    rating_key=updated["rating_key"],
                    title=updated["title"],
                    normalized_title=normalize_title(updated["title"]),
                    year=updated["year"],
                    imdb_id=updated["imdb_id"],
                    file_path=updated["file_path"],
                    size_bytes=updated["size_bytes"]
                )
            
            # Edit parent warning message
            embed = self.parent_message.embeds[0]
            embed.color = discord.Color.green()
            embed.title = "✅ Plex Match Resolved"
            year_str = f" ({chosen['year']})" if chosen.get('year') else ""
            embed.description = f"This mismatch has been resolved.\n**Matched to**: {chosen['name']}{year_str}"
            
            # Clear buttons on original message
            await self.parent_message.edit(embed=embed, view=None)
            
            # Clear the dropdown message
            await interaction.edit_original_response(content="✅ Rematch applied successfully!", view=None)
        else:
            await interaction.followup.send("❌ Plex returned an error when matching.", ephemeral=True)


class RematchCandidateSelectView(discord.ui.View):
    def __init__(self, rating_key: str, candidates: list, parent_message: discord.Message):
        super().__init__(timeout=180.0)
        self.add_item(RematchCandidateSelect(rating_key, candidates, parent_message))


class MismatchAlertView(discord.ui.View):
    def __init__(self, rating_key: str, default_title: str, default_year: Optional[int]):
        super().__init__(timeout=None)
        self.rating_key = rating_key
        self.default_title = default_title
        self.default_year = default_year

    @discord.ui.button(label="🔧 Fix Match", style=discord.ButtonStyle.primary, custom_id="mismatch_fix_match")
    async def fix_match_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_bot_manager(interaction):
            await interaction.response.send_message("🚫 You do not have permission to fix this match.", ephemeral=True)
            return
        modal = RematchSearchModal(
            rating_key=self.rating_key,
            default_title=self.default_title,
            default_year=self.default_year
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="✅ Keep Match", style=discord.ButtonStyle.secondary, custom_id="mismatch_keep_match")
    async def keep_match_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_bot_manager(interaction):
            await interaction.response.send_message("🚫 You do not have permission to keep this match.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.blue()
        embed.title = "✅ Match Confirmed"
        embed.description += "\n\n*Accepted by Administrator.*"
        
        await interaction.message.edit(embed=embed, view=None)
        await interaction.followup.send("Accepted Plex's current match.", ephemeral=True)


async def post_mismatch_alert(conflict: Dict[str, Any]):
    """
    Constructs an interactive Discord embed warning for mismatched metadata and posts it.
    """
    channels = settings.allowed_channels_list
    if not channels:
        print("[Mismatch Guard] No allowed Discord channels configured to post alert.")
        return

    channel_id = channels[0]
    channel = bot.get_channel(channel_id)
    if not channel:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception:
            print(f"[Mismatch Guard ERROR] Could not fetch channel: {channel_id}")
            return

    rating_key = conflict["rating_key"]
    job_filename = conflict["job_filename"]
    expected_title = conflict["job_expected_title"]
    expected_year = conflict["job_expected_year"]
    matched_title = conflict["plex_matched_title"]
    matched_year = conflict["plex_matched_year"]
    similarity = conflict["similarity"]

    embed = discord.Embed(
        title="⚠️ Plex Metadata Mismatch Detected",
        description=(
            f"Plex has imported a movie but matched it to a different item than what was downloaded.\n\n"
            f"**Download File**: `{job_filename}`\n"
            f"**Expected**: `{expected_title}` ({expected_year or 'Unknown'})\n"
            f"**Plex Matched**: `{matched_title}` ({matched_year or 'Unknown'})\n"
            f"**Title Similarity**: `{similarity:.1f}%`"
        ),
        color=discord.Color.orange()
    )
    embed.add_field(name="Rating Key", value=str(rating_key), inline=True)
    embed.add_field(name="Action Required", value="Click **Fix Match** to search and match the correct metadata, or **Keep Match** to accept Plex's match.", inline=False)

    view = MismatchAlertView(rating_key=rating_key, default_title=expected_title, default_year=expected_year)
    await channel.send(embed=embed, view=view)


@bot.tree.command(name="debug", description="Manually run Mismatch Guard audit on a Plex rating key")
@app_commands.describe(rating_key="Plex rating key of the movie to audit")
@in_allowed_channel()
@is_bot_manager_check()
async def slash_debug(interaction: discord.Interaction, rating_key: str):
    await interaction.response.defer()
    
    from moviebot.core.mismatch_guard import MismatchGuard
    guard = MismatchGuard()
    
    try:
        audit_res = await guard.audit_plex_item(rating_key)
        
        status = audit_res.get("status")
        if status == "ignored":
            reason = audit_res.get("reason", "No reason provided.")
            embed = discord.Embed(
                title="🔍 Mismatch Guard Audit: Ignored",
                description=f"Plex item `{rating_key}` was audited but ignored.\n**Reason**: {reason}",
                color=discord.Color.light_grey()
            )
            await interaction.followup.send(embed=embed)
        elif status == "correct":
            title = audit_res.get("plex_title")
            similarity = audit_res.get("similarity", 100.0)
            embed = discord.Embed(
                title="🔍 Mismatch Guard Audit: Correct",
                description=f"Plex item `{rating_key}` (**{title}**) matches the download job perfectly!\n**Title Similarity**: `{similarity:.1f}%`",
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=embed)
        elif status == "auto_corrected":
            old_title = audit_res.get("old_title")
            new_title = audit_res.get("new_title")
            embed = discord.Embed(
                title="🔍 Mismatch Guard Audit: Auto-Corrected",
                description=f"Plex item `{rating_key}` was detected as mismatched and automatically matched to the correct item!\n**Old Title**: `{old_title}`\n**New Title**: `{new_title}`",
                color=discord.Color.gold()
            )
            await interaction.followup.send(embed=embed)
        elif status == "mismatch_detected":
            job_filename = audit_res["job_filename"]
            expected_title = audit_res["job_expected_title"]
            expected_year = audit_res["job_expected_year"]
            matched_title = audit_res["plex_matched_title"]
            matched_year = audit_res["plex_matched_year"]
            similarity = audit_res["similarity"]

            embed = discord.Embed(
                title="⚠️ Plex Metadata Mismatch Detected",
                description=(
                    f"Plex has imported a movie but matched it to a different item than what was downloaded.\n\n"
                    f"**Download File**: `{job_filename}`\n"
                    f"**Expected**: `{expected_title}` ({expected_year or 'Unknown'})\n"
                    f"**Plex Matched**: `{matched_title}` ({matched_year or 'Unknown'})\n"
                    f"**Title Similarity**: `{similarity:.1f}%`"
                ),
                color=discord.Color.orange()
            )
            embed.add_field(name="Rating Key", value=str(rating_key), inline=True)
            embed.add_field(name="Action Required", value="Click **Fix Match** to search and match the correct metadata, or **Keep Match** to accept Plex's match.", inline=False)

            view = MismatchAlertView(rating_key=rating_key, default_title=expected_title, default_year=expected_year)
            await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.followup.send(content=f"Unknown mismatch status: {status}")
            
    except Exception as e:
        tb_str = traceback.format_exc()
        embed = discord.Embed(
            title="❌ Debug Error",
            description=f"Failed to audit rating key `{rating_key}`:\n```{str(e)}```",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed)


@bot.tree.command(name="library", description="Search the library using keyword filters or semantic queries")
@app_commands.describe(
    query="FTS5 query keyword",
    semantic_query="Conceptual semantic search prompt",
    genre="Genre filter",
    director="Director filter",
    resolution="Resolution filter",
    watch_status="Watch status filter",
    max_runtime="Max runtime in minutes",
    min_rating="Minimum rating score",
    limit="Max results to return (default 10)"
)
@in_allowed_channel()
async def slash_library(
    interaction: discord.Interaction,
    query: Optional[str] = None,
    semantic_query: Optional[str] = None,
    genre: Optional[str] = None,
    director: Optional[str] = None,
    resolution: Optional[str] = None,
    watch_status: Optional[str] = None,
    max_runtime: Optional[int] = None,
    min_rating: Optional[float] = None,
    limit: int = 10
):
    await interaction.response.defer()
    res = await query_library_tool(
        query=query,
        semantic_query=semantic_query,
        genre=genre,
        director=director,
        resolution=resolution,
        watch_status=watch_status,
        max_runtime=max_runtime,
        min_rating=min_rating,
        limit=limit
    )
    if not res["ok"]:
        await interaction.followup.send(content=f"❌ Library query failed: {res['error']['message']}")
        return

    movies = res["data"]["movies"]
    if not movies:
        await interaction.followup.send(content="No matching movies found in library.")
        return

    embed = discord.Embed(
        title="🎬 Library Search Results",
        color=discord.Color.blue()
    )
    
    description_lines = []
    for idx, m in enumerate(movies):
        title_year = f"**{m['title']}** ({m.get('year') or 'N/A'})"
        
        details = []
        if m.get("resolution"):
            details.append(f"📺 {m['resolution']}")
        if m.get("rating") is not None:
            details.append(f"⭐ {m['rating']}/10")
        if m.get("runtime"):
            details.append(f"⏱️ {m['runtime']}m")
        if m.get("watch_status"):
            details.append(f"👁️ {m['watch_status']}")
            
        match_pct = ""
        if "similarity_score" in m:
            match_pct = f" - **{m['similarity_score'] * 100:.1f}% Match**"

        details_str = " | ".join(details)
        description_lines.append(f"**#{idx+1}** {title_year}{match_pct}\n   {details_str}")

    embed.description = "\n\n".join(description_lines)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="recommend", description="Get personalized movie recommendations based on viewing history")
@app_commands.describe(
    user="Filter watch history by username (optional)",
    limit="Max recommendations to return (default 5)"
)
@in_allowed_channel()
async def slash_recommend(
    interaction: discord.Interaction,
    user: Optional[str] = None,
    limit: int = 5
):
    await interaction.response.defer()
    res = await recommend_movies_tool(user=user, limit=limit)
    if not res["ok"]:
        await interaction.followup.send(content=f"❌ Recommendation generation failed: {res['error']['message']}")
        return

    recs = res["data"]["recommendations"]
    if not recs:
        await interaction.followup.send(content="No recommendations available.")
        return

    user_label = user or "All Users"
    embed = discord.Embed(
        title=f"🍿 Recommendations for {user_label}",
        color=discord.Color.gold()
    )

    description_lines = []
    for idx, r in enumerate(recs):
        title_year = f"**{r['title']}** ({r.get('year') or 'N/A'})"
        score_str = f"Score: `{r.get('score', 0.0):.2f}`"
        breakdown_str = f"Sim: `{r.get('cosine_similarity', 0.0):.2f}` | Genre: `{r.get('genre_score', 0.0):.2f}` | Dir: `{r.get('director_score', 0.0):.2f}`"
        description_lines.append(f"**#{idx+1}** {title_year}\n   ⭐ {score_str} ({breakdown_str})")

    embed.description = "\n\n".join(description_lines)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="audit", description="Audit local collections to detect gaps and missing sequels")
@in_allowed_channel()
async def slash_audit(interaction: discord.Interaction):
    await interaction.response.defer()
    res = await audit_collections_tool()
    if not res["ok"]:
        await interaction.followup.send(content=f"❌ Collection audit failed: {res['error']['message']}")
        return

    reports = res["data"]["reports"]
    if not reports:
        await interaction.followup.send(content="All collections are fully complete! No gaps found.")
        return

    embed = discord.Embed(
        title="📋 Collection Gap Audit Results",
        description="Found sequel gaps or missing items in the following collections:",
        color=discord.Color.red()
    )

    # We will collect missing movies to construct the CollectionAuditView
    missing_movies = []
    
    # List them in the embed fields
    for idx, rep in enumerate(reports[:10]):  # Embed field limit is 25, let's show top 10
        col = rep.get("collection")
        missing = rep.get("missing", [])
        owned = rep.get("owned", [])
        
        owned_info = [f"{o['title']} ({o.get('year') or 'N/A'})" for o in sorted(owned, key=lambda x: x.get("index") or 0)]
        missing_info = [f"Part {m['index']}: {m['title']}" for m in sorted(missing, key=lambda x: x.get("index") or 0)]
        
        # Accumulate missing movies for the search buttons (across all audited collections)
        for m in missing:
            # Avoid adding duplicate titles to button list
            if not any(x["title"] == m["title"] for x in missing_movies):
                missing_movies.append(m)

        field_val = (
            f"**Owned:** {', '.join(owned_info)}\n"
            f"**Missing Gaps:**\n" + "\n".join(f"• {x}" for x in missing_info)
        )
        embed.add_field(name=f"📦 {col}", value=field_val, inline=False)

    if missing_movies:
        # Pass missing movies to CollectionAuditView for search buttons
        view = CollectionAuditView(missing_movies)
        await interaction.followup.send(embed=embed, view=view)
    else:
        await interaction.followup.send(embed=embed)


def run_discord_client():
    token = settings.discord_token
    bot.run(token)

