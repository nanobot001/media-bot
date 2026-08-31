from __future__ import annotations
from typing import Optional, List
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
    discord_playback_channel_id: Optional[int] = None
    bot_manager_user_ids: str = ""  # Comma-separated list of Discord user IDs
    bot_manager_role_ids: str = ""  # Comma-separated list of Discord role IDs
    job_resolver_poll_interval: int = 60  # Background task resolution loop interval in seconds

    @property
    def bot_manager_users_list(self) -> List[int]:
        if not self.bot_manager_user_ids:
            return []
        try:
            return [int(x.strip()) for x in self.bot_manager_user_ids.split(",") if x.strip()]
        except ValueError:
            return []

    @property
    def bot_manager_roles_list(self) -> List[int]:
        if not self.bot_manager_role_ids:
            return []
        try:
            return [int(x.strip()) for x in self.bot_manager_role_ids.split(",") if x.strip()]
        except ValueError:
            return []

    @property
    def allowed_channels_list(self) -> List[int]:
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
    ignored_plex_sections: str = ""
    plex_domain_mapping: str = ""

    # Tautulli Settings
    tautulli_url: str = "http://localhost:8181"
    tautulli_api_key: str = ""
    tautulli_webhook_secret: str = "default_secret"

    # IDM Bridge Settings
    idm_bridge_url: str = "http://127.0.0.1:8765"
    idm_bridge_secret: str = ""

    # Paths & Storage
    database_path: str = "data/moviebot.sqlite3"
    anime_database_path: str = "data/animebot.sqlite3"
    tv_database_path: str = "data/tvbot.sqlite3"
    tv_classic_database_path: str = "data/tvclassicbot.sqlite3"
    output_dir: str = r"F:\_temp\movies"
    tv_output_dir: str = r"F:\_temp\tv"
    tv_classic_output_dir: str = r"F:\temp\Classic Tv"
    media_watcher_state_path: str = "C:\\Users\\antho\\Code\\media-watcher\\state\\watcher-state.json"
    vlc_path: Optional[str] = None

    # Isolated MediaFlow capability pilot (disabled unless explicitly used)
    mediaflow_url: str = "http://127.0.0.1:8888"
    mediaflow_api_password: str = ""
    mediaflow_timeout_seconds: float = 20.0
    mediaflow_pilot_enabled: bool = False
    mediaflow_pilot_fixture_base_url: str = "http://host.docker.internal:18765"
    mediaflow_production_enabled: bool = False
    mediaflow_expected_version: str = "2.4.9"
    mediaflow_session_ttl_seconds: int = 900
    mediaflow_max_heavy_transcode_size_bytes: int = 6 * 1024 * 1024 * 1024
    mediaflow_max_heavy_transcode_duration_seconds: float = 7200.0
    # Capacity reservations are conservative until local benchmark profiles
    # are supplied through MEDIAFLOW_CAPACITY_PROFILES_JSON.
    mediaflow_capacity_cpu_cores: float = 4.0
    mediaflow_capacity_memory_mb: int = 2048
    mediaflow_capacity_gpu_percent: float = 100.0
    mediaflow_capacity_encoder_slots: int = 1
    mediaflow_capacity_max_heavy_sessions: int = 1
    mediaflow_capacity_safety_factor: float = 1.25
    mediaflow_capacity_baseline_cpu_cores: float = 0.5
    mediaflow_capacity_baseline_memory_mb: int = 256
    mediaflow_capacity_baseline_gpu_percent: float = 0.0
    mediaflow_capacity_profiles_json: str = ""
    # Controls only sanitized diagnostic visibility/retention. Safety and
    # structured minimal failure codes remain active in every mode.
    mediaflow_diagnostics_mode: str = "summary"


    # Movie Metadata Providers
    tmdb_api_key: str = ""
    tmdb_bearer_token: str = ""
    tmdb_base_url: str = "https://api.themoviedb.org/3"

    # Google Gemini & Ollama Embeddings
    gemini_api_key: str = ""
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_enrichment_model: str = "gemini-2.5-flash"
    embedding_dim: int = 768
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "nomic-embed-text"
    rag_persona: str = (
        "You are a passionate, knowledgeable movie enthusiast helping friends discover "
        "films in their shared library. Be warm, direct, and conversational. Avoid formal "
        "or academic language. If you're excited about a movie, say so."
    )


# Global settings instance
settings = Settings()
