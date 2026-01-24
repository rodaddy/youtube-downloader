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


def normalize_channel_name(name: str) -> str:
    """Normalize channel name for fuzzy matching by removing all separators.

    This creates a canonical form for detecting duplicate directories:
    - "Charles_Watts_-_Inside_Arsenal" → "charleswattsinsidearsenal"
    - "Charles Watts - Inside Arsenal" → "charleswattsinsidearsenal"

    Args:
        name: Channel directory name

    Returns:
        Normalized lowercase string with no separators
    """
    # Remove all common separators and convert to lowercase
    normalized = re.sub(r'[_\s\-–—\|]', '', name.lower())
    return normalized


def sanitize_name(name: str) -> str:
    """Sanitize a filename or folder name by removing spaces and special characters.

    Converts:
    - Spaces → underscores
    - Special chars (：｜:|,!?'""＂) → removed
    - Emojis → removed (for filesystem compatibility)
    - Multiple underscores → single underscore
    - Dashes → underscores

    Args:
        name: Original name

    Returns:
        Sanitized name
    """
    logger.debug(f"🧹 SANITIZE_NAME: input='{name}'")
    # Remove emojis (Unicode ranges for emoji characters)
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F700-\U0001F77F"  # alchemical symbols
        "\U0001F780-\U0001F7FF"  # Geometric Shapes Extended
        "\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
        "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
        "\U0001FA00-\U0001FA6F"  # Chess Symbols
        "\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
        "\U00002600-\U000026FF"  # Miscellaneous Symbols
        "\U00002700-\U000027BF"  # Dingbats
        "\U0000FE00-\U0000FE0F"  # Variation Selectors
        "\U0001F1E0-\U0001F1FF"  # Flags (iOS)
        "]+",
        flags=re.UNICODE
    )
    clean = emoji_pattern.sub('', name)
    # Remove wide and narrow special characters (including / which breaks paths)
    clean = re.sub(r'[：｜:|,!?\'\"""＂()（）/\\]', '', clean)
    # Replace spaces and dashes with underscores
    clean = clean.replace(' ', '_').replace('-', '_')
    # Collapse multiple underscores
    clean = re.sub(r'_+', '_', clean)
    # Remove leading/trailing underscores
    clean = clean.strip('_')
    logger.debug(f"🧹 SANITIZE_NAME: output='{clean}'")
    return clean


# Common redundant prefixes that channels add to every video title
# These make titles indistinguishable when truncated in Plex grid view
REDUNDANT_TITLE_PREFIXES = [
    # Charles Watts (Arsenal)
    r"^Arsenal latest news\s*[-–—:]\s*",
    r"^Arsenal news\s*[-–—:]\s*",
    # FPL channels (already have channel context)
    r"^FPL GW\d+\s*[-–—:]\s*",
    # Add more patterns here as needed
]


def strip_redundant_prefixes(title: str) -> str:
    """Strip common redundant prefixes from video titles.

    Many YouTube channels add the same prefix to every video title,
    which makes them look identical when truncated in Plex's grid view.
    This removes those prefixes to show the unique part of the title.

    Args:
        title: Original video title

    Returns:
        Title with redundant prefix stripped (or original if no match)
    """
    original = title
    for pattern in REDUNDANT_TITLE_PREFIXES:
        title = re.sub(pattern, '', title, flags=re.IGNORECASE)
        if title != original:
            logger.debug(f"🔤 Stripped prefix: '{original}' → '{title}'")
            break  # Only strip one prefix
    return title


