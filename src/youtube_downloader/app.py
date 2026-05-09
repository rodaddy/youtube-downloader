"""Flask application for YouTube Downloader.

This module provides the Flask web application with API routes for
downloading YouTube videos and checking download status.
"""

import atexit
import ipaddress
import json
import logging
import os
import re
import shutil
import signal
import time
from datetime import datetime
from pathlib import Path

import requests
from flask import Flask, jsonify, render_template, request, send_file
from flask_httpauth import HTTPBasicAuth
from loguru import logger
from werkzeug.security import check_password_hash, generate_password_hash

from .cleanup import CleanupManager
from .config import Settings
from .database import Database
from .downloader import DownloadManager
from .logger import setup_logger
from .scheduler import DownloadScheduler


def is_local_network(ip_str: str) -> bool:
    """Check if an IP address is in a local/private network.

    Args:
        ip_str: IP address string (e.g., "192.168.1.100")

    Returns:
        True if IP is in a private network range
    """
    try:
        ip = ipaddress.ip_address(ip_str)
        # Check if it's in private ranges
        return ip.is_private or ip.is_loopback
    except ValueError:
        # Invalid IP format
        return False


def create_app(settings: Settings | None = None) -> Flask:
    """Create and configure the Flask application.

    Args:
        settings: Application settings. If None, loads from environment.

    Returns:
        Configured Flask application
    """
    if settings is None:
        settings = Settings.load_with_overrides()

    # Setup logging
    setup_logger(debug=settings.debug, log_dir=settings.log_dir)

    # Suppress Werkzeug HTTP access logs (too verbose)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    logger.info("Starting YouTube Downloader")
    logger.debug(f"Download directory: {settings.download_dir}")
    logger.debug(f"Videos per channel: {settings.videos_per_channel}")

    # Ensure download directory exists
    settings.ensure_download_dir()

    # Initialize database
    db_path = settings.project_root / "data" / "videos.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(db_path)
    logger.info(f"Database initialized at {db_path}")

    # Create Flask app with template folder at project root
    app = Flask(
        __name__,
        template_folder=str(settings.project_root / "templates"),
    )

    # Create download manager with database
    download_manager = DownloadManager(settings, database=database)

    # Create cleanup manager
    cleanup_manager = CleanupManager(database)
    app.cleanup_manager = cleanup_manager  # Make available to routes

    # Create scheduler (only in main process, not reloader)
    # When Flask debug mode is on, it creates a reloader process that would also start the scheduler
    # We only want the scheduler in the main process
    is_reloader = os.environ.get("WERKZEUG_RUN_MAIN") == "true"

    if not settings.debug or is_reloader:
        scheduler = DownloadScheduler(settings)
        scheduler.set_download_callback(download_manager.download_all_channels)
        scheduler.set_cleanup_callback(lambda: download_manager._enforce_directory_structure(None))
        scheduler.start(interval_hours=2.0, cleanup_interval_hours=1.0)

        # Register cleanup on shutdown
        atexit.register(scheduler.stop)
        logger.info("Scheduler enabled (main process)")
    else:
        logger.info("Scheduler disabled (reloader process)")

    # Setup authentication if enabled
    auth = HTTPBasicAuth()

    if settings.auth_enabled:
        logger.info("Web UI authentication enabled")
        if settings.auth_bypass_local:
            logger.info("Local network bypass enabled (private IPs skip auth)")

        # Store hashed password
        password_hash = generate_password_hash(settings.admin_password)  # type: ignore

        @auth.verify_password
        def verify_password(username: str, password: str) -> bool:
            """Verify username and password.

            Bypasses auth for local network requests if configured.
            """
            # Check if request is from local network and bypass is enabled
            if settings.auth_bypass_local:
                client_ip = request.remote_addr
                if client_ip and is_local_network(client_ip):
                    logger.debug(f"Local network bypass for {client_ip}")
                    return True

            # Verify credentials
            if username == settings.admin_username:
                return check_password_hash(password_hash, password)
            return False

        @auth.error_handler
        def auth_error(status: int) -> tuple:
            """Return JSON error for failed auth."""
            return jsonify({"error": "Unauthorized"}), status
    else:
        logger.info("Web UI authentication disabled")
        # No-op auth decorator when disabled
        auth.login_required = lambda f: f  # type: ignore

    @app.route("/")
    @auth.login_required
    def index() -> str:
        """Serve main UI."""
        return render_template("index.html")

    @app.route("/api/channels")
    @auth.login_required
    def get_channels() -> tuple:
        """Get list of configured channels."""
        channels = download_manager.load_channels()
        return jsonify(
            {
                "channels": channels,
                "videos_per_channel": settings.videos_per_channel,
            }
        )

    @app.route("/api/channels", methods=["POST"])
    @auth.login_required
    def add_channel() -> tuple:
        """Add a new channel to channels.txt."""
        data = request.json
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        channel_url = data.get("channel_url", "").strip()
        if not channel_url:
            return jsonify({"error": "No channel URL provided"}), 400

        # Basic YouTube URL validation
        is_valid_channel = (
            "youtube.com/@" in channel_url or "youtube.com/c/" in channel_url or "youtube.com/channel/" in channel_url
        )
        if not is_valid_channel:
            return jsonify({"error": "Invalid YouTube channel URL"}), 400

        channels_file = settings.channels_file
        channels = download_manager.load_channels()

        # Check if already exists
        if channel_url in channels:
            return jsonify({"error": "Channel already exists"}), 400

        # Append to file
        with open(channels_file, "a") as f:
            f.write(f"\n{channel_url}\n")

        logger.info(f"Added channel: {channel_url}")
        return jsonify({"message": "Channel added successfully", "channel_url": channel_url})

    @app.route("/api/channels", methods=["DELETE"])
    @auth.login_required
    def remove_channel() -> tuple:
        """Remove a channel from channels.txt."""
        data = request.json
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        channel_url = data.get("channel_url", "").strip()
        if not channel_url:
            return jsonify({"error": "No channel URL provided"}), 400

        channels_file = settings.channels_file
        channels = download_manager.load_channels()

        if channel_url not in channels:
            return jsonify({"error": "Channel not found"}), 404

        # Remove from list and rewrite file
        channels.remove(channel_url)
        with open(channels_file, "w") as f:
            f.write("\n".join(channels) + "\n")

        logger.info(f"Removed channel: {channel_url}")
        return jsonify({"message": "Channel removed successfully"})

    @app.route("/api/download/channel", methods=["POST"])
    @auth.login_required
    def download_channel() -> tuple:
        """Download latest videos from a single channel.

        Request body:
            channel_url (required): YouTube channel URL
            quality (optional): Quality preset - "default" (1080p HDR), "best" (4K HDR), or custom format string
        """
        data = request.json
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        channel_url = data.get("channel_url")
        if not channel_url:
            return jsonify({"error": "No channel URL provided"}), 400

        quality = data.get("quality", "best")  # Default to "best" for manual downloads
        download_id = download_manager.start_download(channel_url, quality=quality)
        return jsonify({"download_id": download_id, "quality": quality})

    @app.route("/api/download/all", methods=["POST"])
    @auth.login_required
    def download_all_channels() -> tuple:
        """Download latest videos from all configured channels."""
        channels = download_manager.load_channels()
        download_ids = []

        for channel_url in channels:
            download_id = download_manager.start_download(channel_url)
            download_ids.append(download_id)

        return jsonify({"download_ids": download_ids})

    @app.route("/api/status")
    @auth.login_required
    def get_all_status() -> tuple:
        """Get status of all downloads."""
        downloads = download_manager.get_all_downloads()
        return jsonify(
            {
                "downloads": {
                    dl_id: {
                        "channel_url": dl.channel_url,
                        "status": dl.status,
                        "progress": dl.progress,
                        "message": dl.message,
                        "started_at": dl.started_at,
                    }
                    for dl_id, dl in downloads.items()
                }
            }
        )

    @app.route("/api/queue")
    @auth.login_required
    def get_queue_status() -> tuple:
        """Get download queue status."""
        queue_status = download_manager.get_queue_status()
        return jsonify(queue_status)

    @app.route("/api/status/<download_id>")
    @auth.login_required
    def get_status(download_id: str) -> tuple:
        """Get status of a specific download."""
        download = download_manager.get_download(download_id)
        if not download:
            return jsonify({"error": "Download not found"}), 404

        return jsonify(
            {
                "id": download.id,
                "channel_url": download.channel_url,
                "status": download.status,
                "progress": download.progress,
                "message": download.message,
                "output": download.output,
                "started_at": download.started_at,
            }
        )

    @app.route("/api/files")
    def list_files() -> tuple:
        """List all downloaded files grouped by channel."""
        files_by_channel: dict = {}
        download_dir = settings.download_dir

        if not download_dir.exists():
            return jsonify({"files": {}})

        for channel_dir in download_dir.iterdir():
            if channel_dir.is_dir() and not channel_dir.name.startswith("."):
                files = []
                for video_file in channel_dir.glob("*"):
                    if video_file.suffix in [".mp4", ".mkv", ".webm"]:
                        stat = video_file.stat()
                        files.append(
                            {
                                "name": video_file.name,
                                "size": stat.st_size,
                                "modified": stat.st_mtime,
                            }
                        )

                if files:
                    files_by_channel[channel_dir.name] = sorted(files, key=lambda x: x["modified"], reverse=True)

        return jsonify({"files": files_by_channel})

    @app.route("/api/videos")
    def get_videos() -> tuple:
        """Get all videos from database grouped by channel."""
        videos_by_channel: dict = {}

        for channel_name in database.get_channel_names():
            videos = database.get_videos_by_channel(channel_name)
            videos_by_channel[channel_name] = [
                {
                    "id": v.id,
                    "video_id": v.video_id,
                    "title": v.title,
                    "upload_date": v.upload_date,
                    "file_path": v.file_path,
                    "file_size": v.file_size,
                    "file_exists": v.file_exists,
                    "downloaded_at": v.downloaded_at.isoformat(),
                    "keep_forever": v.keep_forever,
                    "channel_url": v.channel_url,
                }
                for v in videos
            ]

        return jsonify(
            {
                "videos": videos_by_channel,
                "stats": database.get_stats(),
            }
        )

    @app.route("/api/videos/<video_id>", methods=["DELETE"])
    def delete_video(video_id: str) -> tuple:
        """Delete a video by its YouTube video ID."""
        video = database.get_video_by_id(video_id)
        if not video:
            return jsonify({"error": "Video not found"}), 404

        # Block deletion of pinned videos
        if video.keep_forever:
            return jsonify({"error": "This video is pinned. Unpin it first to delete.", "pinned": True}), 403

        success = database.delete_video(video_id, delete_file=True)
        if success:
            return jsonify({"message": f"Deleted: {video.title}"})
        else:
            return jsonify({"error": "Failed to delete video"}), 500

    @app.route("/api/videos/<video_id>/pin", methods=["PATCH"])
    @auth.login_required
    def toggle_pin_video(video_id: str) -> tuple:
        """Pin or unpin a video to prevent automatic cleanup."""
        data = request.json
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        keep_forever = data.get("keep_forever", False)

        success = database.set_keep_forever(video_id, keep_forever)
        if not success:
            return jsonify({"error": "Video not found"}), 404

        # Sync with Plex Keepers collection if Plex is enabled
        if download_manager.plex:
            video = database.get_video_by_id(video_id)
            if video:
                if keep_forever:
                    download_manager.plex.add_to_keepers(video.file_path)
                else:
                    download_manager.plex.remove_from_keepers(video.file_path)

        action = "pinned" if keep_forever else "unpinned"
        return jsonify({"message": f"Video {action} successfully", "keep_forever": keep_forever})

    @app.route("/api/channels/<path:channel_url>/settings", methods=["GET"])
    @auth.login_required
    def get_channel_settings(channel_url: str) -> tuple:
        """Get per-channel settings."""
        limit = database.get_channel_limit(channel_url)
        return jsonify(
            {
                "channel_url": channel_url,
                "video_limit": limit,
                "using_default": limit is None,
                "default_limit": settings.videos_per_channel,
            }
        )

    @app.route("/api/channels/<path:channel_url>/settings", methods=["PUT"])
    @auth.login_required
    def update_channel_settings(channel_url: str) -> tuple:
        """Update per-channel settings."""
        data = request.json
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        video_limit = data.get("video_limit")
        if video_limit is not None:
            if video_limit <= 0:
                return jsonify({"error": "Video limit must be positive"}), 400

            database.set_channel_limit(channel_url, video_limit)
            return jsonify(
                {
                    "message": "Channel settings updated",
                    "channel_url": channel_url,
                    "video_limit": video_limit,
                }
            )
        else:
            # Delete custom limit (revert to default)
            database.delete_channel_limit(channel_url)
            return jsonify(
                {
                    "message": "Reverted to default limit",
                    "channel_url": channel_url,
                    "video_limit": settings.videos_per_channel,
                }
            )

    @app.route("/api/scheduler")
    def get_scheduler_status() -> tuple:
        """Get scheduler status."""
        return jsonify(scheduler.get_status())

    @app.route("/api/scheduler/run-now", methods=["POST"])
    def run_scheduler_now() -> tuple:
        """Trigger immediate download of all channels."""
        scheduler.run_now()
        return jsonify({"message": "Download triggered"})

    @app.route("/api/stats")
    def get_stats() -> tuple:
        """Get database and scheduler statistics."""
        return jsonify(
            {
                "database": database.get_stats(),
                "scheduler": scheduler.get_status(),
                "settings": {
                    "videos_per_channel": settings.videos_per_channel,
                    "download_dir": str(settings.download_dir),
                },
            }
        )

    @app.route("/api/scan", methods=["POST"])
    def scan_existing() -> tuple:
        """Scan download directory for existing videos and add to database."""
        try:
            # First cleanup orphan entries
            orphans_removed = database.cleanup_orphans()
            # Then scan for new videos
            added_count = download_manager.scan_existing_videos()
            return jsonify(
                {
                    "message": f"Scan complete - added {added_count} videos, removed {orphans_removed} orphans",
                    "added_count": added_count,
                    "orphans_removed": orphans_removed,
                }
            )
        except Exception as e:
            logger.exception(f"Scan failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/cleanup", methods=["POST"])
    def cleanup_orphans() -> tuple:
        """Remove database entries for files that no longer exist."""
        try:
            removed = database.cleanup_orphans()
            return jsonify(
                {
                    "message": f"Cleanup complete - removed {removed} orphan entries",
                    "removed": removed,
                }
            )
        except Exception as e:
            logger.exception(f"Cleanup failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/cleanup/enforce-structure", methods=["POST"])
    def enforce_directory_structure() -> tuple:
        """Trigger directory structure enforcement (consolidate duplicates, cleanup metadata folders)."""
        try:
            logger.info("Manual directory structure enforcement triggered")
            download_manager._enforce_directory_structure(None)
            return jsonify({"message": "Directory structure enforcement complete", "status": "success"})
        except Exception as e:
            logger.exception(f"Directory structure enforcement failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/cleanup/fix-dates", methods=["POST"])
    def fix_file_dates() -> tuple:
        """Fix file modification times to match upload dates (for Plex release date)."""
        try:
            logger.info("Fixing file modification times for all videos")

            fixed_count = 0
            error_count = 0

            # Scan all channel directories
            for channel_dir in settings.download_dir.iterdir():
                if not channel_dir.is_dir() or channel_dir.name.startswith("."):
                    continue

                # Scan video folders
                for video_folder in channel_dir.iterdir():
                    if not video_folder.is_dir():
                        continue

                    # Find .info.json to get upload_date
                    info_files = list(video_folder.glob("*.info.json"))
                    if not info_files:
                        continue

                    try:
                        with open(info_files[0]) as f:
                            metadata = json.load(f)

                        upload_date_str = metadata.get("upload_date")
                        if not upload_date_str:
                            continue

                        # Parse upload_date and create timestamp
                        upload_datetime = datetime.strptime(upload_date_str, "%Y%m%d")
                        upload_timestamp = upload_datetime.replace(hour=12).timestamp()

                        # Set mtime for all files in folder
                        for file in video_folder.iterdir():
                            if file.is_file():
                                os.utime(file, (upload_timestamp, upload_timestamp))

                        fixed_count += 1
                        logger.debug(f"Fixed dates for: {video_folder.name}")

                    except Exception as e:
                        logger.debug(f"Could not fix {video_folder.name}: {e}")
                        error_count += 1

            logger.info(f"✅ Fixed {fixed_count} video folders, {error_count} errors")

            return jsonify(
                {
                    "message": f"Fixed file dates for {fixed_count} videos",
                    "fixed": fixed_count,
                    "errors": error_count,
                    "status": "success",
                }
            )

        except Exception as e:
            logger.exception(f"Date fixing failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/plex/fix-dates", methods=["POST"])
    def fix_plex_dates() -> tuple:
        """Fix Plex originallyAvailableAt field to match upload dates."""
        if not settings.plex_enabled:
            return jsonify({"error": "Plex integration not configured"}), 400

        try:
            logger.info("Fixing Plex originallyAvailableAt dates")

            # Get all items from Plex
            from youtube_downloader.plex import PlexIntegration

            plex = PlexIntegration(settings.plex_url, settings.plex_token, settings.plex_library_id)
            items = plex.get_all_items()

            fixed_count = 0
            skipped_count = 0

            for item in items:
                file_path = item.get("file", "")
                rating_key = item.get("ratingKey")

                if not file_path or not rating_key:
                    continue

                # Extract date from filename (format: YYYYMMDD_Title.mp4)
                filename = Path(file_path).name
                date_match = re.match(r"(\d{8})_", filename)

                if not date_match:
                    logger.debug(f"No date prefix in filename: {filename}")
                    skipped_count += 1
                    continue

                upload_date_str = date_match.group(1)

                try:
                    # Parse date (YYYYMMDD -> YYYY-MM-DD)
                    upload_date = datetime.strptime(upload_date_str, "%Y%m%d")
                    date_formatted = upload_date.strftime("%Y-%m-%d")

                    # Update Plex metadata via API
                    # PUT /library/metadata/{ratingKey}?originallyAvailableAt.value=YYYY-MM-DD
                    response = plex._put(
                        f"/library/metadata/{rating_key}", params={"originallyAvailableAt.value": date_formatted}
                    )

                    if response.status_code == 200:
                        logger.debug(f"Updated {filename[:40]}... to {date_formatted}")
                        fixed_count += 1
                    else:
                        logger.warning(f"Failed to update {rating_key}: {response.status_code}")
                        skipped_count += 1

                except Exception as e:
                    logger.debug(f"Error updating {filename}: {e}")
                    skipped_count += 1

            logger.info(f"✅ Fixed {fixed_count} Plex dates, {skipped_count} skipped")

            return jsonify(
                {
                    "message": f"Fixed Plex dates for {fixed_count} videos",
                    "fixed": fixed_count,
                    "skipped": skipped_count,
                    "status": "success",
                }
            )

        except Exception as e:
            logger.exception(f"Plex date fixing failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/plex/create-channel-collections", methods=["POST"])
    def create_channel_collections() -> tuple:
        """Create Plex collections for each YouTube channel with channel avatars."""
        if not settings.plex_enabled:
            return jsonify({"error": "Plex integration not configured"}), 400

        try:
            from youtube_downloader.plex import PlexIntegration

            logger.info("Creating channel collections in Plex")

            plex = PlexIntegration(settings.plex_url, settings.plex_token, settings.plex_library_id)

            created = 0
            updated = 0
            errors = 0

            # Get all items from Plex
            all_items = plex.get_all_items()

            # Group items by channel folder
            channel_items = {}
            for item in all_items:
                file_path = item.get("file", "")
                if not file_path:
                    continue

                # Extract channel folder name from path
                # /mnt/media/.../ChannelName/VideoFolder/video.mp4
                parts = Path(file_path).parts
                if len(parts) >= 2:
                    channel_name = parts[-3]  # ChannelName is 3 levels up from video file
                    if channel_name not in channel_items:
                        channel_items[channel_name] = []
                    channel_items[channel_name].append(item)

            logger.info(f"Found {len(channel_items)} channels")

            # Create/update collection for each channel
            for channel_name, items in channel_items.items():
                try:
                    # Fetch all channel videos as Plex items
                    plex_items = []
                    for item in items:
                        rating_key = item.get("ratingKey")
                        if rating_key:
                            plex_item = plex.plex.fetchItem(f"/library/metadata/{rating_key}")
                            plex_items.append(plex_item)

                    if not plex_items:
                        logger.warning(f"No items found for {channel_name}, skipping")
                        continue

                    # Get or create collection
                    collection = None
                    for coll in plex.library.collections():
                        if coll.title == channel_name:
                            collection = coll
                            logger.debug(f"Found existing collection: {channel_name}")
                            break

                    if not collection:
                        # Create new collection WITH items (required by Plex)
                        collection = plex.library.createCollection(title=channel_name, items=plex_items)
                        logger.info(f"Created collection: {channel_name} with {len(plex_items)} items")
                        created += 1
                    else:
                        # Update existing collection
                        collection.addItems(plex_items)
                        logger.debug(f"Added {len(plex_items)} items to {channel_name}")
                        updated += 1

                    # Upload channel avatar as collection poster
                    channel_dir = settings.download_dir / channel_name
                    folder_jpg = channel_dir / "folder.jpg"

                    if folder_jpg.exists():
                        with open(folder_jpg, "rb") as f:
                            collection.uploadPoster(filepath=f)
                        collection.lockPoster()
                        logger.info(f"Uploaded poster for collection: {channel_name}")

                except Exception as e:
                    logger.error(f"Error creating collection for {channel_name}: {e}")
                    errors += 1

            logger.info(f"✅ Created {created} collections, updated {updated}, {errors} errors")

            return jsonify(
                {
                    "message": f"Created {created} channel collections, updated {updated}",
                    "created": created,
                    "updated": updated,
                    "errors": errors,
                    "status": "success",
                }
            )

        except Exception as e:
            logger.exception(f"Collection creation failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/plex/download-channel-posters", methods=["POST"])
    def download_channel_posters() -> tuple:
        """Download YouTube channel avatars and save as poster.jpg in channel folders."""
        try:
            logger.info("Downloading YouTube channel avatars")

            downloaded = 0
            skipped = 0
            errors = 0

            # Scan all channel directories
            for channel_dir in settings.download_dir.iterdir():
                if not channel_dir.is_dir() or channel_dir.name.startswith("."):
                    continue

                # Check if poster already exists
                # Plex expects folder.jpg for folder posters in Movies libraries
                poster_path = channel_dir / "folder.jpg"
                if poster_path.exists():
                    logger.debug(f"Poster exists: {channel_dir.name}")
                    skipped += 1
                    continue

                # Find any .info.json to get channel info
                info_file = None
                for video_folder in channel_dir.iterdir():
                    if video_folder.is_dir():
                        info_files = list(video_folder.glob("*.info.json"))
                        if info_files:
                            info_file = info_files[0]
                            break

                if not info_file:
                    logger.debug(f"No info.json found for {channel_dir.name}")
                    errors += 1
                    continue

                try:
                    # Load metadata
                    with open(info_file) as f:
                        metadata = json.load(f)

                    # Get channel URL (e.g., https://www.youtube.com/@Bhavss14)
                    channel_url = metadata.get("uploader_url") or metadata.get("channel_url")

                    if not channel_url:
                        logger.warning(f"No channel URL found for {channel_dir.name}")
                        errors += 1
                        continue

                    # Fetch channel page to extract avatar URL
                    # YouTube channel avatars are in og:image meta tag
                    try:
                        response = requests.get(
                            channel_url,
                            timeout=10,
                            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                        )
                        response.raise_for_status()

                        # Extract og:image from HTML (channel avatar)
                        og_image_match = re.search(r'<meta property="og:image" content="([^"]+)"', response.text)

                        if not og_image_match:
                            logger.warning(f"Could not extract avatar from {channel_url}")
                            errors += 1
                            continue

                        avatar_url = og_image_match.group(1)

                        # Download avatar
                        avatar_response = requests.get(avatar_url, timeout=10)
                        if avatar_response.status_code == 200:
                            with open(poster_path, "wb") as f:
                                f.write(avatar_response.content)
                            logger.info(f"Downloaded avatar for {channel_dir.name}")
                            downloaded += 1
                        else:
                            logger.warning(f"Failed to download avatar: {avatar_response.status_code}")
                            errors += 1

                    except requests.RequestException as e:
                        logger.warning(f"Error fetching channel page for {channel_dir.name}: {e}")
                        errors += 1

                except Exception as e:
                    logger.error(f"Error processing {channel_dir.name}: {e}")
                    errors += 1

            logger.info(f"✅ Downloaded {downloaded} channel avatars, {skipped} skipped, {errors} errors")

            # Trigger Plex refresh to pick up new posters
            if settings.plex_enabled and downloaded > 0:
                from youtube_downloader.plex import PlexIntegration

                plex = PlexIntegration(settings.plex_url, settings.plex_token, settings.plex_library_id)
                plex.refresh_library()
                logger.info("Triggered Plex library refresh")

            return jsonify(
                {
                    "message": f"Downloaded {downloaded} channel avatars",
                    "downloaded": downloaded,
                    "skipped": skipped,
                    "errors": errors,
                    "status": "success",
                }
            )

        except Exception as e:
            logger.exception(f"Channel poster download failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/sync", methods=["POST"])
    def sync_library() -> tuple:
        """Comprehensive sync: cleanup old files, remove orphans, scan for new videos."""
        try:
            # Step 1: Remove old flat-structure files
            flat_cleanup = download_manager.cleanup_flat_structure_files()

            # Step 2: Remove orphaned database entries
            orphans_removed = database.cleanup_orphans()

            # Step 3: Scan for new videos
            added_count = download_manager.scan_existing_videos()

            message = (
                f"Sync complete - "
                f"removed {flat_cleanup['videos']} old videos, "
                f"{flat_cleanup['posters']} posters, "
                f"{flat_cleanup['info']} info files "
                f"({flat_cleanup['locked']} locked files skipped), "
                f"cleaned {orphans_removed} orphan DB entries, "
                f"added {added_count} new videos"
            )

            return jsonify(
                {
                    "message": message,
                    "flat_cleanup": flat_cleanup,
                    "orphans_removed": orphans_removed,
                    "videos_added": added_count,
                }
            )
        except Exception as e:
            logger.exception(f"Sync failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/settings", methods=["GET"])
    def get_settings() -> tuple:
        """Get current application settings."""
        return jsonify(
            {
                "download_dir": str(settings.download_dir),
                "videos_per_channel": settings.videos_per_channel,
                "max_quality": settings.max_quality,
            }
        )

    @app.route("/api/settings", methods=["POST"])
    def update_settings() -> tuple:
        """Update application settings."""
        data = request.json
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        download_dir = data.get("download_dir")
        videos_per_channel = data.get("videos_per_channel")

        try:
            settings.update_runtime_config(
                download_dir=download_dir,
                videos_per_channel=videos_per_channel,
            )

            # Ensure new download directory exists
            if download_dir:
                settings.ensure_download_dir()

            logger.info(
                f"Settings updated: download_dir={settings.download_dir}, "
                f"videos_per_channel={settings.videos_per_channel}"
            )

            return jsonify(
                {
                    "message": "Settings updated",
                    "download_dir": str(settings.download_dir),
                    "videos_per_channel": settings.videos_per_channel,
                }
            )
        except Exception as e:
            logger.exception(f"Failed to update settings: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/nuke", methods=["POST"])
    @auth.login_required
    def nuke_download_folder() -> tuple:
        """DESTRUCTIVE: Delete all files in download directory and clear database.

        Requires confirmation token in request body.
        """
        data = request.json
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        # Require confirmation token
        confirmation = data.get("confirmation", "").strip()
        if confirmation != "DELETE EVERYTHING":
            return jsonify({"error": "Invalid confirmation token"}), 400

        try:
            deleted_files = 0
            deleted_dirs = 0
            errors = []

            # Delete all contents of download directory
            download_dir = settings.download_dir
            if download_dir.exists():
                for item in download_dir.iterdir():
                    try:
                        if item.is_file():
                            item.unlink()
                            deleted_files += 1
                        elif item.is_dir():
                            shutil.rmtree(item)
                            deleted_dirs += 1
                    except Exception as e:
                        errors.append(f"{item.name}: {str(e)}")
                        logger.warning(f"Could not delete {item}: {e}")

            # Clear database
            database.clear_all_videos()

            # Delete download archive
            archive_file = settings.archive_file
            if archive_file.exists():
                archive_file.unlink()
                logger.info("Deleted download archive")

            message = (
                f"Nuclear cleanup complete - "
                f"deleted {deleted_files} files, "
                f"{deleted_dirs} directories, "
                f"cleared database, "
                f"reset download archive"
            )

            if errors:
                message += f" ({len(errors)} errors)"

            logger.warning(f"NUKE executed: {message}")

            return jsonify(
                {
                    "message": message,
                    "deleted_files": deleted_files,
                    "deleted_dirs": deleted_dirs,
                    "errors": errors,
                }
            )

        except Exception as e:
            logger.exception(f"Nuke operation failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/logs", methods=["GET"])
    def get_logs() -> tuple:
        """Get log file contents with optional filtering.

        Query parameters:
            lines: Number of recent lines to return (default: 100, max: 1000)
            level: Filter by log level (DEBUG, INFO, WARNING, ERROR)
            search: Search term to filter log lines
        """
        try:
            log_file = settings.log_dir / "app.log"
            if not log_file.exists():
                return jsonify({"error": "Log file not found"}), 404

            # Get query parameters
            lines = min(int(request.args.get("lines", 100)), 1000)
            level_filter = request.args.get("level", "").upper()
            search_term = request.args.get("search", "")

            # Read log file
            with open(log_file, encoding="utf-8", errors="ignore") as f:
                all_lines = f.readlines()

            # Get last N lines
            recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines

            # Apply filters
            filtered_lines = []
            for line in recent_lines:
                # Level filter
                if level_filter and f"| {level_filter} " not in line:
                    continue
                # Search filter
                if search_term and search_term.lower() not in line.lower():
                    continue
                filtered_lines.append(line.rstrip())

            return jsonify(
                {
                    "lines": filtered_lines,
                    "total_lines": len(all_lines),
                    "filtered_lines": len(filtered_lines),
                    "log_file": str(log_file),
                }
            )

        except Exception as e:
            logger.exception(f"Failed to read logs: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/logs/download", methods=["GET"])
    def download_log_file() -> tuple:
        """Download the full log file."""
        try:
            log_file = settings.log_dir / "app.log"
            if not log_file.exists():
                return jsonify({"error": "Log file not found"}), 404

            return send_file(
                log_file,
                as_attachment=True,
                download_name=f"youtube-downloader-{log_file.name}",
                mimetype="text/plain",
            )
        except Exception as e:
            logger.exception(f"Failed to download log file: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/logs/level", methods=["POST"])
    @auth.login_required
    def set_log_level() -> tuple:
        """Change logging level dynamically.

        Request body:
            level: Log level (DEBUG, INFO, WARNING, ERROR)
        """
        data = request.json
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        level = data.get("level", "").upper()
        if level not in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            return jsonify({"error": "Invalid log level. Use DEBUG, INFO, WARNING, or ERROR"}), 400

        try:
            # Update loguru log level for console handler
            logger.remove()
            setup_logger(debug=(level == "DEBUG"), log_dir=settings.log_dir)

            logger.info(f"Log level changed to {level}")

            return jsonify(
                {
                    "message": f"Log level set to {level}",
                    "level": level,
                }
            )

        except Exception as e:
            logger.exception(f"Failed to set log level: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/restart", methods=["POST"])
    @auth.login_required
    def restart_server() -> tuple:
        """Restart the application server.

        Note: This only works when running as a systemd service or with a process manager.
        In debug mode, use Ctrl+C and restart manually, or just save files for auto-reload.
        """
        try:
            if settings.debug:
                # In debug mode, trigger werkzeug reloader by touching a file
                logger.warning("Restart requested in debug mode - triggering auto-reload")
                # Touch the main app file to trigger reload
                app_file = Path(__file__)
                os.utime(app_file, (time.time(), time.time()))
                return jsonify({"message": "Debug mode: Auto-reload triggered. Server will restart momentarily."})
            else:
                # In production, send SIGHUP to trigger graceful restart (systemd handles this)
                logger.warning("Restart requested - sending SIGHUP")
                os.kill(os.getpid(), signal.SIGHUP)
                return jsonify({"message": "Restart signal sent. Server will restart shortly."})

        except Exception as e:
            logger.exception(f"Failed to restart server: {e}")
            return jsonify({"error": str(e), "note": "Manual restart required: Ctrl+C then re-run serve command"}), 500

    @app.route("/api/cleanup/preview", methods=["POST"])
    @auth.login_required
    def preview_cleanup():
        """Preview what will be deleted without actually deleting."""
        data = request.json or {}
        keep_count = data.get("keep_count", 3)

        try:
            logger.info(f"Cleanup preview requested (keep_count={keep_count})")
            result = app.cleanup_manager.cleanup_keep_last_n(keep_count=keep_count, preview=True)
            logger.info(f"Cleanup preview: {result['videos_to_delete']} videos, {result['space_to_free_gb']} GB")
            return jsonify(result)
        except Exception as e:
            logger.exception(f"Cleanup preview failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/cleanup/execute", methods=["POST"])
    @auth.login_required
    def execute_cleanup():
        """Execute cleanup operation."""
        data = request.json or {}
        keep_count = data.get("keep_count", 3)

        try:
            logger.warning(f"Cleanup execution started (keep_count={keep_count})")
            result = app.cleanup_manager.cleanup_keep_last_n(keep_count=keep_count, preview=False)
            logger.warning(
                f"Cleanup complete: {result['videos_deleted']} videos deleted, {result['space_freed_gb']} GB freed"
            )
            return jsonify(result)
        except Exception as e:
            logger.exception(f"Cleanup execution failed: {e}")
            return jsonify({"error": str(e)}), 500

    return app
