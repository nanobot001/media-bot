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

    # IDM Bridge Settings
    idm_bridge_url: str = "http://127.0.0.1:8765"
    idm_bridge_secret: str = ""

    # Paths & Storage
    database_path: str = "data/moviebot.sqlite3"
    output_dir: str = r"F:\_temp\movies"


# Global settings instance
settings = Settings()
