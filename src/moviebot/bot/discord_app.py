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

    embed = discord.Embed(
        title="🎬 Plex Watch History",
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




def run_discord_client():
    token = settings.discord_token
    bot.run(token)
