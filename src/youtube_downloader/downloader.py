"""Download management for YouTube Downloader.

This module provides the DownloadManager class that handles channel downloads
using yt-dlp with proper logging and progress tracking.
"""

import json
import queue
import re
import subprocess
import threading
import time as time_module
import uuid
from pathlib import Path
from time import time
from typing import TYPE_CHECKING, Optional

from loguru import logger

from .config import Settings
from .models import Download, DownloadStatus
from .plex import PlexIntegration

if TYPE_CHECKING:
    from .database import Database


# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY_BASE = 5  # seconds
TIMEOUT_SECONDS = 600  # 10 minutes per attempt

# Queue configuration
MAX_CONCURRENT_DOWNLOADS = 1  # Download 1 channel at a time to avoid rate limits
DOWNLOAD_START_DELAY = 10  # Wait 10 seconds between starting downloads


def parse_ytdlp_error(output_lines: list[str]) -> tuple[str, bool]:
    """Parse yt-dlp error output to extract meaningful error message.

    Args:
        output_lines: List of output lines from yt-dlp

    Returns:
        Tuple of (error_message, is_retryable)
    """
    # Get last 20 lines where errors usually appear
    relevant_lines = output_lines[-20:] if len(output_lines) > 20 else output_lines

    # Common error patterns
    error_patterns = {
        # Retryable errors
        r"ERROR: unable to download video data: HTTP Error 429": (
            "Rate limited by YouTube - will retry with backoff",
            True,
        ),
        r"ERROR:.*timed out": ("Network timeout - will retry", True),
        r"ERROR:.*Connection reset": ("Connection lost - will retry", True),
        r"ERROR:.*temporarily unavailable": ("Temporarily unavailable - will retry", True),
        r"urlopen error \[Errno -3\]": ("DNS resolution failed - will retry", True),
        r"urlopen error \[Errno 8\]": ("Network error - will retry", True),
        # Non-retryable errors
        r"ERROR: This video is unavailable": (
            "Video unavailable (deleted/private)",
            False,
        ),
        r"ERROR: Private video": ("Private video - cannot download", False),
        r"ERROR: Video unavailable": ("Video unavailable", False),
        r"ERROR:.*Sign in to confirm your age": (
            "Age-restricted video (requires login)",
            False,
        ),
        r"ERROR:.*Join this channel to get access to members-only content": (
            "Members-only content (skipped)",
            False,
        ),
        r"ERROR: This live event will begin in": (
            "Live stream not started yet",
            False,
        ),
        r"ERROR:.*Premieres in": ("Premiere not started yet", False),
        r"ERROR: Unsupported URL": ("Invalid/unsupported URL", False),
        r"ERROR:.*This video has been removed": ("Video removed", False),
        r"ERROR:.*no video formats": ("No downloadable formats found", False),
        r"ERROR: unable to download video data: HTTP Error 416": (
            "Resume error (file likely complete)",
            False,
        ),
    }

    # Search for known error patterns
    for line in reversed(relevant_lines):
        for pattern, (message, retryable) in error_patterns.items():
            if re.search(pattern, line, re.IGNORECASE):
                logger.debug(f"Matched error pattern: {pattern}")
                return message, retryable

    # If no specific pattern found, look for generic ERROR lines
    for line in reversed(relevant_lines):
        if line.startswith("ERROR:"):
            # Extract just the error message without the ERROR: prefix
            error_msg = line[6:].strip()
            # Most generic errors are worth retrying
            return f"yt-dlp error: {error_msg}", True

    # Fallback
    return "Download failed (see logs for details)", True


