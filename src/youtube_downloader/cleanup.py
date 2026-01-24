"""Cleanup manager for downloaded videos."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from youtube_downloader.database import Database


@dataclass
class CleanupStats:
    """Statistics from a cleanup operation."""

    videos_deleted: int
    space_freed_mb: float
    channels_processed: int


class CleanupManager:
    """Manages cleanup operations for downloaded videos."""

    def __init__(self, database: "Database"):
        """Initialize cleanup manager.

        Args:
            database: Database instance
        """
        self.database = database

    def cleanup_keep_last_n(self, keep_count: int = 3, preview: bool = False) -> dict:
        """Keep only the last N videos per channel.

        Args:
            keep_count: Number of most recent videos to keep per channel
            preview: If True, return what would be deleted without deleting

        Returns:
            Dictionary with stats and preview data
        """
        stats = CleanupStats(videos_deleted=0, space_freed_mb=0.0, channels_processed=0)
        preview_videos = []

        # Get all unique channels
        with self.database._get_connection() as conn:
            cursor = conn.execute(
                "SELECT DISTINCT channel_url, channel_name FROM videos ORDER BY channel_name"
            )
            channels = cursor.fetchall()

        for channel in channels:
            channel_url = channel["channel_url"]
            channel_name = channel["channel_name"]

            # Get videos for this channel, sorted by upload date (newest first)
            # Upload date format is YYYYMMDD, so string sort works
            with self.database._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT id, video_id, title, file_path, file_size, upload_date, keep_forever
                    FROM videos
                    WHERE channel_url = ?
                    ORDER BY upload_date DESC, downloaded_at DESC
                    """,
                    (channel_url,),
                )
                videos = cursor.fetchall()

            # Keep first N, mark rest for deletion
            videos_to_delete = videos[keep_count:]

            for video in videos_to_delete:
                # Skip pinned videos
                if video["keep_forever"]:
                    logger.info(
                        f"[{channel_name}] Skipping pinned video: {video['title']}"
                    )
                    continue

                file_path = Path(video["file_path"])
                size_mb = 0.0

                # Calculate size
                if file_path.exists():
                    size_mb = file_path.stat().st_size / 1024 / 1024
                    stats.space_freed_mb += size_mb

                if preview:
                    # Add to preview list
                    preview_videos.append(
                        {
                            "video_id": video["video_id"],
                            "title": video["title"],
                            "channel_name": channel_name,
                            "upload_date": video["upload_date"],
                            "file_path": str(file_path),
                            "size_mb": round(size_mb, 2),
                        }
                    )
                    stats.videos_deleted += 1
                else:
                    # Actually delete
                    try:
                        self.database.delete_video(
                            video["video_id"], delete_file=True
                        )
                        stats.videos_deleted += 1
                        logger.info(
                            f"[{channel_name}] Deleted old video: {video['title']} "
                            f"({size_mb:.2f} MB)"
                        )
                    except Exception as e:
                        logger.error(
                            f"[{channel_name}] Failed to delete {video['title']}: {e}"
                        )

            stats.channels_processed += 1

        if preview:
            return {
                "preview": True,
                "videos_to_delete": stats.videos_deleted,
                "space_to_free_mb": round(stats.space_freed_mb, 2),
                "space_to_free_gb": round(stats.space_freed_mb / 1024, 2),
                "channels_processed": stats.channels_processed,
                "videos": preview_videos,
            }
        else:
            logger.info(
                f"Cleanup complete: {stats.videos_deleted} videos deleted, "
                f"{stats.space_freed_mb:.2f} MB freed from {stats.channels_processed} channels"
            )
            return {
                "preview": False,
                "videos_deleted": stats.videos_deleted,
                "space_freed_mb": round(stats.space_freed_mb, 2),
                "space_freed_gb": round(stats.space_freed_mb / 1024, 2),
                "channels_processed": stats.channels_processed,
            }
