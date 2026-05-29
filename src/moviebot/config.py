from __future__ import annotations
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Discord Bot Settings
    discord_token: str = ""
    discord_guild_id: Optional[int] = None
    allowed_discord_channels: str = ""  # Comma-separated list of IDs
    discord_error_channel_id: Optional[int] = None
    bot_manager_user_ids: str = ""  # Comma-separated list of Discord user IDs
    bot_manager_role_ids: str = ""  # Comma-separated list of Discord role IDs
    job_resolver_poll_interval: int = 60  # Background task resolution loop interval in seconds

    @property
    def bot_manager_users_list(self) -> list[int]:
        if not self.bot_manager_user_ids:
            return []
        try:
            return [int(x.strip()) for x in self.bot_manager_user_ids.split(",") if x.strip()]
        except ValueError:
            return []

    @property
    def bot_manager_roles_list(self) -> list[int]:
        if not self.bot_manager_role_ids:
            return []
        try:
            return [int(x.strip()) for x in self.bot_manager_role_ids.split(",") if x.strip()]
        except ValueError:
            return []

    @property
    def allowed_channels_list(self) -> list[int]:
        if not self.allowed_discord_channels:
            return []
        try:
            return [int(x.strip()) for x in self.allowed_discord_channels.split(",") if x.strip()]
        except ValueError:
            return []


    # Prowlarr Settings
    prowlarr_url: str = "http://host.docker.internal:9696"
    prowlarr_api_key: str = ""

    # AllDebrid Settings
    alldebrid_api_key: str = ""

    # Plex Settings
    plex_url: str = "http://localhost:32400"
    plex_token: str = ""

    # Tautulli Settings
    tautulli_url: str = "http://localhost:8181"
    tautulli_api_key: str = ""
    tautulli_webhook_secret: str = "default_secret"

    # IDM Bridge Settings
    idm_bridge_url: str = "http://127.0.0.1:8765"
    idm_bridge_secret: str = ""

    # Paths & Storage
    database_path: str = "data/moviebot.sqlite3"
    output_dir: str = r"F:\_temp\movies"


# Global settings instance
settings = Settings()
