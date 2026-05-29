import asyncio
import sys
import uvicorn
from moviebot.config import settings
from moviebot.db.connection import init_db
from moviebot.api.webhook import app as webhook_app


async def run_bot_and_server():
    """Concurrently runs the FastAPI webhook server and the Discord Client."""
    from moviebot.bot.discord_app import bot

    config = uvicorn.Config(
        webhook_app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        loop="asyncio"
    )
    server = uvicorn.Server(config)

    print("[System] Starting FastAPI Webhook server on port 8000...")
    print("[System] Starting Discord Gateway connection...")

    try:
        await asyncio.gather(
            server.serve(),
            bot.start(settings.discord_token)
        )
    except asyncio.CancelledError:
        print("[System] Async tasks cancelled, shutting down.")
    finally:
        if not bot.is_closed():
            print("[System] Closing Discord bot connection...")
            await bot.close()
        server.should_exit = True
        print("[System] Shutdown complete.")


def start_bot():
    """Initializes system states and runs the bot lifecycle."""
    print("=== Starting MovieMediaBot App Lifecycle ===")
    
    # 1. Ensure DB and state tables exist
    try:
        init_db()
        print("[System] Database state mirrors initialized successfully.")
    except Exception as e:
        print(f"[System ERROR] Failed to initialize SQLite tables: {str(e)}", file=sys.stderr)
        sys.exit(1)

    # 2. Check token config
    if not settings.discord_token:
        print("[System ERROR] DISCORD_TOKEN is missing in the environment. Exiting.", file=sys.stderr)
        sys.exit(1)

    # 3. Boot Discord Application Client & Web Server
    try:
        asyncio.run(run_bot_and_server())
    except KeyboardInterrupt:
        print("[System] Shutting down MovieMediaBot gateway gracefully.")
    except Exception as e:
        print(f"[System CRITICAL] Bot execution terminated: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    start_bot()
