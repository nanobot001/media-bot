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
from moviebot.db.repositories import LibraryItemRepository, SearchResultRepository, ErrorLogRepository, EventRepository, KeyValueRepository, UserProfileRepository, UserMemoryRepository
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
from moviebot.tools.ask_library_tool import ask_library_tool
from moviebot.core.external_recommendations import sanitize_external_title
from typing import Literal, Optional, Dict, Any, List
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
                    if status.stage == PipelineStage.IN_PLEX:
                        await post_auto_enrichment_card_for_status(status)
                    from moviebot.db.repositories import DownloadJobRepository
                    DownloadJobRepository.update_discord_message_id(job_id, f"done:{msg_id_str}")
                    print(f"[Background Resolver] Job {job_id} reached terminal stage {status.stage}. Marked status card as done.")
            except Exception as e:
                print(f"[Background Resolver] Error updating status card for job {job_id}: {e}")

    @auto_resolve_pending_loop.before_loop
    async def before_auto_resolve_pending_loop(self):
        await self.wait_until_ready()


    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # Check if the message is in a thread
        if isinstance(message.channel, discord.Thread):
            thread = message.channel
            # Check if this thread belongs to us (the bot) and is an /ask follow-up thread
            if thread.owner_id == self.user.id:
                try:
                    # Fetch parent message (which started the thread)
                    parent_message = await thread.parent.fetch_message(thread.id)
                    # Verify parent message is from us and has the Library Assistant embed
                    if (parent_message.author.id == self.user.id and 
                            parent_message.embeds and 
                            parent_message.embeds[0].title == "💬 Library Assistant"):
                        
                        # Extract first question from parent message footer
                        first_question = ""
                        footer_text = parent_message.embeds[0].footer.text if parent_message.embeds[0].footer else ""
                        if footer_text and footer_text.startswith("Question: "):
                            first_question = footer_text.replace("Question: ", "", 1)
                        
                        if first_question:
                            # Trigger typing context
                            async with thread.typing():
                                # Build chat history
                                chat_history = [{"role": "user", "text": first_question}]
                                chat_history.append({"role": "model", "text": parent_message.embeds[0].description or ""})
                                
                                # Retrieve message history in the thread
                                async for msg in thread.history(limit=20, oldest_first=True):
                                    if msg.id == message.id:
                                        # Skip current follow-up question message itself (it is processed as the latest question)
                                        continue
                                    if msg.author.id == self.user.id:
                                        text = msg.embeds[0].description if msg.embeds else msg.content
                                        if text:
                                            chat_history.append({"role": "model", "text": text})
                                    else:
                                        if msg.content:
                                            chat_history.append({"role": "user", "text": msg.content})
                                
                                # Build known_users mapping
                                known_users = {}
                                if message.guild:
                                    for m in message.guild.members:
                                        if m.bot:
                                            continue
                                        known_users[m.name] = str(m.id)
                                        known_users[m.display_name] = str(m.id)
                                        if hasattr(m, "nick") and m.nick:
                                            known_users[m.nick] = str(m.id)
                                else:
                                    known_users = {message.author.display_name: str(message.author.id)}

                                # Call query_library_conversational
                                from moviebot.core.conversational_rag import query_library_conversational
                                res = await query_library_conversational(
                                    message.content,
                                    chat_history=chat_history,
                                    discord_user_id=str(message.author.id),
                                    known_users=known_users
                                )
                                if not res.get("ok", True) and "error" in res:
                                    await thread.send(content=f"❌ Error: {res['error']['message']}")
                                    return
                                
                                answer = res["answer"]
                                cited_ids = res.get("cited_movie_ids", [])
                                external_recs = res.get("external_recommendations", [])
                                
                                embed = discord.Embed(
                                    title="💬 Library Assistant",
                                    description=answer,
                                    color=discord.Color.blue()
                                )
                                embed.set_footer(text=f"Question: {message.content}")
                                
                                if cited_ids:
                                    cited_lines = []
                                    for m_id in cited_ids:
                                        movie = LibraryItemRepository.get_by_id(m_id)
                                        if movie:
                                            year_part = f" ({movie['year']})" if movie.get('year') is not None else ""
                                            cited_lines.append(f"• **{movie['title']}**{year_part}")
                                    if cited_lines:
                                        embed.add_field(name="📚 Cited Movies", value="\n".join(cited_lines), inline=False)
                                
                                view = CitedMoviesView(cited_ids, external_recs) if cited_ids or external_recs else None
                                await thread.send(embed=embed, view=view)
                except Exception as e:
                    print(f"[Bot] Error processing thread follow-up message: {e}")
                    traceback.print_exc()

        await self.process_commands(message)


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
    if isinstance(error, app_commands.CommandOnCooldown):
        embed = discord.Embed(
            title="⏳ Command on Cooldown",
            description=f"This command is on cooldown. Please try again in `{error.retry_after:.1f}` seconds.",
            color=discord.Color.orange()
        )
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception:
            pass
        return

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


def _find_library_item_for_status(status) -> Optional[Dict[str, Any]]:
    if not status.title:
        return None

    matches = LibraryItemRepository.search_by_normalized_title(normalize_title(status.title))
    if status.year:
        year_matches = [m for m in matches if m.get("year") == status.year]
        if year_matches:
            matches = year_matches

    if not matches:
        return None

    target_norm = normalize_title(status.title)
    matches.sort(key=lambda m: 0 if normalize_title(m.get("title") or "") == target_norm else 1)
    return matches[0]


