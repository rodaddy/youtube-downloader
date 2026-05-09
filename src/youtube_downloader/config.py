"""Configuration management for YouTube Downloader.

This module provides a centralized configuration class using pydantic-settings
to manage application settings from environment variables and .env files.
"""

import json
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent.parent


def _get_runtime_config_path() -> Path:
    """Get path to runtime config file."""
    return _get_project_root() / "data" / "runtime_config.json"


def _load_runtime_overrides() -> dict[str, Any]:
    """Load runtime configuration overrides from JSON file."""
    config_path = _get_runtime_config_path()
    if config_path.exists():
        try:
            with open(config_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


class Settings(BaseSettings):
    """Application configuration loaded from environment variables.

    All settings can be overridden via environment variables or a .env file.

    Attributes:
        download_dir: Directory where downloaded videos will be stored
        videos_per_channel: Number of recent videos to download per channel
        max_quality: yt-dlp format selector for maximum video quality
        host: Server host address to bind to
        port: Server port number
        debug: Enable debug mode for development
    """

    download_dir: Path = Field(
        default=Path.home() / "Downloads" / "youtube_stuff",
        description="Directory where videos will be downloaded",
    )
    videos_per_channel: int = Field(
        default=2,
        ge=1,
        description="Number of most recent videos to download per channel",
    )
    max_quality: str = Field(
        default="best[height<=1080]",
        description="yt-dlp format selector for video quality (default/scheduled downloads)",
    )
    max_quality_best: str = Field(
        default="bestvideo+bestaudio/best",
        description="yt-dlp format selector for best quality (manual downloads, no limits)",
    )
    host: str = Field(default="0.0.0.0", description="Server host address")
    port: int = Field(
        default=5000,
        ge=1,
        le=65535,
        description="Server port number",
    )
    debug: bool = Field(default=True, description="Enable debug mode")

    # Plex integration settings (optional)
    plex_url: str | None = Field(
        default=None,
        description="Plex server URL (e.g., http://10.71.1.35:32400)",
    )
    plex_token: str | None = Field(
        default=None,
        description="Plex authentication token",
    )
    plex_library_id: int | None = Field(
        default=None,
        description="Plex library section ID for YouTube videos",
    )

    # Authentication settings (optional)
    admin_username: str | None = Field(
        default=None,
        description="Admin username for web UI (leave blank to disable auth)",
    )
    admin_password: str | None = Field(
        default=None,
        description="Admin password for web UI (leave blank to disable auth)",
    )
    auth_bypass_local: bool = Field(
        default=True,
        description="Bypass authentication for local network requests",
    )

    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("download_dir", mode="before")
    @classmethod
    def expand_download_dir(cls, v: str | Path) -> Path:
        """Expand user home directory and resolve relative paths."""
        path = Path(v).expanduser() if isinstance(v, str) else v.expanduser()

        # If relative path, make it relative to project root
        if not path.is_absolute():
            project_root = Path(__file__).parent.parent.parent
            path = project_root / path

        return path

    @property
    def project_root(self) -> Path:
        """Project root directory (where run.py, channels.txt, etc. live)."""
        return Path(__file__).parent.parent.parent

    @property
    def channels_file(self) -> Path:
        """Path to the channels.txt file in project root."""
        return self.project_root / "channels.txt"

    @property
    def log_dir(self) -> Path:
        """Path to the logs directory."""
        return self.project_root / "logs"

    @property
    def archive_file(self) -> Path:
        """Path to the yt-dlp download archive file."""
        return self.download_dir / ".yt-dlp-archive.txt"

    @property
    def plex_enabled(self) -> bool:
        """Check if Plex integration is configured."""
        return bool(self.plex_url and self.plex_token and self.plex_library_id is not None)

    @property
    def auth_enabled(self) -> bool:
        """Check if web UI authentication is configured."""
        return bool(self.admin_username and self.admin_password)

    def ensure_download_dir(self) -> None:
        """Create the download directory if it doesn't exist."""
        logger.debug(f"⚙️  ENSURE_DOWNLOAD_DIR: {self.download_dir}")
        if self.download_dir.exists():
            logger.debug(f"⚙️  Directory already exists: {self.download_dir}")
        else:
            logger.info(f"⚙️  Creating directory: {self.download_dir}")
        self.download_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("⚙️  ENSURE_DOWNLOAD_DIR: Complete")

    def update_runtime_config(
        self,
        download_dir: Path | str | None = None,
        videos_per_channel: int | None = None,
    ) -> None:
        """Update runtime configuration and persist to disk.

        Args:
            download_dir: New download directory path
            videos_per_channel: New videos per channel limit
        """
        logger.info(f"⚙️  UPDATE_RUNTIME_CONFIG: download_dir={download_dir}, videos_per_channel={videos_per_channel}")

        config_path = _get_runtime_config_path()
        logger.debug(f"⚙️  Config path: {config_path}")
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing config
        current = _load_runtime_overrides()
        logger.debug(f"⚙️  Current overrides: {current}")

        # Update with new values
        if download_dir is not None:
            path = Path(download_dir).expanduser()
            if not path.is_absolute():
                path = self.project_root / path
            logger.info(f"⚙️  Updating download_dir: {self.download_dir} → {path}")
            current["download_dir"] = str(path)
            # Update in-memory setting using object.__setattr__ to bypass frozen
            object.__setattr__(self, "download_dir", path)

        if videos_per_channel is not None:
            logger.info(f"⚙️  Updating videos_per_channel: {self.videos_per_channel} → {videos_per_channel}")
            current["videos_per_channel"] = videos_per_channel
            object.__setattr__(self, "videos_per_channel", videos_per_channel)

        # Save to disk
        logger.debug(f"⚙️  Saving to {config_path}: {current}")
        with open(config_path, "w") as f:
            json.dump(current, f, indent=2)
        logger.info("⚙️  UPDATE_RUNTIME_CONFIG: Complete")

    @classmethod
    def load_with_overrides(cls) -> "Settings":
        """Load settings with runtime overrides applied."""
        logger.debug("⚙️  LOAD_WITH_OVERRIDES: Loading runtime config...")
        overrides = _load_runtime_overrides()
        logger.info(f"⚙️  LOAD_WITH_OVERRIDES: Applying overrides: {overrides}")
        settings = cls(**overrides)
        logger.debug(f"⚙️  LOAD_WITH_OVERRIDES: download_dir={settings.download_dir}")
        logger.debug(f"⚙️  LOAD_WITH_OVERRIDES: videos_per_channel={settings.videos_per_channel}")
        return settings