def letterbox_thumbnail(thumbnail_path: Path, target_aspect: float = 2/3) -> bool:
    """Convert 16:9 YouTube thumbnail to 2:3 Plex poster format with letterboxing.

    Adds black bars at top and bottom to preserve the full thumbnail image
    while fitting Plex's portrait poster format.

    Args:
        thumbnail_path: Path to the .jpg thumbnail file
        target_aspect: Target aspect ratio (width/height), default 2:3 for Plex posters

    Returns:
        True if conversion succeeded, False otherwise
    """
    if not thumbnail_path.exists():
        return False

    try:
        # Use ImageMagick to:
        # 1. Resize to 1000px width (preserving aspect ratio)
        # 2. Extend canvas to 2:3 aspect ratio (1000x1500) with black background
        # 3. Center the original image vertically
        result = subprocess.run(
            [
                "magick",
                str(thumbnail_path),
                "-resize", "1000x",  # Resize to 1000px width
                "-background", "black",
                "-gravity", "center",
                "-extent", "1000x1500",  # Extend to 2:3 poster format
                str(thumbnail_path),  # Overwrite original
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            logger.debug(f"🖼️ Letterboxed thumbnail: {thumbnail_path.name}")
            return True
        else:
            logger.warning(f"Failed to letterbox {thumbnail_path.name}: {result.stderr}")
            return False

    except FileNotFoundError:
        logger.warning("ImageMagick not found - skipping thumbnail letterboxing")
        return False
    except Exception as e:
        logger.warning(f"Error letterboxing thumbnail: {e}")
        return False


def sanitize_path(path: Path) -> Path:
    """Sanitize filesystem path by removing spaces and special characters.

    Converts:
    - Spaces → underscores
    - Special chars (:|,!?'") → removed
    - Multiple underscores → single underscore

    Args:
        path: Original path

    Returns:
        Sanitized path
    """
    logger.debug(f"🧹 SANITIZE_PATH: input='{path}'")
    parts = []
    for part in path.parts:
        if part == path.parts[0]:  # Keep root unchanged (e.g., /Volumes)
            parts.append(part)
            continue

        # Use sanitize_name for each path component
        parts.append(sanitize_name(part))

    result = Path(*parts)
    logger.debug(f"🧹 SANITIZE_PATH: output='{result}'")
    return result


def rename_downloaded_files(original_dir: Path, info_json_path: Path) -> Path:
    """Rename downloaded video folder and files with sanitized names + date prefix.

    Args:
        original_dir: Original video folder path
        info_json_path: Path to .info.json file for metadata

    Returns:
        New video file path after renaming
    """
    logger.info(f"🔧 SANITIZE START: {original_dir}")
    logger.info(f"   Info JSON: {info_json_path}")

    try:
        # Load metadata to get upload date
        with open(info_json_path) as f:
            metadata = json.load(f)

        upload_date = metadata.get('upload_date', '99999999')
        video_id = metadata.get('id', 'unknown')

        logger.info(f"   Upload Date: {upload_date}, Video ID: {video_id}")

        # Find video file (.mp4, .mkv, .webm, etc.)
        video_file = None
        for ext in ['.mp4', '.mkv', '.webm', '.m4a']:
            potential = list(original_dir.glob(f'*{ext}'))
            if potential:
                video_file = potential[0]
                break

        if not video_file:
            logger.warning(f"No video file found in {original_dir}")
            return original_dir / "unknown.mp4"

        # Get channel folder and original video folder name
        channel_dir = original_dir.parent
        original_folder_name = original_dir.name

        logger.info(f"   Channel dir (BEFORE): {channel_dir}")
        logger.info(f"   Video folder name: {original_folder_name}")

        # Create new folder name: YYYYMMDD_sanitized_title
        # Remove the [video_id] suffix first
        title_without_id = re.sub(r'\s*\[[\w-]+\]$', '', original_folder_name)
        # Strip redundant prefixes like "Arsenal latest news - " before sanitizing
        title_clean = strip_redundant_prefixes(title_without_id)
        sanitized_title = sanitize_name(title_clean)
        new_folder_name = f"{upload_date}_{sanitized_title}"

        logger.info(f"   New video folder name: {new_folder_name}")

        # Sanitize channel folder name too
        sanitized_channel = sanitize_path(channel_dir).name
        new_channel_dir = channel_dir.parent / sanitized_channel

        logger.info(f"   Channel dir (AFTER): {new_channel_dir}")

        # Create new paths
        new_video_dir = new_channel_dir / new_folder_name

        logger.info(f"   Target video dir: {new_video_dir}")

        # Rename channel folder if needed
        if channel_dir != new_channel_dir:
            logger.info(f"📁 RENAME CHANNEL: {channel_dir} → {new_channel_dir}")
            if new_channel_dir.exists():
                logger.info(f"   Channel already exists, using it")
                # Target exists, update original_dir to point to video folder in new channel location
                original_dir = new_channel_dir / original_dir.name
            else:
                logger.info(f"   Executing rename...")
                channel_dir.rename(new_channel_dir)
                channel_dir = new_channel_dir
                # Update original_dir to point to video folder in renamed channel
                original_dir = new_channel_dir / original_dir.name
            logger.info(f"   Video dir updated to: {original_dir}")

        # Rename video folder if needed
        if original_dir != new_video_dir:
            logger.info(f"📁 RENAME VIDEO FOLDER: {original_dir} → {new_video_dir}")
            if new_video_dir.exists():
                logger.warning(f"   Target already exists, merging files")
                # Move files to existing folder
                for file in original_dir.iterdir():
                    target = new_video_dir / file.name
                    if not target.exists():
                        logger.debug(f"   Moving: {file.name}")
                        file.rename(target)
                # Remove old folder if empty
                if not list(original_dir.iterdir()):
                    logger.debug(f"   Removing empty folder: {original_dir}")
                    original_dir.rmdir()
            else:
                logger.info(f"   Executing rename...")
                original_dir.rename(new_video_dir)

        # Rename all files inside to match folder name
        video_ext = video_file.suffix
        new_video_file = new_video_dir / f"{new_folder_name}{video_ext}"

        for file in new_video_dir.iterdir():
            if file.is_file():
                ext = ''.join(file.suffixes)  # Handle .info.json, etc.
                new_name = f"{new_folder_name}{ext}"
                new_path = new_video_dir / new_name

                if file != new_path:
                    logger.debug(f"Renaming file: {file.name} → {new_name}")
                    file.rename(new_path)

                    if file.suffix in ['.mp4', '.mkv', '.webm', '.m4a']:
                        new_video_file = new_path

        logger.info(f"✅ Sanitized: {new_video_file.relative_to(new_channel_dir.parent)}")
        return new_video_file

    except Exception as e:
        logger.error(f"Failed to rename files in {original_dir}: {e}")
        return original_dir / "error.mp4"
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

        # Channel name mappings for consolidating duplicate directories
        self._mappings_file = settings.download_dir / "channel_name_mappings.json"
        self._channel_mappings = self._load_channel_mappings()

        # Failed videos tracking (videos with metadata but no video file)
        self._failed_videos_file = settings.download_dir / "failed_videos.json"
        self._failed_videos = self._load_failed_videos()

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
                channel_url, download_id, quality = self._download_queue.get(timeout=1.0)

                # Add delay between downloads (except for first one)
                if not first_download:
                    logger.info(f"Waiting {DOWNLOAD_START_DELAY}s before starting next download...")
                    time_module.sleep(DOWNLOAD_START_DELAY)
                first_download = False

                # Execute the download
                logger.info(f"Queue: Processing download {download_id} (quality: {quality})")
                self._download_channel(channel_url, download_id, quality)

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

    def start_download(self, channel_url: str, quality: str = "default") -> str:
        """Start downloading videos from a channel (queues the download).

        Args:
            channel_url: YouTube channel URL
            quality: Quality preset - "default" (1080p HDR), "best" (4K HDR), or custom format string

        Returns:
            Unique download ID for tracking
        """
        logger.info(f"🚀 START_DOWNLOAD: channel_url='{channel_url}', quality='{quality}'")
        download_id = str(uuid.uuid4())
        logger.debug(f"🚀 Generated download_id: {download_id}")

        download = Download(
            id=download_id,
            channel_url=channel_url,
            status=DownloadStatus.QUEUED,
            started_at=time(),
        )
        self._downloads[download_id] = download

        # Extract channel name for better logging
        channel_name = channel_url.split("@")[1] if "@" in channel_url else channel_url.split("/")[-1]
        logger.debug(f"🚀 Extracted channel_name: '{channel_name}'")

        # Add to queue instead of spawning thread directly
        queue_size = self._download_queue.qsize()
        logger.info(f"[{channel_name}] Queued download {download_id} (queue position: {queue_size + 1})")
        self._download_queue.put((channel_url, download_id, quality))

        return download_id

    def _load_channel_mappings(self) -> dict:
        """Load channel name mappings from JSON file.

        Returns:
            Dictionary of normalized names to canonical names and variants
        """
        if not self._mappings_file.exists():
            return {}

        try:
            with open(self._mappings_file) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load channel mappings: {e}")
            return {}

    def _save_channel_mappings(self) -> None:
        """Save channel name mappings to JSON file."""
        try:
            with open(self._mappings_file, 'w') as f:
                json.dump(self._channel_mappings, f, indent=2)
            logger.debug(f"📝 Saved channel mappings to {self._mappings_file}")
        except Exception as e:
            logger.error(f"Failed to save channel mappings: {e}")

    def _load_failed_videos(self) -> dict:
        """Load failed videos tracking from JSON file.

        Returns:
            Dictionary of video_id to failure metadata
        """
        if not self._failed_videos_file.exists():
            return {}

        try:
            with open(self._failed_videos_file) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load failed videos: {e}")
            return {}

    def _save_failed_videos(self) -> None:
        """Save failed videos tracking to JSON file."""
        try:
            with open(self._failed_videos_file, 'w') as f:
                json.dump(self._failed_videos, f, indent=2)
            logger.debug(f"📝 Saved failed videos to {self._failed_videos_file}")
        except Exception as e:
            logger.error(f"Failed to save failed videos: {e}")

    def _retry_failed_videos(self, channel_url: str) -> int:
        """Retry downloading videos that previously failed for a specific channel.

        Args:
            channel_url: Channel URL to retry failed videos for

        Returns:
            Number of videos successfully retried
        """
        if not self._failed_videos:
            logger.debug("No failed videos to retry")
            return 0

        # Find failed videos for this channel
        channel_failed = {
            vid: data for vid, data in self._failed_videos.items()
            if data.get("channel_url") == channel_url and data.get("retry_count", 0) < MAX_RETRIES
        }

        if not channel_failed:
            logger.debug(f"No retryable failed videos for {channel_url}")
            return 0

        logger.info(f"🔄 Found {len(channel_failed)} failed videos to retry")

        retried_successfully = 0

        for video_id, data in channel_failed.items():
            retry_count = data.get("retry_count", 0)
            title = data.get("title", "Unknown")

            logger.info(f"🔄 Retrying: {title} [{video_id}] (attempt {retry_count + 1}/{MAX_RETRIES})")

            try:
                # Create staging directory for retry
                staging_dir = self.settings.download_dir / ".staging" / f"retry_{video_id}"
                staging_dir.mkdir(parents=True, exist_ok=True)

                # Download this specific video by ID
                output_template = str(
                    staging_dir
                    / "%(uploader)s"
                    / "%(title)s [%(id)s]"
                    / "%(title)s [%(id)s].%(ext)s"
                )

                cmd = [
                    "yt-dlp",
                    "--format",
                    self.settings.max_quality,
                    "--output",
                    output_template,
                    # Metadata for Plex
                    "--embed-metadata",
                    # NOTE: --embed-thumbnail removed - causes "Bad file descriptor" errors
                    # at 100% completion during muxing. We use external thumbnails anyway.
                    "--write-info-json",
                    # External thumbnail for Plex YouTube Agent
                    "--write-thumbnail",
                    "--convert-thumbnails",
                    "jpg",
                    # Filename sanitization
                    "--restrict-filenames",
                    # Error handling
                    "--no-continue",  # Don't resume partial downloads
                    "--no-part",  # Don't use .part files - avoids file descriptor issues
                    # Workaround for YouTube SABR streaming "Bad file descriptor" errors
                    "--extractor-args",
                    "youtube:player_client=ios,web",
                    f"https://www.youtube.com/watch?v={video_id}",
                ]

                logger.debug(f"Command: {' '.join(cmd)}")

                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=600,  # 10 minute timeout per video
                )

                if result.returncode == 0:
                    # Move from staging to final location
                    moved_videos = self._move_from_staging(staging_dir, channel_url)

                    if moved_videos:
                        logger.info(f"✅ Successfully retried: {title} [{video_id}]")
                        retried_successfully += 1
                        # Note: video is removed from failed_videos in _move_from_staging
                    else:
                        # Still failed - increment retry count
                        logger.warning(f"⚠️  Retry failed (no video file): {title} [{video_id}]")
                        self._failed_videos[video_id]["retry_count"] = retry_count + 1
                        self._failed_videos[video_id]["last_retry_at"] = time()
                        self._save_failed_videos()

                else:
                    # Download failed - increment retry count
                    logger.warning(f"⚠️  Retry failed (exit code {result.returncode}): {title} [{video_id}]")
                    self._failed_videos[video_id]["retry_count"] = retry_count + 1
                    self._failed_videos[video_id]["last_retry_at"] = time()
                    self._save_failed_videos()

                # Clean up staging directory
                import shutil
                if staging_dir.exists():
                    shutil.rmtree(staging_dir)

            except Exception as e:
                logger.error(f"❌ Exception during retry of {video_id}: {e}")
                self._failed_videos[video_id]["retry_count"] = retry_count + 1
                self._failed_videos[video_id]["last_retry_at"] = time()
                self._save_failed_videos()

        logger.info(f"✅ Successfully retried {retried_successfully}/{len(channel_failed)} failed videos")
        return retried_successfully

    def _consolidate_duplicate_directories(self) -> None:
        """Consolidate duplicate channel directories using fuzzy name matching.

        This self-learning system:
        1. Scans all channel directories
        2. Groups them by normalized name (stripping separators)
        3. Picks canonical name (most videos or first alphabetically)
        4. Moves videos from variant directories to canonical
        5. Deletes empty variant directories
        6. Updates mapping file for future reference
        """
        logger.info("🔧 Consolidating duplicate channel directories...")

        # Scan all directories (exclude staging, hidden, and date-based folders)
        channel_dirs = [
            d for d in self.settings.download_dir.iterdir()
            if d.is_dir() and not d.name.startswith('.') and not d.name.startswith('202')
        ]

        # Group directories by normalized name
        groups: dict[str, list[Path]] = {}
        for dir_path in channel_dirs:
            normalized = normalize_channel_name(dir_path.name)
            if normalized not in groups:
                groups[normalized] = []
            groups[normalized].append(dir_path)

        # Process groups with duplicates
        for normalized, directories in groups.items():
            if len(directories) <= 1:
                continue  # No duplicates

            logger.info(f"🔍 Found {len(directories)} variants for '{normalized}':")
            for d in directories:
                logger.info(f"   - {d.name}")

            # Pick canonical directory (most videos, or first alphabetically)
            def count_videos(dir_path: Path) -> int:
                return sum(1 for _ in dir_path.rglob("*.mp4"))

            canonical = max(directories, key=lambda d: (count_videos(d), d.name))
            variants = [d for d in directories if d != canonical]

            logger.info(f"📌 Canonical: {canonical.name} ({count_videos(canonical)} videos)")

            # Move videos from variants to canonical
            for variant_dir in variants:
                logger.info(f"📦 Consolidating {variant_dir.name} → {canonical.name}")

                # Find all video folders in variant (YYYYMMDD_Title pattern)
                video_folders = [
                    d for d in variant_dir.iterdir()
                    if d.is_dir() and re.match(r'^\d{8}_', d.name)
                ]

                for video_folder in video_folders:
                    dest_folder = canonical / video_folder.name

                    if dest_folder.exists():
                        logger.debug(f"   ⚠️  {video_folder.name} already exists in canonical, skipping")
                        continue

                    # Move the entire video folder
                    import shutil
                    try:
                        shutil.move(str(video_folder), str(dest_folder))
                        logger.info(f"   ✅ Moved {video_folder.name}")
                    except Exception as e:
                        logger.error(f"   ❌ Failed to move {video_folder.name}: {e}")

                # Check if variant directory is now empty (except metadata folders)
                remaining_items = [
                    item for item in variant_dir.iterdir()
                    if not ('_-_Videos' in item.name or '_-_Live' in item.name or '_-_Shorts' in item.name)
                ]

                if not remaining_items:
                    logger.info(f"🧹 Deleting empty variant directory: {variant_dir.name}")
                    import shutil
                    try:
                        shutil.rmtree(variant_dir)
                    except Exception as e:
                        logger.error(f"Failed to delete {variant_dir.name}: {e}")

            # Update mappings
            if normalized not in self._channel_mappings:
                self._channel_mappings[normalized] = {
                    "canonical": canonical.name,
                    "variants_seen": [],
                }

            # Track all variants seen
            for variant in variants:
                if variant.name not in self._channel_mappings[normalized]["variants_seen"]:
                    self._channel_mappings[normalized]["variants_seen"].append(variant.name)

            self._channel_mappings[normalized]["canonical"] = canonical.name
            self._save_channel_mappings()

        logger.info("✅ Directory consolidation complete")

    def _cleanup_orphaned_metadata_folders(self) -> None:
        """Delete orphaned playlist metadata folders (*_-_Videos, *_-_Live, *_-_Shorts).

        These folders are created by older yt-dlp runs before we added
        --no-write-playlist-metafiles flag.
        """
        logger.info("🧹 Cleaning up orphaned playlist metadata folders...")

        metadata_folders = list(self.settings.download_dir.rglob("*_-_Videos*")) + \
                          list(self.settings.download_dir.rglob("*_-_Live*")) + \
                          list(self.settings.download_dir.rglob("*_-_Shorts*"))

        for folder in metadata_folders:
            if folder.is_dir():
                logger.info(f"🗑️  Deleting metadata folder: {folder.relative_to(self.settings.download_dir)}")
                import shutil
                try:
                    shutil.rmtree(folder)
                except Exception as e:
                    logger.error(f"Failed to delete {folder}: {e}")

        logger.info(f"✅ Cleaned up {len(metadata_folders)} metadata folders")

    def _cleanup_watched_videos(self) -> int:
        """Delete watched videos from filesystem (Plex integration).

        Queries Plex for watched videos and deletes them from disk.
        Archive entries are kept (preventing re-download).

        Returns:
            Number of videos deleted
        """
        if not self.plex:
            logger.debug("Plex integration not configured, skipping watched video cleanup")
            return 0

        logger.info("🧹 Cleaning up watched videos...")

        try:
            # Get watched videos from Plex
            watched_files = self.plex.get_watched_videos()

            if not watched_files:
                logger.info("No watched videos to clean up")
                return 0

            deleted_count = 0

            for file_path in watched_files:
                video_path = Path(file_path)

                # Translate Plex path to local path if needed
                # Plex may use different mount point (e.g., /mnt/media vs /Volumes/media_files)
                if not video_path.exists():
                    # Try to find the file by matching the relative path from download_dir
                    # Extract filename and search in our download directory
                    video_name = video_path.name
                    matches = list(self.settings.download_dir.rglob(video_name))
                    if matches:
                        video_path = matches[0]
                        logger.debug(f"Translated Plex path to: {video_path}")
                    else:
                        logger.debug(f"Video already deleted: {video_name}")
                        continue

                if not video_path.exists():
                    logger.debug(f"Video already deleted: {video_path.name}")
                    continue

                # Delete the video file
                try:
                    video_path.unlink()
                    logger.info(f"🗑️  Deleted watched video: {video_path.name}")
                    deleted_count += 1

                    # Also delete associated files (thumbnails, metadata)
                    base_name = video_path.stem  # Remove extension
                    parent_dir = video_path.parent

                    for associated_file in parent_dir.glob(f"{base_name}*"):
                        if associated_file != video_path and associated_file.is_file():
                            try:
                                associated_file.unlink()
                                logger.debug(f"   Deleted: {associated_file.name}")
                            except Exception as e:
                                logger.debug(f"Could not delete {associated_file.name}: {e}")

                except Exception as e:
                    logger.error(f"Failed to delete {video_path.name}: {e}")

            logger.info(f"✅ Deleted {deleted_count} watched videos")
            return deleted_count

        except Exception as e:
            logger.error(f"Error in watched video cleanup: {e}")
            return 0

    def _sync_archive_with_filesystem(self) -> int:
        """Sync archive file with filesystem (remove entries for missing videos).

        Scans all video folders, extracts YouTube IDs, checks if videos exist.
        Removes archive entries for missing videos (allows re-download).

        Returns:
            Number of archive entries removed
        """
        logger.info("🔄 Syncing archive with filesystem...")

        archive_file = self.settings.download_dir / ".yt-dlp-archive.txt"

        if not archive_file.exists():
            logger.debug("Archive file doesn't exist, nothing to sync")
            return 0

        try:
            # Read all archive entries
            with open(archive_file) as f:
                archive_lines = f.readlines()

            # Extract video IDs from archive (format: "youtube VIDEO_ID")
            archive_ids = set()
            for line in archive_lines:
                line = line.strip()
                if line.startswith("youtube "):
                    video_id = line.split()[1]
                    archive_ids.add(video_id)

            logger.debug(f"Archive has {len(archive_ids)} entries")

            # Scan filesystem for existing videos
            existing_ids = set()

            # Find all .info.json files (every downloaded video has one)
            for info_file in self.settings.download_dir.rglob("*.info.json"):
                try:
                    import json
                    with open(info_file) as f:
                        metadata = json.load(f)
                        video_id = metadata.get("id")
                        if video_id:
                            existing_ids.add(video_id)
                except Exception as e:
                    logger.debug(f"Could not read {info_file.name}: {e}")

            logger.debug(f"Filesystem has {len(existing_ids)} videos")

            # Find IDs in archive but not on disk
            missing_ids = archive_ids - existing_ids

            if not missing_ids:
                logger.info("Archive is in sync with filesystem")
                return 0

            logger.info(f"Found {len(missing_ids)} videos in archive but not on disk")

            # Remove missing IDs from archive
            new_archive_lines = []
            removed_count = 0

            for line in archive_lines:
                line_stripped = line.strip()
                if line_stripped.startswith("youtube "):
                    video_id = line_stripped.split()[1]
                    if video_id in missing_ids:
                        logger.debug(f"Removing from archive: {video_id}")
                        removed_count += 1
                        continue  # Skip this line
                new_archive_lines.append(line)

            # Write updated archive
            with open(archive_file, "w") as f:
                f.writelines(new_archive_lines)

            logger.info(f"✅ Removed {removed_count} stale entries from archive")
            return removed_count

        except Exception as e:
            logger.error(f"Error syncing archive: {e}")
            return 0

    def _recover_orphaned_videos(self) -> int:
        """Move orphaned video folders (YYYYMMDD_Title) to correct channel directories.

        Scans root level for orphaned video folders, reads metadata to find channel,
        moves them to the correct channel directory.

        Returns:
            Number of videos moved
        """
        logger.info("🔧 Recovering orphaned video folders...")

        moved_count = 0

        try:
            # Find all YYYYMMDD_* folders at root level
            for item in self.settings.download_dir.iterdir():
                if not item.is_dir():
                    continue

                # Skip special directories
                if item.name.startswith('.') or item.name == 'channel_name_mappings.json':
                    continue

                # Check if it matches YYYYMMDD_* pattern (orphaned video)
                if re.match(r'^\d{8}_', item.name):
                    logger.info(f"📦 Found orphaned video: {item.name}")

                    # Try to find .info.json to determine channel
                    info_files = list(item.glob("*.info.json"))

                    if not info_files:
                        logger.warning(f"   ⚠️  No .info.json found, skipping {item.name}")
                        continue

                    try:
                        import json
                        with open(info_files[0]) as f:
                            metadata = json.load(f)

                        uploader = metadata.get("uploader", "")
                        if not uploader:
                            logger.warning(f"   ⚠️  No uploader in metadata, skipping {item.name}")
                            continue

                        # Sanitize channel name
                        channel_name = sanitize_name(uploader)
                        channel_dir = self.settings.download_dir / channel_name

                        # Create channel directory if it doesn't exist
                        channel_dir.mkdir(parents=True, exist_ok=True)

                        # Move video folder to channel directory
                        dest_path = channel_dir / item.name

                        if dest_path.exists():
                            logger.warning(f"   ⚠️  {item.name} already exists in {channel_name}, skipping")
                            continue

                        import shutil
                        shutil.move(str(item), str(dest_path))
                        logger.info(f"   ✅ Moved to {channel_name}/{item.name}")
                        moved_count += 1

                    except Exception as e:
                        logger.error(f"   ❌ Failed to move {item.name}: {e}")

            logger.info(f"✅ Recovered {moved_count} orphaned videos")
            return moved_count

        except Exception as e:
            logger.error(f"Error recovering orphaned videos: {e}")
            return 0

    def _normalize_video_folder_names(self) -> int:
        """Normalize all video folder names to YYYYMMDD_Title format.

        Scans all channel directories, finds folders without date prefix,
        reads metadata to get upload date, renames to YYYYMMDD_Title.

        Returns:
            Number of folders renamed
        """
        logger.info("🔧 Normalizing video folder names...")

        renamed_count = 0

        try:
            # Scan all channel directories
            for channel_dir in self.settings.download_dir.iterdir():
                if not channel_dir.is_dir():
                    continue

                # Skip special directories
                if channel_dir.name.startswith('.') or channel_dir.name == 'channel_name_mappings.json':
                    continue

                # Scan video folders inside channel
                for video_folder in channel_dir.iterdir():
                    if not video_folder.is_dir():
                        continue

                    # Check if already has YYYYMMDD_ prefix
                    if re.match(r'^\d{8}_', video_folder.name):
                        continue  # Already correct format

                    # Skip Season folders (Plex TV structure)
                    if re.match(r'^Season \d+$', video_folder.name):
                        continue  # Season containers, not video folders

                    logger.info(f"📦 Found incorrectly named folder: {channel_dir.name}/{video_folder.name}")

                    # Find .info.json to get upload date
                    info_files = list(video_folder.glob("*.info.json"))

                    if not info_files:
                        logger.warning(f"   ⚠️  No .info.json found, skipping")
                        continue

                    try:
                        import json
                        from datetime import datetime

                        with open(info_files[0]) as f:
                            metadata = json.load(f)

                        # Get upload date
                        upload_date_str = metadata.get("upload_date")
                        if not upload_date_str:
                            logger.warning(f"   ⚠️  No upload_date in metadata, skipping")
                            continue

                        # Parse upload date (format: YYYYMMDD)
                        upload_date = datetime.strptime(upload_date_str, "%Y%m%d")
                        date_prefix = upload_date.strftime("%Y%m%d")

                        # Get title
                        title = metadata.get("title", "")
                        if not title:
                            logger.warning(f"   ⚠️  No title in metadata, skipping")
                            continue

                        # Strip redundant prefixes and sanitize title
                        title_clean = strip_redundant_prefixes(title)
                        title_sanitized = sanitize_name(title_clean)

                        # Build new name
                        new_name = f"{date_prefix}_{title_sanitized}"

                        # Avoid duplicate names
                        new_path = channel_dir / new_name
                        if new_path.exists():
                            logger.warning(f"   ⚠️  {new_name} already exists, skipping")
                            continue

                        # Rename folder
                        video_folder.rename(new_path)
                        logger.info(f"   ✅ Renamed to: {new_name}")
                        renamed_count += 1

                        # Set file modification times to match upload_date for Plex
                        try:
                            import os
                            upload_timestamp = upload_date.replace(hour=12).timestamp()

                            # Set mtime for all files in the renamed folder
                            for file in new_path.iterdir():
                                if file.is_file():
                                    os.utime(file, (upload_timestamp, upload_timestamp))

                            logger.debug(f"   📅 Updated file mtimes to {date_prefix}")
                        except Exception as mtime_err:
                            logger.debug(f"   Could not set mtimes: {mtime_err}")

                    except Exception as e:
                        logger.error(f"   ❌ Failed to rename {video_folder.name}: {e}")

            logger.info(f"✅ Normalized {renamed_count} video folder names")
            return renamed_count

        except Exception as e:
            logger.error(f"Error normalizing folder names: {e}")
            return 0

    def _download_channel(self, channel_url: str, download_id: str, quality: str = "default") -> None:
        """Download videos from a channel with retry logic (runs in background thread).

        Args:
            channel_url: YouTube channel URL
            download_id: Unique download ID for tracking
            quality: Quality preset - "default" (1080p HDR), "best" (4K HDR), or custom format string
        """
        logger.info(f"📥 _DOWNLOAD_CHANNEL: channel_url='{channel_url}', download_id={download_id}, quality={quality}")

        download = self._downloads.get(download_id)
        if not download:
            logger.error(f"Download {download_id} not found")
            return

        # Extract channel name for better logging
        channel_name = channel_url.split("@")[1] if "@" in channel_url else channel_url.split("/")[-1]
        logger.debug(f"📥 Extracted channel_name: '{channel_name}'")

        # Retry loop
        for attempt in range(1, MAX_RETRIES + 1):
            logger.info(f"📥 [{channel_name}] Retry attempt {attempt}/{MAX_RETRIES}")
            try:
                download.status = DownloadStatus.DOWNLOADING
                download.output = []

                # Ensure download directory exists
                self.settings.ensure_download_dir()

                logger.info(f"📂 DOWNLOAD_DIR = {self.settings.download_dir}")
                logger.info(f"📂 ARCHIVE_FILE = {self.settings.archive_file}")

                # Create staging directory for this download
                staging_dir = self.settings.download_dir / ".staging" / f"download_{download_id}"
                staging_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"📂 STAGING_DIR = {staging_dir}")

                # Download to staging area - yt-dlp can create whatever structure it wants
                # We'll clean it up and move to final location after download completes
                output_template = str(
                    staging_dir
                    / "%(uploader)s"
                    / "%(title)s [%(id)s]"
                    / "%(title)s [%(id)s].%(ext)s"
                )

                logger.info(f"📝 OUTPUT_TEMPLATE = {output_template}")
                logger.debug(f"📝 Template breakdown:")
                logger.debug(f"   - Staging dir: {staging_dir}")
                logger.debug(f"   - Channel folder: %(uploader)s (from yt-dlp metadata)")
                logger.debug(f"   - Video folder: %(title)s [%(id)s] (from yt-dlp metadata)")
                logger.debug(f"   - File: %(title)s [%(id)s].%(ext)s (from yt-dlp metadata)")

                # Select quality format string
                if quality == "best":
                    format_str = self.settings.max_quality_best
                    logger.info(f"📺 Using BEST quality: {format_str}")
                elif quality == "default":
                    format_str = self.settings.max_quality
                    logger.info(f"📺 Using DEFAULT quality: {format_str}")
                else:
                    # Custom format string
                    format_str = quality
                    logger.info(f"📺 Using CUSTOM quality: {format_str}")

                cmd = [
                    "yt-dlp",
                    "--format",
                    format_str,
                    "--playlist-reverse",  # Reverse playlist order (newest first)
                    "--playlist-end",
                    str(self.settings.videos_per_channel),  # Take first N after reversing (newest N videos)
                    "--download-archive",
                    str(self.settings.archive_file),  # Skip videos already downloaded
                    "--output",
                    output_template,
                    "--print-to-file", "after_move:filepath" , str(self.settings.download_dir / ".last_download.txt"),  # Track what was downloaded
                    # Content filtering
                    "--match-filter",
                    "duration>60&!is_live",  # Skip shorts (<60s) and live streams (no spaces around &)
                    # Metadata for Plex
                    "--embed-metadata",
                    # NOTE: --embed-thumbnail removed - causes "Bad file descriptor" errors
                    # at 100% completion during muxing. We use external thumbnails anyway.
                    "--write-info-json",
                    # External thumbnail for Plex YouTube Agent
                    "--write-thumbnail",
                    "--convert-thumbnails",
                    "jpg",
                    # Filename sanitization
                    "--restrict-filenames",  # Convert Unicode to ASCII, replace spaces with underscores
                    "--no-write-playlist-metafiles",  # Don't create playlist metadata folders
                    # Error handling
                    "--ignore-errors",  # Continue downloading playlist even if some videos fail
                    "--no-continue",  # Don't resume partial downloads - prevents HTTP 416 errors
                    "--no-part",  # Don't use .part files - avoids file descriptor issues
                    # Workaround for YouTube SABR streaming "Bad file descriptor" errors
                    # See: https://github.com/yt-dlp/yt-dlp/issues/12482
                    "--extractor-args",
                    "youtube:player_client=ios,web",
                    # Other options
                    "--progress",
                    "--verbose",  # More detailed error messages
                    f"{channel_url}/videos",  # /videos suffix = download ONLY from Videos tab
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
                logger.info(f"✅ Process completed with return code: {process.returncode}")

                if process.returncode == 0:
                    download.status = DownloadStatus.COMPLETE
                    download.message = "Download complete, processing files..."
                    logger.info(f"[{channel_name}] Download completed successfully")

                    # Run middleware to enforce directory structure
                    # This moves files from staging, enforces naming, and cleans up old videos
                    logger.info(f"🔧 Running directory structure enforcement")
                    self._enforce_directory_structure(channel_url)

                    # Retry failed videos for this channel
                    logger.info(f"🔄 Checking for failed videos to retry")
                    self._retry_failed_videos(channel_url)

                    # Upload thumbnails and metadata to Plex if integration is enabled
                    if self.plex:
                        try:
                            # Upload thumbnails
                            uploaded_thumbs = self.plex.sync_thumbnails(
                                self.settings.download_dir
                            )
                            logger.info(f"Plex sync: uploaded {uploaded_thumbs} thumbnails")

                            # Upload metadata (title, summary, date)
                            uploaded_meta = self.plex.sync_metadata(
                                self.settings.download_dir
                            )
                            logger.info(f"Plex sync: uploaded metadata for {uploaded_meta} items")
                        except Exception as e:
                            logger.warning(f"Plex sync failed: {e}")

                    download.message = "Complete"
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

    def _enforce_directory_structure(self, channel_url: str | None = None) -> None:
        """Middleware to enforce correct directory structure and cleanup.

        This function:
        1. Processes staging directories (moves downloads to final location)
        2. Enforces proper naming conventions
        3. Removes excess videos per channel (keeps last N based on settings)
        4. Can run after downloads OR on a schedule for cleanup

        Args:
            channel_url: Optional channel URL filter (if None, processes all)
        """
        logger.info(f"🔧 ENFORCE_DIRECTORY_STRUCTURE: channel_url={channel_url}")

        # Step 1: Process staging directories
        staging_root = self.settings.download_dir / ".staging"
        if staging_root.exists():
            logger.info(f"📦 Processing staging directories in {staging_root}")
            for staging_download in staging_root.iterdir():
                if staging_download.is_dir():
                    try:
                        logger.info(f"📦 Processing staging: {staging_download.name}")
                        moved_videos = self._move_from_staging(staging_download, channel_url or "")
                        logger.info(f"📦 Moved {len(moved_videos)} videos from {staging_download.name}")

                        # Track in database
                        if self.database and moved_videos:
                            for video_file, info_file, channel_url_used in moved_videos:
                                self._track_video_in_db(video_file, info_file, channel_url_used)

                        # Clean up staging directory
                        import shutil
                        shutil.rmtree(staging_download)
                        logger.info(f"🧹 Cleaned up staging: {staging_download.name}")
                    except Exception as e:
                        logger.error(f"Failed to process staging {staging_download.name}: {e}")

        # Step 2: Enforce video count limits per channel
        if self.database:
            self._cleanup_old_videos()

        # Step 3: Clean up orphaned playlist metadata folders
        self._cleanup_orphaned_metadata_folders()

        # Step 4: Consolidate duplicate channel directories
        self._consolidate_duplicate_directories()

        # Step 5: Recover orphaned videos (move YYYYMMDD_* folders to correct channels)
        self._recover_orphaned_videos()

        # Step 6: Normalize video folder names (ensure all use YYYYMMDD_Title format)
        self._normalize_video_folder_names()

        # Step 7: Cleanup watched videos (Plex integration - Option 4 hybrid approach)
        self._cleanup_watched_videos()

        # Step 8: Sync archive with filesystem (Option 4 hybrid approach)
        self._sync_archive_with_filesystem()

        logger.info(f"✅ Directory structure enforcement complete")

    def _move_from_staging(self, staging_dir: Path, channel_url: str) -> list[tuple[Path, Path, str]]:
        """Move downloaded videos from staging to final location with proper structure.

        Args:
            staging_dir: Staging directory containing downloaded files
            channel_url: Channel URL for tracking

        Returns:
            List of (video_file, info_file, channel_url) tuples for tracking
        """
        logger.info(f"📦 _MOVE_FROM_STAGING: {staging_dir}")
        moved_videos = []

        # Find all .info.json files in staging (these indicate downloaded videos)
        info_files = list(staging_dir.rglob("*.info.json"))
        logger.info(f"📦 Found {len(info_files)} .info.json files in staging")

        for info_file in info_files:
            try:
                # Skip playlist metadata files
                if "_-_Videos" in info_file.name or "_-_Live" in info_file.name or "_-_Shorts" in info_file.name:
                    logger.debug(f"📦 Skipping playlist metadata: {info_file.name}")
                    continue

                with open(info_file) as f:
                    metadata = json.load(f)

                video_id = metadata.get('id', '')
                if not video_id:
                    logger.warning(f"📦 No video ID in {info_file}, skipping")
                    continue

                upload_date = metadata.get('upload_date', '99999999')
                uploader = metadata.get('uploader', 'Unknown_Channel')
                title = metadata.get('title', 'Unknown_Title')

                # Find the actual video file
                # Note: Can't use with_suffix() as it breaks on filenames with periods
                # e.g. "Title. [VIDEO_ID].info.json" -> with_suffix would break on the period before [
                video_file = None
                info_str = str(info_file)
                if info_str.endswith('.info.json'):
                    base_name = info_str[:-10]  # Remove .info.json (10 chars)
                else:
                    base_name = info_str

                for ext in ['.mp4', '.mkv', '.webm', '.m4a']:
                    potential = Path(base_name + ext)
                    if potential.exists():
                        video_file = potential
                        break

                if not video_file:
                    logger.warning(f"📦 No video file found for {info_file}")

                    # Track failed video for retry
                    self._failed_videos[video_id] = {
                        "video_id": video_id,
                        "title": title,
                        "uploader": uploader,
                        "upload_date": upload_date,
                        "channel_url": channel_url,
                        "failed_at": time(),
                        "retry_count": self._failed_videos.get(video_id, {}).get("retry_count", 0),
                        "reason": "no_video_file"
                    }
                    self._save_failed_videos()
                    logger.info(f"🔄 Tracked failed video for retry: {title} [{video_id}]")

                    continue

                # Find thumbnail (use base_name from video file lookup)
                thumbnail = Path(base_name + '.jpg')

                # Sanitize names (strip redundant prefixes first)
                sanitized_channel = sanitize_name(uploader)
                title_clean = strip_redundant_prefixes(title)
                sanitized_title = sanitize_name(title_clean)

                # Calculate season/episode from upload date for Plex TV Shows
                # Season = last 2 digits of year (2026 -> 26)
                # Episode = day of year (Jan 23 = 023)
                from datetime import datetime
                upload_dt = datetime.strptime(upload_date, "%Y%m%d")
                season_num = int(upload_dt.strftime("%y"))  # Last 2 digits of year
                episode_num = upload_dt.timetuple().tm_yday  # Day of year (1-366)

                # Video filename: S##E### - Title.mp4 (Plex TV format)
                video_filename = f"S{season_num:02d}E{episode_num:03d} - {sanitized_title}"

                # Create season folder structure for Plex TV Shows
                final_channel_dir = self.settings.download_dir / sanitized_channel
                final_season_dir = final_channel_dir / f"Season {season_num:02d}"
                final_channel_dir.mkdir(parents=True, exist_ok=True)
                final_season_dir.mkdir(parents=True, exist_ok=True)

                # Move files to final location (inside season folder)
                final_video_file = final_season_dir / f"{video_filename}{video_file.suffix}"
                final_info_file = final_season_dir / f"{video_filename}.info.json"
                final_thumbnail = final_season_dir / f"{video_filename}.jpg"  # Plex requires exact name match

                logger.info(f"📦 Moving: {video_file.name}")
                logger.info(f"📦   → {final_video_file.relative_to(self.settings.download_dir)}")

                # Move video
                if not final_video_file.exists():
                    import shutil
                    shutil.move(str(video_file), str(final_video_file))

                # Move info.json
                if not final_info_file.exists():
                    import shutil
                    shutil.move(str(info_file), str(final_info_file))

                # Move thumbnail
                if thumbnail.exists() and not final_thumbnail.exists():
                    import shutil
                    shutil.move(str(thumbnail), str(final_thumbnail))

                # Letterbox thumbnail to 2:3 Plex poster format (adds black bars)
                if final_thumbnail.exists():
                    letterbox_thumbnail(final_thumbnail)

                # Set file permissions to 644 (rw-r--r--) so Plex can read them
                import os
                try:
                    os.chmod(final_video_file, 0o644)
                    if final_info_file.exists():
                        os.chmod(final_info_file, 0o644)
                    if final_thumbnail.exists():
                        os.chmod(final_thumbnail, 0o644)
                    logger.debug("📝 Set file permissions to 644 for Plex access")
                except Exception as e:
                    logger.warning(f"Could not set file permissions: {e}")

                # Set file modification time to match upload_date for Plex
                # Plex uses file mtime for release date, not embedded metadata tags
                try:
                    from datetime import datetime
                    import os

                    # Parse upload_date (format: YYYYMMDD)
                    upload_datetime = datetime.strptime(upload_date, "%Y%m%d")
                    # Convert to timestamp (set to noon UTC to avoid timezone issues)
                    upload_timestamp = upload_datetime.replace(hour=12).timestamp()

                    # Set modification and access time for video file
                    os.utime(final_video_file, (upload_timestamp, upload_timestamp))

                    # Also set for info.json and thumbnail
                    if final_info_file.exists():
                        os.utime(final_info_file, (upload_timestamp, upload_timestamp))
                    if final_thumbnail.exists():
                        os.utime(final_thumbnail, (upload_timestamp, upload_timestamp))

                    logger.debug(f"📅 Set file mtime to {upload_date} for Plex")
                except Exception as e:
                    logger.warning(f"Could not set file mtime: {e}")

                moved_videos.append((final_video_file, final_info_file, channel_url))

                # Remove from failed videos if it was previously failed
                if video_id in self._failed_videos:
                    logger.info(f"✅ Video previously failed, now recovered: {title} [{video_id}]")
                    del self._failed_videos[video_id]
                    self._save_failed_videos()

            except Exception as e:
                logger.error(f"Error moving {info_file}: {e}")
                import traceback
                logger.error(traceback.format_exc())

        return moved_videos

    def _track_video_in_db(self, video_file: Path, info_file: Path, channel_url: str) -> None:
        """Track a video in the database.

        Args:
            video_file: Path to video file
            info_file: Path to .info.json file
            channel_url: Channel URL
        """
        try:
            with open(info_file) as f:
                info = json.load(f)

            video_id = info.get("id", "")
            if self.database.get_video_by_id(video_id):
                logger.debug(f"Video {video_id} already in database")
                return  # Already tracked

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
            logger.error(f"Error tracking {video_file}: {e}")

    def _scan_and_track_videos(self, channel_url: str) -> None:
        """Scan for new videos and add them to the database.

        Args:
            channel_url: The channel URL that was just downloaded
        """
        logger.info(f"🔍 _SCAN_AND_TRACK_VIDEOS: channel_url='{channel_url}'")
        logger.debug(f"🔍 Scanning directory: {self.settings.download_dir}")

        if not self.database:
            logger.warning(f"🔍 Database not available, returning early")
            return

        # Find all .info.json files in download directory
        info_files = list(self.settings.download_dir.rglob("*.info.json"))
        logger.info(f"🔍 Found {len(info_files)} .info.json files")

        for info_file in info_files:
            logger.debug(f"🔍 Processing: {info_file}")
            try:
                with open(info_file) as f:
                    info = json.load(f)

                video_id = info.get("id", "")
                logger.debug(f"🔍 Video ID: {video_id}")

                if not video_id:
                    logger.warning(f"🔍 No video ID in {info_file}, skipping")
                    continue

                # Skip if already in database
                if self.database.get_video_by_id(video_id):
                    logger.debug(f"🔍 Video {video_id} already in database, skipping")
                    continue

                # Find the video file (same name without .info.json)
                logger.debug(f"🔍 Searching for video file matching {info_file}")
                video_file = self._find_video_file(info_file)
                if not video_file:
                    logger.warning(f"Video file not found for {info_file}")
                    continue

                logger.info(f"🔍 Found video file: {video_file}")

                # Sanitize filenames (remove spaces, add date prefix)
                video_dir = video_file.parent
                logger.debug(f"🔍 Calling rename_downloaded_files('{video_dir}', '{info_file}')")
                video_file = rename_downloaded_files(video_dir, info_file)
                logger.info(f"🔍 After sanitization: {video_file}")

                # Re-find info_file after renaming
                info_file = video_file.parent / f"{video_file.stem}.info.json"

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
        logger.debug(f"🖼️  _RENAME_THUMBNAILS_FOR_PLEX: Scanning {self.settings.download_dir}")

        # Search recursively for all .jpg files
        jpg_files = list(self.settings.download_dir.rglob("*.jpg"))
        logger.debug(f"🖼️  Found {len(jpg_files)} .jpg files")

        renamed_count = 0
        for jpg_file in jpg_files:
            # Skip if already renamed or not a video thumbnail
            if jpg_file.name.endswith("-poster.jpg"):
                logger.debug(f"🖼️  Skipping (already poster): {jpg_file}")
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
                renamed_count += 1
                logger.debug(f"Renamed thumbnail: {jpg_file.name} → {new_name.name}")

        logger.info(f"🖼️  _RENAME_THUMBNAILS_FOR_PLEX: Renamed {renamed_count} thumbnails")

    def _find_video_file(self, info_file: Path) -> Optional[Path]:
        """Find the video file corresponding to an info.json file.

        Args:
            info_file: Path to the .info.json file

        Returns:
            Path to video file or None if not found
        """
        logger.debug(f"🔎 _FIND_VIDEO_FILE: info_file='{info_file}'")

        # Video file has same stem but different extension
        base_path = info_file.with_suffix("")  # Remove .json
        base_path = base_path.with_suffix("")  # Remove .info
        logger.debug(f"🔎 base_path='{base_path}'")

        video_extensions = [".mp4", ".mkv", ".webm", ".avi", ".mov"]
        for ext in video_extensions:
            video_path = base_path.with_suffix(ext)
            logger.debug(f"🔎 Checking: {video_path}")
            if video_path.exists():
                logger.info(f"🔎 FOUND: {video_path}")
                return video_path

        logger.warning(f"🔎 NOT FOUND: No video file for {info_file}")
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