def _json_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed if str(v).strip()]
        except Exception:
            return [value] if value.strip() else []
    return [str(value)]


def _plain_list(value: Any, limit: int = 8) -> str:
    items = _json_list(value)
    if not items:
        return "None"
    suffix = f" +{len(items) - limit} more" if len(items) > limit else ""
    return ", ".join(items[:limit]) + suffix


def _tag_list(value: Any, limit: int = 10) -> str:
    items = _json_list(value)
    if not items:
        return "None"
    suffix = f" +{len(items) - limit} more" if len(items) > limit else ""
    return " ".join(f"`{item}`" for item in items[:limit]) + suffix


def _format_runtime(minutes: Any) -> str:
    try:
        mins = int(minutes)
    except (TypeError, ValueError):
        return "Unknown"
    hours = mins // 60
    rem = mins % 60
    return f"{hours}h {rem}m" if hours else f"{rem}m"


def _format_size(size_bytes: Any) -> str:
    try:
        size = int(size_bytes)
    except (TypeError, ValueError):
        return "Unknown"
    return f"{size / (1024 ** 3):.2f} GB"


async def ensure_poster_url(item: Dict[str, Any]) -> None:
    if not item or item.get("poster_url"):
        return
    try:
        from moviebot.tools.tmdb_fact_provider import TMDbFactProvider
        provider = TMDbFactProvider()
        loop = asyncio.get_running_loop()
        facts = await loop.run_in_executor(
            None,
            lambda: provider.get_facts(
                title=item.get("title", ""),
                year=item.get("year"),
                imdb_id=item.get("imdb_id")
            )
        )
        if facts:
            poster_url = facts.get("poster_url")
            poster_path = facts.get("poster_path")
            if not poster_url and poster_path:
                poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
        else:
            poster_url = None
        if poster_url:
            item["poster_url"] = poster_url
            LibraryItemRepository.update_poster_url(item["id"], poster_url)
    except Exception as e:
        print(f"[Dynamic Poster Fetch Failed] {e}")


def build_movie_detail_embed(item: Dict[str, Any]) -> discord.Embed:
    title = item.get("title") or "Unknown Movie"
    year = item.get("year")
    synopsis = item.get("synopsis") or "No synopsis stored."
    if len(synopsis) > 900:
        synopsis = synopsis[:897].rstrip() + "..."

    embed = discord.Embed(
        title=f"Movie: {title}{f' ({year})' if year else ''}",
        description=synopsis,
        color=discord.Color.teal()
    )

    core_parts = [
        f"Rating: {item.get('rating') or 'N/A'}",
        f"Audience: {item.get('audience_rating') or 'N/A'}",
        f"Content: {item.get('content_rating') or 'N/A'}",
        f"Runtime: {_format_runtime(item.get('runtime'))}",
        f"Released: {item.get('originally_available_at') or 'Unknown'}",
        f"Watch: {item.get('watch_status') or 'unwatched'}",
    ]
    embed.add_field(name="Core", value="\n".join(core_parts), inline=True)

    library_parts = [
        f"Resolution: {item.get('resolution') or 'Unknown'}",
        f"Bitrate: {item.get('bitrate_kbps') or 'Unknown'} kbps",
        f"Size: {_format_size(item.get('size_bytes'))}",
        f"Watch Count: {item.get('watch_count') if item.get('watch_count') is not None else 0}",
    ]
    embed.add_field(name="Library", value="\n".join(library_parts), inline=True)

    if item.get("tagline"):
        embed.add_field(name="Tagline", value=str(item["tagline"])[:1024], inline=False)

    embed.add_field(name="Genres", value=_plain_list(item.get("genres")), inline=False)
    embed.add_field(name="Collections", value=_plain_list(item.get("collections")), inline=False)
    embed.add_field(name="Directors", value=_plain_list(item.get("directors")), inline=True)
    embed.add_field(name="Writers", value=_plain_list(item.get("writers")), inline=True)
    embed.add_field(name="Cast", value=_plain_list(item.get("cast"), limit=12), inline=False)
    embed.add_field(name="Studios", value=_plain_list(item.get("studios")), inline=True)
    embed.add_field(name="Countries", value=_plain_list(item.get("countries")), inline=True)

    enrichment_lines = [
        f"Brand: {_tag_list(item.get('brand_tags'))}",
        f"Franchise: {_tag_list(item.get('franchise_tags'))}",
        f"Universe: {_tag_list(item.get('universe_tags'))}",
        f"Themes: {_tag_list(item.get('theme_tags'))}",
        f"Tone: {_tag_list(item.get('tone_tags'))}",
        f"Premise: {_tag_list(item.get('premise_tags'))}",
        f"Characters: {_tag_list(item.get('character_tags'))}",
        f"Setting: {_tag_list(item.get('setting_locations'))}",
        f"Craft: {_tag_list(item.get('craft_tags'))}",
    ]
    embed.add_field(name="Enrichment", value="\n".join(enrichment_lines)[:1024], inline=False)

    hard_fact_lines = [
        f"Awards: {_tag_list(item.get('award_tags'))}",
        f"Acclaim: {_tag_list(item.get('acclaim_tags'))}",
        f"Source: {_tag_list(item.get('source_material_tags'))}",
        f"Popularity: {_tag_list(item.get('popularity_tags'))}",
        f"Cultural Impact: {_tag_list(item.get('cultural_impact_tags'))}",
        f"Box Office: {item.get('box_office_tier') or 'Unknown'}",
    ]
    embed.add_field(name="Hard Facts", value="\n".join(hard_fact_lines)[:1024], inline=False)

    warning_text = _tag_list(item.get("content_warning_tags"))
    if warning_text != "None":
        embed.add_field(name="Content Warnings", value=warning_text, inline=False)

    footer_bits = [
        f"ID: {item.get('id')}",
        f"Rating Key: {item.get('rating_key') or 'N/A'}",
        f"IMDb: {item.get('imdb_id') or 'N/A'}",
        f"Enrichment: {item.get('enrichment_model') or 'none'}",
    ]
    embed.set_footer(text=" | ".join(footer_bits)[:2048])
    if item.get("poster_url"):
        embed.set_thumbnail(url=item["poster_url"])
        embed.set_image(url=item["poster_url"])
    return embed