class DownloadManager:
    """Manages YouTube channel downloads with progress tracking.

    Attributes:
        settings: Application configuration settings
        database: Optional database for tracking downloads
        plex: Optional Plex integration for thumbnail uploads
    """

    def __init__(
        self, settings: Settings, database: Optional["Database"] = None
    ) -> None:
        """Initialize the download manager.

        Args:
            settings: Application configuration settings
            database: Optional database for tracking downloads
        """
        self.settings = settings
        self.database = database
        self._downloads: dict[str, Download] = {}

        # Initialize download queue and worker thread
        self._download_queue: queue.Queue = queue.Queue()
        self._queue_worker_running = True
        self._queue_worker_thread = threading.Thread(
            target=self._process_download_queue,
            daemon=True,
        )
        self._queue_worker_thread.start()
        logger.info(f"Download queue initialized (max concurrent: {MAX_CONCURRENT_DOWNLOADS}, delay: {DOWNLOAD_START_DELAY}s)")

        # Initialize Plex integration if configured
        self.plex: Optional[PlexIntegration] = None
        if settings.plex_enabled:
            try:
                self.plex = PlexIntegration(
                    url=settings.plex_url,  # type: ignore
                    token=settings.plex_token,  # type: ignore
                    library_id=settings.plex_library_id,  # type: ignore
                )
                logger.info("Plex integration enabled")
            except Exception as e:
                logger.warning(f"Failed to initialize Plex integration: {e}")

    def _process_download_queue(self) -> None:
        """Process downloads from the queue one at a time (runs in background thread).

        This worker thread pulls download jobs from the queue and executes them
        with a delay between each download to avoid hitting YouTube rate limits.
        """
        logger.info("Download queue worker started")
        first_download = True

        while self._queue_worker_running:
            try:
                # Wait for next download (with timeout to allow checking stop flag)
                channel_url, download_id = self._download_queue.get(timeout=1.0)

                # Add delay between downloads (except for first one)
                if not first_download:
                    logger.info(f"Waiting {DOWNLOAD_START_DELAY}s before starting next download...")
                    time_module.sleep(DOWNLOAD_START_DELAY)
                first_download = False

                # Execute the download
                logger.info(f"Queue: Processing download {download_id}")
                self._download_channel(channel_url, download_id)

                # Mark task as done
                self._download_queue.task_done()

            except queue.Empty:
                # No downloads in queue, continue waiting
                continue
            except Exception as e:
                logger.exception(f"Queue worker error: {e}")
                try:
                    self._download_queue.task_done()
                except ValueError:
                    pass

        logger.info("Download queue worker stopped")

    def load_channels(self) -> list[str]:
        """Load channel URLs from channels.txt file.

        Returns:
            List of channel URLs, one per line
        """
        channels_file = self.settings.channels_file
        if not channels_file.exists():
            logger.warning(f"Channels file not found: {channels_file}")
            return []

        channels = [
            line.strip()
            for line in channels_file.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        logger.info(f"Loaded {len(channels)} channels from {channels_file}")
        return channels

    def start_download(self, channel_url: str) -> str:
        """Start downloading videos from a channel (queues the download).

        Args:
            channel_url: YouTube channel URL

        Returns:
            Unique download ID for tracking
        """
        download_id = str(uuid.uuid4())

        download = Download(
            id=download_id,
            channel_url=channel_url,
            status=DownloadStatus.QUEUED,
            started_at=time(),
        )
        self._downloads[download_id] = download

        # Extract channel name for better logging
        channel_name = channel_url.split("@")[1] if "@" in channel_url else channel_url.split("/")[-1]

        # Add to queue instead of spawning thread directly
        queue_size = self._download_queue.qsize()
        logger.info(f"[{channel_name}] Queued download {download_id} (queue position: {queue_size + 1})")
        self._download_queue.put((channel_url, download_id))

        return download_id

    def _download_channel(self, channel_url: str, download_id: str) -> None:
        """Download videos from a channel with retry logic (runs in background thread).

        Args:
            channel_url: YouTube channel URL
            download_id: Unique download ID for tracking
        """
        download = self._downloads.get(download_id)
        if not download:
            logger.error(f"Download {download_id} not found")
            return

        # Extract channel name for better logging
        channel_name = channel_url.split("@")[1] if "@" in channel_url else channel_url.split("/")[-1]

        # Retry loop
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                download.status = DownloadStatus.DOWNLOADING
                download.output = []

                # Ensure download directory exists
                self.settings.ensure_download_dir()

                # Plex-compatible naming for YouTube Agent:
                # {channel} [{channel_id}]/{title} [{video_id}]/{title} [{video_id}].{ext}
                # Each video in its own folder for easier cleanup
                output_template = str(
                    self.settings.download_dir
                    / "%(uploader)s [%(channel_id)s]"
                    / "%(title)s [%(id)s]"
                    / "%(title)s [%(id)s].%(ext)s"
                )

                cmd = [
                    "yt-dlp",
                    "--format",
                    self.settings.max_quality,
                    "--max-downloads",
                    str(self.settings.videos_per_channel),  # Download N successful videos (not just first N)
                    "--download-archive",
                    str(self.settings.archive_file),
                    "--output",
                    output_template,
                    # Metadata for Plex
                    "--embed-metadata",
                    "--embed-thumbnail",
                    "--write-info-json",
                    # External thumbnail for Plex YouTube Agent
                    "--write-thumbnail",
                    "--convert-thumbnails",
                    "jpg",
                    # Error handling
                    "--ignore-errors",  # Continue downloading playlist even if some videos fail
                    "--no-continue",    # Don't resume partial downloads (prevents HTTP 416 errors)
                    # Other options
                    "--progress",
                    "--verbose",  # More detailed error messages
                    f"{channel_url}/videos",
                ]

                logger.info(
                    f"[{channel_name}] Download attempt {attempt}/{MAX_RETRIES} (ID: {download_id})"
                )
                logger.debug(f"Command: {' '.join(cmd)}")

                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )

                # Capture output with timeout
                start_time = time()
                for line in process.stdout:  # type: ignore
                    line = line.strip()
                    download.output.append(line)

                    # Log important lines
                    if any(
                        keyword in line
                        for keyword in ["ERROR", "WARNING", "[download]", "Downloading"]
                    ):
                        logger.debug(f"[{channel_name}] {line}")

                    # Parse progress
                    if "[download]" in line and "%" in line:
                        try:
                            parts = line.split()
                            for part in parts:
                                if "%" in part:
                                    progress_str = part.replace("%", "")
                                    download.progress = float(progress_str)
                                    break
                        except (ValueError, IndexError) as e:
                            logger.debug(f"Could not parse progress from: {line} - {e}")

                    # Timeout check
                    if time() - start_time > TIMEOUT_SECONDS:
                        logger.error(
                            f"[{channel_name}] Download timeout after {TIMEOUT_SECONDS}s"
                        )
                        process.kill()
                        raise TimeoutError(
                            f"Download exceeded {TIMEOUT_SECONDS}s timeout"
                        )

                process.wait()

                if process.returncode == 0:
                    download.status = DownloadStatus.COMPLETE
                    download.message = "Download complete"
                    logger.info(f"[{channel_name}] Download completed successfully")

                    # Rename thumbnails for Plex Local Media Assets compatibility
                    self._rename_thumbnails_for_plex()

                    # Track new videos in database and run cleanup
                    if self.database:
                        self._scan_and_track_videos(channel_url)

                    # Upload thumbnails to Plex if integration is enabled
                    if self.plex:
                        try:
                            uploaded = self.plex.sync_thumbnails(
                                self.settings.download_dir
                            )
                            logger.info(f"Plex sync: uploaded {uploaded} thumbnails")
                        except Exception as e:
                            logger.warning(f"Plex thumbnail sync failed: {e}")

                    return  # Success - exit retry loop

                else:
                    # Parse error from output
                    error_msg, is_retryable = parse_ytdlp_error(download.output)

                    # Log last 15 lines of output for debugging
                    last_lines = download.output[-15:] if len(download.output) > 15 else download.output
                    logger.error(
                        f"[{channel_name}] yt-dlp failed with exit code {process.returncode}"
                    )
                    logger.error(f"[{channel_name}] Error: {error_msg}")
                    logger.error(
                        f"[{channel_name}] Last output lines:\n" + "\n".join(last_lines)
                    )

                    # Decide whether to retry
                    if not is_retryable or attempt == MAX_RETRIES:
                        download.status = DownloadStatus.ERROR
                        download.message = error_msg
                        logger.error(
                            f"[{channel_name}] Permanent failure: {error_msg}"
                        )
                        return  # Give up

                    # Exponential backoff before retry
                    retry_delay = RETRY_DELAY_BASE * (2 ** (attempt - 1))
                    download.message = f"{error_msg} (retry {attempt}/{MAX_RETRIES} in {retry_delay}s)"
                    logger.warning(
                        f"[{channel_name}] Retrying in {retry_delay}s... (attempt {attempt + 1}/{MAX_RETRIES})"
                    )
                    time_module.sleep(retry_delay)

            except TimeoutError as e:
                logger.error(f"[{channel_name}] Timeout: {e}")
                if attempt == MAX_RETRIES:
                    download.status = DownloadStatus.ERROR
                    download.message = f"Download timeout after {TIMEOUT_SECONDS}s"
                    return
                else:
                    retry_delay = RETRY_DELAY_BASE * (2 ** (attempt - 1))
                    download.message = f"Timeout - retry {attempt}/{MAX_RETRIES} in {retry_delay}s"
                    logger.warning(
                        f"[{channel_name}] Retrying after timeout in {retry_delay}s..."
                    )
                    time_module.sleep(retry_delay)

            except Exception as e:
                logger.exception(f"[{channel_name}] Unexpected error: {e}")
                if attempt == MAX_RETRIES:
                    download.status = DownloadStatus.ERROR
                    download.message = f"Error: {str(e)}"
                    return
                else:
                    retry_delay = RETRY_DELAY_BASE * (2 ** (attempt - 1))
                    download.message = f"Error - retry {attempt}/{MAX_RETRIES} in {retry_delay}s"
                    time_module.sleep(retry_delay)

    def get_download(self, download_id: str) -> Download | None:
        """Get a specific download by ID.

        Args:
            download_id: Unique download ID

        Returns:
            Download object or None if not found
        """
        return self._downloads.get(download_id)

    def get_all_downloads(self) -> dict[str, Download]:
        """Get all downloads.

        Returns:
            Dictionary of download ID to Download object
        """
        return self._downloads.copy()

    def get_queue_status(self) -> dict[str, int]:
        """Get current download queue status.

        Returns:
            Dictionary with queue metrics: {
                "queue_size": number of downloads waiting,
                "active_downloads": number currently processing
            }
        """
        queue_size = self._download_queue.qsize()
        active_downloads = sum(
            1 for d in self._downloads.values()
            if d.status == DownloadStatus.DOWNLOADING
        )

        return {
            "queue_size": queue_size,
            "active_downloads": active_downloads,
        }

    def _scan_and_track_videos(self, channel_url: str) -> None:
        """Scan for new videos and add them to the database.

        Args:
            channel_url: The channel URL that was just downloaded
        """
        if not self.database:
            return

        # Find all .info.json files in download directory
        for info_file in self.settings.download_dir.rglob("*.info.json"):
            try:
                with open(info_file) as f:
                    info = json.load(f)

                video_id = info.get("id", "")
                if not video_id:
                    continue

                # Skip if already in database
                if self.database.get_video_by_id(video_id):
                    continue

                # Find the video file (same name without .info.json)
                video_file = self._find_video_file(info_file)
                if not video_file:
                    logger.warning(f"Video file not found for {info_file}")
                    continue

                channel_name = info.get("uploader", info.get("channel", "Unknown"))
                upload_date = info.get("upload_date", "")
                title = info.get("title", "Unknown")
                file_size = video_file.stat().st_size if video_file.exists() else 0

                self.database.add_video(
                    channel_name=channel_name,
                    channel_url=channel_url,
                    video_id=video_id,
                    title=title,
                    upload_date=upload_date,
                    file_path=str(video_file),
                    file_size=file_size,
                    info_json_path=str(info_file),
                )

                logger.info(f"Tracked video in DB: {title}")

            except Exception as e:
                logger.exception(f"Error processing {info_file}: {e}")

        # Run cleanup after adding new videos
        self._cleanup_old_videos()

    def _rename_thumbnails_for_plex(self) -> None:
        """Rename thumbnails from .jpg to -poster.jpg for Plex Local Media Assets.

        Plex's Local Media Assets agent expects movie posters to be named
        {video-name}-poster.jpg rather than just {video-name}.jpg.

        With the new folder structure, each video is in its own subfolder.
        """
        # Search recursively for all .jpg files
        for jpg_file in self.settings.download_dir.rglob("*.jpg"):
            # Skip if already renamed or not a video thumbnail
            if jpg_file.name.endswith("-poster.jpg"):
                continue

            # Check if corresponding video file exists in same directory
            base_name = jpg_file.stem  # filename without .jpg
            video_dir = jpg_file.parent
            video_extensions = [".mp4", ".mkv", ".webm"]
            has_video = any(
                (video_dir / f"{base_name}{ext}").exists()
                for ext in video_extensions
            )

            if has_video:
                new_name = video_dir / f"{base_name}-poster.jpg"
                jpg_file.rename(new_name)
                logger.debug(f"Renamed thumbnail: {jpg_file.name} → {new_name.name}")

    def _find_video_file(self, info_file: Path) -> Optional[Path]:
        """Find the video file corresponding to an info.json file.

        Args:
            info_file: Path to the .info.json file

        Returns:
            Path to video file or None if not found
        """
        # Video file has same stem but different extension
        base_path = info_file.with_suffix("")  # Remove .json
        base_path = base_path.with_suffix("")  # Remove .info

        video_extensions = [".mp4", ".mkv", ".webm", ".avi", ".mov"]
        for ext in video_extensions:
            video_path = base_path.with_suffix(ext)
            if video_path.exists():
                return video_path

        return None

    def _cleanup_old_videos(self) -> None:
        """Delete old videos beyond the per-channel limit."""
        if not self.database:
            return

        for channel_name in self.database.get_channel_names():
            # Get videos for this channel to determine channel_url
            videos = self.database.get_videos_by_channel(channel_name)
            if not videos:
                continue

            # Get channel URL from first video (all videos in same channel have same URL)
            channel_url = videos[0].channel_url

            # Check for per-channel limit, fallback to global default
            keep_count = self.database.get_channel_limit(channel_url)
            if keep_count is None:
                keep_count = self.settings.videos_per_channel

            videos_to_delete = self.database.get_videos_to_cleanup(
                channel_name, keep_count
            )

            for video in videos_to_delete:
                logger.info(
                    f"Cleaning up old video: {video.title} from {channel_name}"
                )
                self.database.delete_video(video.video_id, delete_file=True)

            if videos_to_delete:
                logger.info(
                    f"Cleaned up {len(videos_to_delete)} old videos from {channel_name} (limit: {keep_count})"
                )

    def download_all_channels(self) -> list[str]:
        """Download from all configured channels.

        Returns:
            List of download IDs for all started downloads
        """
        channels = self.load_channels()
        download_ids = []

        for channel_url in channels:
            download_id = self.start_download(channel_url)
            download_ids.append(download_id)

        return download_ids

    def scan_existing_videos(self) -> int:
        """Scan download directory for existing videos and add to database.

        This is useful for importing videos that were downloaded before
        the database was set up.

        Returns:
            Number of videos added to database
        """
        if not self.database:
            logger.warning("No database configured - cannot scan existing videos")
            return 0

        added_count = 0

        # Find all .info.json files
        for info_file in self.settings.download_dir.rglob("*.info.json"):
            try:
                with open(info_file) as f:
                    info = json.load(f)

                video_id = info.get("id", "")
                if not video_id:
                    continue

                # Skip if already in database
                if self.database.get_video_by_id(video_id):
                    continue

                # Find the video file
                video_file = self._find_video_file(info_file)
                if not video_file:
                    logger.debug(f"Video file not found for {info_file}")
                    continue

                channel_name = info.get("uploader", info.get("channel", "Unknown"))
                channel_url = info.get("channel_url", info.get("uploader_url", ""))
                upload_date = info.get("upload_date", "")
                title = info.get("title", "Unknown")
                file_size = video_file.stat().st_size if video_file.exists() else 0

                self.database.add_video(
                    channel_name=channel_name,
                    channel_url=channel_url,
                    video_id=video_id,
                    title=title,
                    upload_date=upload_date,
                    file_path=str(video_file),
                    file_size=file_size,
                    info_json_path=str(info_file),
                )

                added_count += 1
                logger.info(f"Imported existing video: {title}")

            except Exception as e:
                logger.exception(f"Error scanning {info_file}: {e}")

        logger.info(f"Scan complete - added {added_count} videos to database")
        return added_count

    def cleanup_flat_structure_files(self) -> dict[str, int]:
        """Remove old flat-structure files (videos directly in channel folders).

        With the new subfolder structure, each video should be in its own folder.
        This removes old files from the flat structure that are no longer needed.

        Returns:
            Dict with counts of removed files: {"videos": N, "posters": N, "info": N, "locked": N}
        """
        counts = {"videos": 0, "posters": 0, "info": 0, "locked": 0}

        for channel_dir in self.settings.download_dir.iterdir():
            if not channel_dir.is_dir():
                continue

            # Find all files directly in channel folder (not in subdirectories)
            for file in channel_dir.iterdir():
                if file.is_file():
                    try:
                        if file.suffix in [".mp4", ".mkv", ".webm"]:
                            file.unlink()
                            counts["videos"] += 1
                            logger.info(f"Removed old video file: {file.name}")
                        elif file.name.endswith("-poster.jpg"):
                            file.unlink()
                            counts["posters"] += 1
                        elif file.suffix == ".jpg":
                            file.unlink()
                            counts["posters"] += 1
                        elif file.suffix == ".json":
                            file.unlink()
                            counts["info"] += 1
                    except (OSError, PermissionError) as e:
                        logger.warning(f"Could not remove {file.name}: {e}")
                        counts["locked"] += 1

        logger.info(
            f"Cleanup complete: {counts['videos']} videos, "
            f"{counts['posters']} posters, {counts['info']} info files removed, "
            f"{counts['locked']} files locked"
        )
        return counts
