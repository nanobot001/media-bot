import asyncio
import os
import sys
from moviebot.config import settings
from moviebot.db.connection import init_db


def start_bot():
    """Initializes system states and runs the Discord Bot interface."""
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

    # 3. Boot Discord Application Client
    # Deferred import to prevent loading discord library during CLI executions
    from moviebot.bot.discord_app import run_discord_client
    
    try:
        run_discord_client()
    except KeyboardInterrupt:
        print("[System] Shutting down MovieMediaBot gateway gracefully.")
    except Exception as e:
        print(f"[System CRITICAL] Bot execution terminated: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    start_bot()