async def post_auto_enrichment_card_for_status(status) -> bool:
    """
    Enrich and post the New Movie Added card when a media-bot download reaches Plex.
    Tautulli may still trigger the same card for outside additions, so item/job keys
    keep this path idempotent.
    """
    job_key = f"pipeline_auto_enrichment_posted:{status.job_id}"
    if KeyValueRepository.get(job_key):
        return False

    item = _find_library_item_for_status(status)
    if not item:
        print(f"[Auto-Enrich] Pipeline reached Plex but no library item matched job {status.job_id}.")
        return False

    item_key = f"auto_enrichment_posted:{item['id']}"
    if KeyValueRepository.get(item_key):
        KeyValueRepository.set(job_key, "skipped:item_already_posted")
        return False

    channels = settings.allowed_channels_list
    if not channels:
        print(f"[Auto-Enrich] No Discord channels configured; pipeline enrichment saved but card not posted for {item.get('title')}")
        return False

    try:
        from moviebot.core.auto_enrich import auto_enrich_item, build_new_movie_embed

        enrichment = await auto_enrich_item(item, provider="gemini")
        if not enrichment:
            print(f"[Auto-Enrich] Pipeline enrichment returned None for {item.get('title')} ({item.get('year')})")
            return False

        embed = build_new_movie_embed(item, enrichment)
        channel = bot.get_channel(channels[0])
        if not channel:
            channel = await bot.fetch_channel(channels[0])

        await channel.send(embed=embed)
        KeyValueRepository.set(item_key, "pipeline")
        KeyValueRepository.set(job_key, "posted")
        EventRepository.insert(
            event_type="auto_enrichment",
            source="pipeline",
            title=item.get("title"),
            summary=f"Auto-enriched and posted card for {item.get('title')} ({item.get('year')}) after pipeline import.",
            entity_type="movie",
            entity_id=item.get("id"),
            status="completed",
            severity="info",
            data_json=json.dumps({"job_id": status.job_id, "rating_key": item.get("rating_key")})
        )
        print(f"[Auto-Enrich] Posted pipeline new movie card for {item.get('title')} ({item.get('year')})")
        return True
    except Exception as e:
        print(f"[Auto-Enrich ERROR] Pipeline card failed for {item.get('title')} ({item.get('year')}): {e}")
        try:
            ErrorLogRepository.insert(
                command_name="post_auto_enrichment_card_for_status",
                user_id=None,
                user_name=None,
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
        except Exception:
            pass
        return False


async def find_and_edit_status_message(bot, discord_message_id: int, embed: discord.Embed, view: discord.ui.View):
    """
    Attempts to find a Discord message by ID across channels/threads and edits it.
    """
    channel_ids = list(settings.allowed_channels_list)
    search_targets = []
    seen_target_ids = set()

    def add_search_target(target):
        target_id = getattr(target, "id", None)
        if target_id and target_id not in seen_target_ids:
            search_targets.append(target)
            seen_target_ids.add(target_id)
    
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.id not in channel_ids:
                channel_ids.append(channel.id)
            add_search_target(channel)
            for thread in getattr(channel, "threads", []):
                add_search_target(thread)
        for thread in getattr(guild, "threads", []):
            add_search_target(thread)
                
    for channel_id in channel_ids:
        try:
            channel = bot.get_channel(channel_id)
            if not channel:
                channel = await bot.fetch_channel(channel_id)
            
            if channel:
                add_search_target(channel)
        except discord.NotFound:
            continue
        except Exception as e:
            print(f"[Bot] Error resolving channel {channel_id} for message {discord_message_id}: {e}")
            continue

    for target in search_targets:
        try:
            message = await target.fetch_message(discord_message_id)
            if message:
                await message.edit(embed=embed, view=view)
                return True
        except discord.NotFound:
            continue
        except Exception as e:
            print(f"[Bot] Error searching channel/thread {getattr(target, 'id', 'unknown')} for message {discord_message_id}: {e}")
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


async def send_indexer_results_for_title(
    interaction: discord.Interaction,
    movie_title: str,
    ephemeral: bool = True,
) -> None:
    norm = normalize_title(movie_title)
    matches = LibraryItemRepository.search_by_normalized_title(norm)
    embed_warning = None
    if matches:
        match_info = "\n".join([f"- {m['title']} ({m['year']}) [{m['source']}]" for m in matches])
        embed_warning = discord.Embed(
            title="Local Match Alert",
            description=f"Found existing items in database:\n{match_info}\n\nDo you still want to search indexers?",
            color=discord.Color.orange()
        )

    res = await search_sources_tool(query=movie_title)
    if not res["ok"]:
        await interaction.followup.send(content=f"Search failed: {res['error']['message']}", ephemeral=ephemeral)
        return

    results = res["data"]["results"]
    if not results:
        await interaction.followup.send(content=f"No results found on indexers for '{movie_title}'.", ephemeral=ephemeral)
        return

    embed_results = discord.Embed(
        title=f"Indexer Results for: {movie_title}",
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
        await interaction.followup.send(embeds=[embed_warning, embed_results], view=view, ephemeral=ephemeral)
    else:
        await interaction.followup.send(embed=embed_results, view=view, ephemeral=ephemeral)


class CitedMovieDetailButton(discord.ui.Button):
    def __init__(self, movie_id: str, label: str):
        # Truncate label if it exceeds Discord button label limit of 80 characters
        short_label = label
        if len(short_label) > 80:
            short_label = short_label[:77] + "..."
        super().__init__(label=short_label, style=discord.ButtonStyle.secondary)
        self.movie_id = movie_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        movie = LibraryItemRepository.get_by_id(self.movie_id)
        if not movie:
            await interaction.followup.send(content="❌ Movie details not found in database.", ephemeral=True)
            return
        
        await ensure_poster_url(movie)
        embed = build_movie_detail_embed(movie)
        await interaction.followup.send(embed=embed, ephemeral=True)


class CitedMoviesView(discord.ui.View):
    def __init__(self, cited_ids: list, external_recommendations: Optional[list] = None):
        super().__init__(timeout=600.0)
        external_recommendations = external_recommendations or []
        # Add up to 5 cited and external movie buttons.
        added = 0
        for m_id in cited_ids:
            if added >= 5:
                break
            movie = LibraryItemRepository.get_by_id(m_id)
            if movie:
                self.add_item(CitedMovieDetailButton(
                    movie_id=m_id,
                    label=f"🎬 Details: {movie['title']}"
                ))
                added += 1
        for rec in external_recommendations:
            if added >= 5:
                break
            self.add_item(ExternalSearchAddButton(
                title=rec["sanitized_query"],
                year=rec.get("year"),
            ))
            added += 1


class ExternalSearchAddButton(discord.ui.Button):
    def __init__(self, title: str, year: Optional[int] = None):
        self.title = sanitize_external_title(title)
        self.year = year
        year_part = f" ({year})" if year else ""
        label = f"Search & Add: {self.title}{year_part}"
        if len(label) > 80:
            label = label[:77] + "..."
        super().__init__(label=label, style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        if not self.title:
            await interaction.response.send_message("This recommendation could not be searched safely.", ephemeral=True)
            return
        year_part = f" ({self.year})" if self.year else ""
        view = ExternalSearchConfirmView(title=self.title, year=self.year, original_user_id=interaction.user.id)
        await interaction.response.send_message(
            content=f"Search indexers and show add/download options for **{self.title}**{year_part}?",
            view=view,
            ephemeral=True,
        )


class ExternalSearchConfirmView(discord.ui.View):
    def __init__(self, title: str, year: Optional[int], original_user_id: int):
        super().__init__(timeout=60.0)
        self.title = sanitize_external_title(title)
        self.year = year
        self.original_user_id = original_user_id

    @discord.ui.button(label="Yes, Search & Add", style=discord.ButtonStyle.primary)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_user_id:
            await interaction.response.send_message("This confirmation belongs to another user.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        query = self.title
        if self.year:
            query = f"{query} {self.year}"
        await send_indexer_results_for_title(interaction, query, ephemeral=False)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_user_id:
            await interaction.response.send_message("This confirmation belongs to another user.", ephemeral=True)
            return
        await interaction.response.send_message("Search cancelled.", ephemeral=True)
        self.stop()


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
        await send_indexer_results_for_title(interaction, self.movie_title, ephemeral=True)
        return
        
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
    
    library_commands = (
        "• `/library`: Search or browse the local movie database with filters.\n"
        "• `/movie <title> [year]`: Show a detailed movie card with synopsis, metadata, enrichment, and TMDb poster.\n"
        "• `/ask <question>`: Query the library using natural language. Ask what you own or what to add next (e.g. *\"what should I add?\"*). External suggestions come with \uD83D\uDD0D **Search & Add** buttons \u2014 click to confirm before any download triggers.\n"
        "• `/recommend [user] [limit]`: Get personalized movie recommendations.\n"
        "• `/audit`: Find likely missing movies from Plex collections.\n"
        "• `/profile show`: Show and manage your profile settings, Plex mapping, and memories.\n"
        "• Enrichment cards now post automatically when a media-bot download reaches Plex."
    )
    embed.add_field(name="Library & Enrichment", value=library_commands, inline=False)

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
                    size_bytes=updated["size_bytes"],
                    genres=updated.get("genres"),
                    directors=updated.get("directors"),
                    studios=updated.get("studios"),
                    writers=updated.get("writers"),
                    producers=updated.get("producers"),
                    cast=updated.get("cast"),
                    countries=updated.get("countries"),
                    content_rating=updated.get("content_rating"),
                    audience_rating=updated.get("audience_rating"),
                    tagline=updated.get("tagline"),
                    originally_available_at=updated.get("originally_available_at"),
                    labels=updated.get("labels"),
                    rating=updated.get("rating"),
                    runtime=updated.get("runtime"),
                    collections=updated.get("collections"),
                    resolution=updated.get("resolution"),
                    bitrate_kbps=updated.get("bitrate_kbps"),
                    watch_status=updated.get("watch_status"),
                    watch_count=updated.get("watch_count", 0),
                    last_watched_at=updated.get("last_watched_at"),
                    synopsis=updated.get("synopsis"),
                    synopsis_hash=updated.get("synopsis_hash")
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
    studio="Studio or brand filter",
    actor="Actor/cast-name filter",
    content_rating="Content rating filter",
    award_tag="Award/acclaim hard-fact tag filter",
    source_material_tag="Source material hard-fact tag filter",
    popularity_tag="Popularity hard-fact tag filter",
    cultural_impact_tag="Cultural impact hard-fact tag filter",
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
    studio: Optional[str] = None,
    actor: Optional[str] = None,
    content_rating: Optional[str] = None,
    award_tag: Optional[str] = None,
    source_material_tag: Optional[str] = None,
    popularity_tag: Optional[str] = None,
    cultural_impact_tag: Optional[str] = None,
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
        studio=studio,
        actor=actor,
        content_rating=content_rating,
        award_tag=award_tag,
        source_material_tag=source_material_tag,
        popularity_tag=popularity_tag,
        cultural_impact_tag=cultural_impact_tag,
        max_runtime=max_runtime,
        min_rating=min_rating,
        limit=limit
    )
    if not res["ok"]:
        await interaction.followup.send(content=f"❌ Library query failed: {res['error']['message']}")
        return

    movies = res["data"]["movies"]
    if not movies:
        semantic_meta = res.get("data", {}).get("semantic_search")
        if semantic_query and semantic_meta and semantic_meta.get("skipped_model_mismatch", 0) > 0:
            await interaction.followup.send(
                content=(
                    "Semantic search is unavailable right now because the query embedding "
                    f"used `{semantic_meta.get('query_model')}` while library vectors use a different model. "
                    "Check the configured Gemini/Ollama embedding provider and try again."
                )
            )
            return
        await interaction.followup.send(content="No matching movies found in library.")
        return

    embed = discord.Embed(
        title="🎬 Library Search Results",
        color=discord.Color.blue()
    )
    
    # Compile active search criteria/filters
    active_criteria = []
    if semantic_query:
        active_criteria.append(f"🧠 **Semantic Query:** \"{semantic_query}\"")
    if query:
        active_criteria.append(f"🔍 **Keyword Query:** \"{query}\"")
    if genre:
        active_criteria.append(f"🏷️ **Genre:** {genre}")
    if director:
        active_criteria.append(f"🎬 **Director:** {director}")
    if actor:
        active_criteria.append(f"🎭 **Actor:** {actor}")
    if resolution:
        active_criteria.append(f"📺 **Resolution:** {resolution}")
    if watch_status:
        active_criteria.append(f"👁️ **Watch Status:** {watch_status}")
    if studio:
        active_criteria.append(f"🏢 **Studio:** {studio}")
    if content_rating:
        active_criteria.append(f"🔞 **Rating:** {content_rating}")
    if award_tag:
        active_criteria.append(f"🏆 **Award Tag:** {award_tag}")
    if source_material_tag:
        active_criteria.append(f"📚 **Source Material:** {source_material_tag}")
    if popularity_tag:
        active_criteria.append(f"🔥 **Popularity:** {popularity_tag}")
    if cultural_impact_tag:
        active_criteria.append(f"🌍 **Cultural Impact:** {cultural_impact_tag}")
    if max_runtime:
        active_criteria.append(f"⏱️ **Max Runtime:** {max_runtime}m")
    if min_rating:
        active_criteria.append(f"⭐ **Min Rating:** {min_rating}")

    description_lines = []
    if active_criteria:
        description_lines.append("**Search Criteria:**")
        for item in active_criteria:
            description_lines.append(f"• {item}")
        description_lines.append("")  # Spacing
    
    # Display Inferred Routing Filters if query_routing inferred any structured filters
    routing = res.get("data", {}).get("query_routing", {})
    inferred_lines = []
    if routing.get("inferred_brand"):
        inferred_lines.append(f"🏢 **Brand:** {routing['inferred_brand']}")
    if routing.get("inferred_franchise"):
        inferred_lines.append(f"📦 **Franchise:** {routing['inferred_franchise']}")
    if routing.get("inferred_universe"):
        inferred_lines.append(f"🌌 **Universe:** {routing['inferred_universe']}")
    if routing.get("inferred_source_property"):
        inferred_lines.append(f"📚 **Source Property:** {routing['inferred_source_property']}")
    if routing.get("inferred_setting_location"):
        inferred_lines.append(f"🌍 **Location:** {routing['inferred_setting_location']}")
    if routing.get("inferred_studio"):
        inferred_lines.append(f"🏢 **Studio:** {routing['inferred_studio']}")
    if routing.get("inferred_award_tag"):
        inferred_lines.append(f"🏆 **Award:** {routing['inferred_award_tag']}")
    if routing.get("inferred_source_material_tag"):
        inferred_lines.append(f"📖 **Source Material:** {routing['inferred_source_material_tag']}")
    if routing.get("inferred_popularity_tag"):
        inferred_lines.append(f"🔥 **Popularity:** {routing['inferred_popularity_tag']}")
    if routing.get("inferred_cultural_impact_tag"):
        inferred_lines.append(f"🌍 **Cultural Impact:** {routing['inferred_cultural_impact_tag']}")

    if inferred_lines:
        description_lines.append("**Inferred Routing Filters:**")
        for item in inferred_lines:
            description_lines.append(f"• {item}")
        description_lines.append("")  # Spacing

    explanation = res.get("data", {}).get("explanation", {})
    explanation_notes = explanation.get("notes") or []
    if explanation_notes:
        description_lines.append("**Why these results:**")
        for note in explanation_notes[:3]:
            description_lines.append(f"• {note}")
        description_lines.append(f"• Ranked by {explanation.get('ranking', 'library relevance')}.")
        description_lines.append("")

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
        movie_line = f"**#{idx+1}** {title_year}{match_pct}\n   {details_str}"
        
        # Additional metadata: Directors, Genres
        extra_meta = []
        if m.get("directors"):
            try:
                directors_list = json.loads(m["directors"])
                if directors_list:
                    extra_meta.append(f"Dir: {', '.join(directors_list)}")
            except Exception:
                pass
        if m.get("genres"):
            try:
                genres_list = json.loads(m["genres"])
                if genres_list:
                    extra_meta.append(f"Genres: {', '.join(genres_list)}")
            except Exception:
                pass
        
        if extra_meta:
            movie_line += f"\n   * {', '.join(extra_meta)} *"
            
        # Additional TMDB/Enrichment metadata: Brand, Franchise, Universe
        tmdb_meta = []
        if m.get("franchise_tags"):
            try:
                f_list = json.loads(m["franchise_tags"])
                if f_list:
                    tmdb_meta.append(f"Franchise: {', '.join(f_list)}")
            except Exception:
                pass
        if m.get("brand_tags"):
            try:
                b_list = json.loads(m["brand_tags"])
                if b_list:
                    tmdb_meta.append(f"Brand: {', '.join(b_list)}")
            except Exception:
                pass
        if m.get("universe_tags"):
            try:
                u_list = json.loads(m["universe_tags"])
                if u_list:
                    tmdb_meta.append(f"Universe: {', '.join(u_list)}")
            except Exception:
                pass
                
        if tmdb_meta:
            movie_line += f"\n   * {' | '.join(tmdb_meta)} *"

        match_reason = m.get("match_reason")
        if match_reason:
            movie_line += f"\n   Why: {match_reason}"

        # Tagline / Synopsis preview
        tagline = m.get("tagline")
        synopsis = m.get("synopsis")
        if tagline:
            movie_line += f'\n   _"{tagline}"_'
        elif synopsis:
            truncated_syn = synopsis.strip()
            if len(truncated_syn) > 120:
                truncated_syn = truncated_syn[:117].rstrip() + "..."
            movie_line += f'\n   💬 "{truncated_syn}"'
            
        description_lines.append(movie_line)

    embed.description = "\n\n".join(description_lines)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="movie", description="Show a detailed movie database card")
@app_commands.describe(
    title="Movie title to look up",
    year="Release year, useful when multiple movies share a title"
)
@in_allowed_channel()
async def slash_movie(
    interaction: discord.Interaction,
    title: str,
    year: Optional[int] = None
):
    await interaction.response.defer()

    matches = LibraryItemRepository.search_by_normalized_title(normalize_title(title))
    if year:
        matches = [m for m in matches if m.get("year") == year]

    if not matches:
        await interaction.followup.send(content=f"No movie found for `{title}`{f' ({year})' if year else ''}.")
        return

    target_norm = normalize_title(title)
    exact_matches = [m for m in matches if normalize_title(m.get("title") or "") == target_norm]
    if year and exact_matches:
        matches = exact_matches

    if len(matches) > 1 and not exact_matches:
        options = []
        for m in matches[:8]:
            options.append(f"- **{m.get('title')}** ({m.get('year') or 'N/A'})")
        await interaction.followup.send(
            content=(
                f"Multiple movies matched `{title}`. Try `/movie` again with a year.\n"
                + "\n".join(options)
            )
        )
        return

    item = (exact_matches or matches)[0]
    await ensure_poster_url(item)
    await interaction.followup.send(embed=build_movie_detail_embed(item))


@bot.tree.command(name="recommend", description="Get personalized movie recommendations based on viewing history")
@app_commands.describe(
    user="Filter watch history by username (optional)",
    limit="Max recommendations to return (default 5)"
)
@app_commands.checks.cooldown(1, 5.0, key=lambda i: (i.guild_id, i.user.id))
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


@bot.tree.command(name="ask", description="Ask conversational questions about your movie library using natural language")
@app_commands.checks.cooldown(1, 5.0, key=lambda i: (i.guild_id, i.user.id))
@in_allowed_channel()
async def slash_ask(interaction: discord.Interaction, question: str):
    await interaction.response.defer()
    
    # Build known_users mapping
    known_users = {}
    if interaction.guild:
        for m in interaction.guild.members:
            if m.bot:
                continue
            known_users[m.name] = str(m.id)
            known_users[m.display_name] = str(m.id)
            if hasattr(m, "nick") and m.nick:
                known_users[m.nick] = str(m.id)
    else:
        known_users = {interaction.user.display_name: str(interaction.user.id)}

    res = await ask_library_tool(
        question=question,
        discord_user_id=str(interaction.user.id),
        known_users=known_users
    )
    if not res["ok"]:
        await interaction.followup.send(content=f"❌ Error: {res['error']['message']}")
        return

    data = res["data"]
    answer = data["answer"]
    cited_ids = data.get("cited_movie_ids", [])
    external_recs = data.get("external_recommendations", [])

    embed = discord.Embed(
        title="💬 Library Assistant",
        description=answer,
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"Question: {question}")

    if cited_ids:
        cited_lines = []
        for m_id in cited_ids:
            movie = LibraryItemRepository.get_by_id(m_id)
            if movie:
                year_part = f" ({movie['year']})" if movie.get('year') is not None else ""
                cited_lines.append(f"• **{movie['title']}**{year_part}")
        if cited_lines:
            embed.add_field(name="📚 Cited Movies", value="\n".join(cited_lines), inline=False)

    view = CitedMoviesView(cited_ids, external_recs) if cited_ids or external_recs else None
    msg = await interaction.followup.send(embed=embed, view=view)
    try:
        thread_name = f"💬 Chat: {question[:50]}"
        if not thread_name.strip():
            thread_name = "💬 Chat: Library Assistant"

        # Check if the interaction has guild info and the channel supports thread creation.
        # When sending via interaction.followup.send, the returned WebhookMessage might
        # not have its 'guild' attribute set, raising "This message does not have guild info attached."
        # If msg.guild is None, we delegate thread creation to the channel itself.
        if (
            interaction.guild
            and interaction.channel
            and hasattr(interaction.channel, "create_thread")
            and not isinstance(interaction.channel, (discord.Thread, discord.DMChannel))
        ):
            if getattr(msg, "guild", None) is not None:
                await msg.create_thread(
                    name=thread_name,
                    auto_archive_duration=60
                )
            else:
                await interaction.channel.create_thread(
                    name=thread_name,
                    message=msg,
                    auto_archive_duration=60
                )
        else:
            await msg.create_thread(
                name=thread_name,
                auto_archive_duration=60
            )
    except Exception as e:
        print(f"[Bot] Failed to create thread for ask response: {e}")



# User Profile & Memory Settings UI

class EditPlexUsernameModal(discord.ui.Modal, title="Edit Plex Username"):
    username = discord.ui.TextInput(
        label="Plex Username",
        placeholder="Enter your Plex username...",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        plex_user = self.username.value.strip()
        discord_user_id = str(interaction.user.id)

        # Claim locking check: is this plex username already claimed by another user?
        existing = UserProfileRepository.get_by_plex_username(plex_user)
        if existing and existing["discord_user_id"] != discord_user_id:
            await interaction.response.send_message(
                content=f"❌ The Plex username `{plex_user}` is already mapped to another Discord user. If this is an error, please contact an administrator.",
                ephemeral=True
            )
            return

        # Upsert the profile
        UserProfileRepository.upsert(discord_user_id=discord_user_id, plex_username=plex_user)
        
        await interaction.response.send_message(
            content=f"✅ Successfully mapped your Plex username to `{plex_user}`!",
            ephemeral=True
        )
        if interaction.message:
            embed = await build_profile_embed(interaction.user)
            await interaction.message.edit(embed=embed)


class EditTasteOverridesModal(discord.ui.Modal, title="Edit Taste Overrides"):
    taste = discord.ui.TextInput(
        label="Manual Taste Overrides",
        style=discord.TextStyle.paragraph,
        placeholder="e.g. Loves Canadian indie movies. Dislikes jump scares and horror.",
        required=True,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        taste_str = self.taste.value.strip()
        discord_user_id = str(interaction.user.id)

        UserProfileRepository.upsert(discord_user_id=discord_user_id, custom_taste_notes=taste_str)
        
        await interaction.response.send_message(
            content="✅ Successfully updated your manual taste overrides!",
            ephemeral=True
        )
        if interaction.message:
            embed = await build_profile_embed(interaction.user)
            await interaction.message.edit(embed=embed)


class DeleteMemoriesSelect(discord.ui.Select):
    def __init__(self, memories: List[Dict[str, Any]]):
        options = []
        for m in memories[:25]:  # Discord select menu limit is 25 options
            fact_label = m["fact"]
            if len(fact_label) > 90:
                fact_label = fact_label[:87] + "..."
            options.append(discord.SelectOption(
                label=fact_label,
                value=str(m["id"]),
                description=f"Category: {m['category']}"
            ))
            
        super().__init__(
            placeholder="Select a memory fact to delete...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        memory_id = int(self.values[0])
        try:
            UserMemoryRepository.delete(memory_id)
            await interaction.response.send_message(
                content="✅ Memory deleted successfully!",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                content=f"❌ Failed to delete memory: {e}",
                ephemeral=True
            )


class DeleteMemoriesView(discord.ui.View):
    def __init__(self, memories: List[Dict[str, Any]]):
        super().__init__(timeout=180)
        self.add_item(DeleteMemoriesSelect(memories))


class ProfileConfirmResetView(discord.ui.View):
    def __init__(self, original_user: discord.User):
        super().__init__(timeout=60)
        self.original_user = original_user

    @discord.ui.button(label="Yes, Reset Everything", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_user.id:
            await interaction.response.send_message("❌ This is not your profile.", ephemeral=True)
            return

        discord_user_id = str(interaction.user.id)
        # Clear profile repository entry
        UserProfileRepository.delete(discord_user_id)
        # Clear all user memories
        memories = UserMemoryRepository.get_all_for_user(discord_user_id)
        for m in memories:
            UserMemoryRepository.delete(m["id"])
            
        await interaction.response.send_message(
            content="🗑️ Your profile settings, Plex mapping, and atomic memories have been completely reset.",
            ephemeral=True
        )
        
        self.stop()
        if interaction.message:
            embed = await build_profile_embed(interaction.user)
            await interaction.message.edit(embed=embed, view=ProfileMainView(interaction.user))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_user.id:
            await interaction.response.send_message("❌ This is not your profile.", ephemeral=True)
            return

        await interaction.response.send_message("❌ Reset cancelled.", ephemeral=True)
        self.stop()


class ProfileMainView(discord.ui.View):
    def __init__(self, user: discord.User):
        super().__init__(timeout=180)
        self.user = user

    @discord.ui.button(label="✏️ Edit Plex Username", style=discord.ButtonStyle.primary)
    async def edit_plex(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ This is not your profile.", ephemeral=True)
            return
        await interaction.response.send_modal(EditPlexUsernameModal())

    @discord.ui.button(label="📝 Edit Taste Overrides", style=discord.ButtonStyle.primary)
    async def edit_tastes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ This is not your profile.", ephemeral=True)
            return
        await interaction.response.send_modal(EditTasteOverridesModal())

    @discord.ui.button(label="🔓 Toggle Visibility", style=discord.ButtonStyle.secondary)
    async def toggle_visibility(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ This is not your profile.", ephemeral=True)
            return

        discord_user_id = str(interaction.user.id)
        profile = UserProfileRepository.get(discord_user_id)
        
        is_public = True
        if profile and profile.get("metadata_json"):
            try:
                meta = json.loads(profile["metadata_json"])
                is_public = meta.get("public_visibility", True)
            except Exception:
                pass

        new_visibility = not is_public
        new_meta = {"public_visibility": new_visibility}
        
        UserProfileRepository.upsert(
            discord_user_id=discord_user_id,
            metadata_json=json.dumps(new_meta)
        )
        
        visibility_label = "public" if new_visibility else "private"
        await interaction.response.send_message(
            content=f"🔒 Profile visibility changed to **{visibility_label}**!",
            ephemeral=True
        )
        
        embed = await build_profile_embed(interaction.user)
        await interaction.message.edit(embed=embed)

    @discord.ui.button(label="🧠 Delete Memory Facts", style=discord.ButtonStyle.secondary)
    async def delete_memory_facts(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ This is not your profile.", ephemeral=True)
            return

        discord_user_id = str(interaction.user.id)
        memories = UserMemoryRepository.get_all_for_user(discord_user_id)
        
        if not memories:
            await interaction.response.send_message(
                content="❌ You do not have any saved memories to delete.",
                ephemeral=True
            )
            return

        view = DeleteMemoriesView(memories)
        await interaction.response.send_message(
            content="Please choose a memory fact to delete from the list below:",
            view=view,
            ephemeral=True
        )

    @discord.ui.button(label="❌ Reset Profile", style=discord.ButtonStyle.danger)
    async def reset_profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ This is not your profile.", ephemeral=True)
            return

        view = ProfileConfirmResetView(interaction.user)
        await interaction.response.send_message(
            content="⚠️ **Are you absolutely sure you want to delete your profile?**\nThis will permanently remove your Plex mapping, manual overrides, and all atomic memory facts stored by the bot.",
            view=view,
            ephemeral=True
        )


async def build_profile_embed(user: discord.User) -> discord.Embed:
    discord_user_id = str(user.id)
    profile = UserProfileRepository.get(discord_user_id)
    
    plex_user = "Not Mapped"
    custom_taste = "None configured"
    is_public = True
    
    if profile:
        if profile.get("plex_username"):
            plex_user = f"`{profile['plex_username']}`"
        if profile.get("custom_taste_notes"):
            custom_taste = profile["custom_taste_notes"]
            
        if profile.get("metadata_json"):
            try:
                meta = json.loads(profile["metadata_json"])
                is_public = meta.get("public_visibility", True)
            except Exception:
                pass
                
    memories = UserMemoryRepository.get_all_for_user(discord_user_id)
    mem_count = len(memories)
    
    embed = discord.Embed(
        title="👤 User Profile & Memory Settings",
        color=discord.Color.purple()
    )
    embed.add_field(name="Discord User", value=user.mention, inline=True)
    embed.add_field(name="Plex Username", value=plex_user, inline=True)
    embed.add_field(name="Banter Visibility", value="🔓 Public (Banter Enabled)" if is_public else "🔒 Private (Only Me)", inline=True)
    
    if custom_taste != "None configured":
        if len(custom_taste) > 1000:
            custom_taste = custom_taste[:997] + "..."
        embed.add_field(name="Manual Taste Overrides", value=custom_taste, inline=False)
        
    embed.add_field(name="Atomic Memories Count", value=f"`{mem_count}` memory facts", inline=True)
    
    if memories:
        mem_lines = []
        for m in memories[:10]:
            cat = m["category"].upper().replace("_", " ")
            fact_str = m["fact"]
            if len(fact_str) > 80:
                fact_str = fact_str[:77] + "..."
            mem_lines.append(f"• **[{cat}]** {fact_str}")
        if len(memories) > 10:
            mem_lines.append(f"... and {len(memories) - 10} more.")
        embed.add_field(name="Recent Extracted Tastes & Facts", value="\n".join(mem_lines), inline=False)
    else:
        embed.add_field(name="Recent Extracted Tastes & Facts", value="No atomic memories have been extracted yet. Talk to the bot to build memories naturally!", inline=False)
        
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text="Your profile preferences are used to tailor recommendations.")
    return embed


# Profile Command Group
profile_group = app_commands.Group(name="profile", description="Manage user profile, Plex mapping, and memories")

@profile_group.command(name="show", description="Show and manage your profile card interactively")
@app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
@in_allowed_channel()
async def profile_show(interaction: discord.Interaction):
    # Ensure profile exists
    UserProfileRepository.upsert(discord_user_id=str(interaction.user.id))
    
    embed = await build_profile_embed(interaction.user)
    view = ProfileMainView(interaction.user)
    await interaction.response.send_message(embed=embed, view=view)

bot.tree.add_command(profile_group)


def run_discord_client():
    token = settings.discord_token
    bot.run(token)

