"""Flask application for YouTube Downloader.

This module provides the Flask web application with API routes for
downloading YouTube videos and checking download status.
"""

import atexit
import ipaddress

from flask import Flask, jsonify, render_template, request
from flask_httpauth import HTTPBasicAuth
from loguru import logger
from werkzeug.security import check_password_hash, generate_password_hash

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

    # Create scheduler (only in main process, not reloader)
    # When Flask debug mode is on, it creates a reloader process that would also start the scheduler
    # We only want the scheduler in the main process
    import os
    is_reloader = os.environ.get("WERKZEUG_RUN_MAIN") == "true"

    if not settings.debug or is_reloader:
        scheduler = DownloadScheduler(settings)
        scheduler.set_download_callback(download_manager.download_all_channels)
        scheduler.start(interval_hours=2.0)

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
        return jsonify({
            "channels": channels,
            "videos_per_channel": settings.videos_per_channel,
        })

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
        if not ("youtube.com/@" in channel_url or "youtube.com/c/" in channel_url or "youtube.com/channel/" in channel_url):
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
        """Download latest videos from a single channel."""
        data = request.json
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        channel_url = data.get("channel_url")
        if not channel_url:
            return jsonify({"error": "No channel URL provided"}), 400

        download_id = download_manager.start_download(channel_url)
        return jsonify({"download_id": download_id})

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
        return jsonify({
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
        })

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

        return jsonify({
            "id": download.id,
            "channel_url": download.channel_url,
            "status": download.status,
            "progress": download.progress,
            "message": download.message,
            "output": download.output,
            "started_at": download.started_at,
        })

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
                        files.append({
                            "name": video_file.name,
                            "size": stat.st_size,
                            "modified": stat.st_mtime,
                        })

                if files:
                    files_by_channel[channel_dir.name] = sorted(
                        files, key=lambda x: x["modified"], reverse=True
                    )

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

        return jsonify({
            "videos": videos_by_channel,
            "stats": database.get_stats(),
        })

    @app.route("/api/videos/<video_id>", methods=["DELETE"])
    def delete_video(video_id: str) -> tuple:
        """Delete a video by its YouTube video ID."""
        video = database.get_video_by_id(video_id)
        if not video:
            return jsonify({"error": "Video not found"}), 404

        # Block deletion of pinned videos
        if video.keep_forever:
            return jsonify({
                "error": "This video is pinned. Unpin it first to delete.",
                "pinned": True
            }), 403

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
        return jsonify({
            "channel_url": channel_url,
            "video_limit": limit,
            "using_default": limit is None,
            "default_limit": settings.videos_per_channel,
        })

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
            return jsonify({
                "message": "Channel settings updated",
                "channel_url": channel_url,
                "video_limit": video_limit,
            })
        else:
            # Delete custom limit (revert to default)
            database.delete_channel_limit(channel_url)
            return jsonify({
                "message": "Reverted to default limit",
                "channel_url": channel_url,
                "video_limit": settings.videos_per_channel,
            })

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
        return jsonify({
            "database": database.get_stats(),
            "scheduler": scheduler.get_status(),
            "settings": {
                "videos_per_channel": settings.videos_per_channel,
                "download_dir": str(settings.download_dir),
            },
        })

    @app.route("/api/scan", methods=["POST"])
    def scan_existing() -> tuple:
        """Scan download directory for existing videos and add to database."""
        try:
            # First cleanup orphan entries
            orphans_removed = database.cleanup_orphans()
            # Then scan for new videos
            added_count = download_manager.scan_existing_videos()
            return jsonify({
                "message": f"Scan complete - added {added_count} videos, removed {orphans_removed} orphans",
                "added_count": added_count,
                "orphans_removed": orphans_removed,
            })
        except Exception as e:
            logger.exception(f"Scan failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/cleanup", methods=["POST"])
    def cleanup_orphans() -> tuple:
        """Remove database entries for files that no longer exist."""
        try:
            removed = database.cleanup_orphans()
            return jsonify({
                "message": f"Cleanup complete - removed {removed} orphan entries",
                "removed": removed,
            })
        except Exception as e:
            logger.exception(f"Cleanup failed: {e}")
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

            return jsonify({
                "message": message,
                "flat_cleanup": flat_cleanup,
                "orphans_removed": orphans_removed,
                "videos_added": added_count,
            })
        except Exception as e:
            logger.exception(f"Sync failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/settings", methods=["GET"])
    def get_settings() -> tuple:
        """Get current application settings."""
        return jsonify({
            "download_dir": str(settings.download_dir),
            "videos_per_channel": settings.videos_per_channel,
            "max_quality": settings.max_quality,
        })

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

            logger.info(f"Settings updated: download_dir={settings.download_dir}, videos_per_channel={settings.videos_per_channel}")

            return jsonify({
                "message": "Settings updated",
                "download_dir": str(settings.download_dir),
                "videos_per_channel": settings.videos_per_channel,
            })
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
            import shutil
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

            return jsonify({
                "message": message,
                "deleted_files": deleted_files,
                "deleted_dirs": deleted_dirs,
                "errors": errors,
            })

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
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
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

            return jsonify({
                "lines": filtered_lines,
                "total_lines": len(all_lines),
                "filtered_lines": len(filtered_lines),
                "log_file": str(log_file),
            })

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

            from flask import send_file
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

            return jsonify({
                "message": f"Log level set to {level}",
                "level": level,
            })

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
        import os
        import signal

        try:
            if settings.debug:
                # In debug mode, trigger werkzeug reloader by touching a file
                logger.warning("Restart requested in debug mode - triggering auto-reload")
                # Touch the main app file to trigger reload
                import time
                app_file = Path(__file__)
                os.utime(app_file, (time.time(), time.time()))
                return jsonify({
                    "message": "Debug mode: Auto-reload triggered. Server will restart momentarily."
                })
            else:
                # In production, send SIGHUP to trigger graceful restart (systemd handles this)
                logger.warning("Restart requested - sending SIGHUP")
                os.kill(os.getpid(), signal.SIGHUP)
                return jsonify({
                    "message": "Restart signal sent. Server will restart shortly."
                })

        except Exception as e:
            logger.exception(f"Failed to restart server: {e}")
            return jsonify({
                "error": str(e),
                "note": "Manual restart required: Ctrl+C then re-run serve command"
            }), 500

    return app
