"""Data models for YouTube Downloader.

This module defines Pydantic models for download tracking and status management.
"""

from enum import Enum
from time import time

from pydantic import BaseModel, Field


class DownloadStatus(str, Enum):
    """Status of a download job."""

    QUEUED = "queued"
    DOWNLOADING = "downloading"
    COMPLETE = "complete"
    ERROR = "error"


class Download(BaseModel):
    """Represents a single download job.

    Attributes:
        id: Unique identifier for the download
        channel_url: YouTube channel URL to download from
        status: Current status of the download
        progress: Download progress percentage (0.0 to 100.0)
        message: Status message or error description
        output: List of output lines from yt-dlp
        started_at: Unix timestamp when download started
    """

    model_config = {"use_enum_values": True}

    id: str
    channel_url: str
    status: DownloadStatus
    progress: float = Field(default=0.0, ge=0.0, le=100.0)
    message: str = ""
    output: list[str] = Field(default_factory=list)
    started_at: float = Field(default_factory=time)
