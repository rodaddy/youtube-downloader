"""SQLite database for tracking downloaded videos.

This module provides persistent storage for video metadata, enabling
cleanup of old videos and tracking of download history.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loguru import logger


@dataclass
class Video:
    """Represents a downloaded video in the database."""

    id: int
    channel_name: str
    channel_url: str
    video_id: str
    title: str
    upload_date: str
    file_path: str
    file_size: int
    downloaded_at: datetime
    info_json_path: str | None = None
    keep_forever: bool = False

    @property
    def file_exists(self) -> bool:
        """Check if the video file still exists on disk."""
        return Path(self.file_path).exists()


class Database:
    """SQLite database manager for video tracking."""

    def __init__(self, db_path: Path) -> None:
        """Initialize the database.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialize database schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_name TEXT NOT NULL,
                    channel_url TEXT NOT NULL,
                    video_id TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    upload_date TEXT,
                    file_path TEXT NOT NULL,
                    file_size INTEGER DEFAULT 0,
                    info_json_path TEXT,
                    downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    keep_forever INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS channel_settings (
                    channel_url TEXT PRIMARY KEY,
                    video_limit INTEGER NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_channel_name
                ON videos(channel_name)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_downloaded_at
                ON videos(downloaded_at)
            """)

            # Migration: Add keep_forever column if it doesn't exist
            cursor = conn.execute("PRAGMA table_info(videos)")
            columns = [row[1] for row in cursor.fetchall()]
            if "keep_forever" not in columns:
                conn.execute("ALTER TABLE videos ADD COLUMN keep_forever INTEGER DEFAULT 0")
                logger.info("Added keep_forever column to videos table")

            conn.commit()
            logger.debug(f"Database initialized at {self.db_path}")

    def add_video(
        self,
        channel_name: str,
        channel_url: str,
        video_id: str,
        title: str,
        upload_date: str,
        file_path: str,
        file_size: int = 0,
        info_json_path: str | None = None,
    ) -> int:
        """Add a video to the database.

        Args:
            channel_name: Name of the YouTube channel
            channel_url: URL of the channel
            video_id: YouTube video ID
            title: Video title
            upload_date: Upload date (YYYYMMDD format)
            file_path: Path to the downloaded video file
            file_size: Size of the video file in bytes
            info_json_path: Path to the .info.json file

        Returns:
            The ID of the inserted row
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR REPLACE INTO videos
                (channel_name, channel_url, video_id, title, upload_date,
                 file_path, file_size, info_json_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    channel_name,
                    channel_url,
                    video_id,
                    title,
                    upload_date,
                    file_path,
                    file_size,
                    info_json_path,
                ),
            )
            conn.commit()
            logger.info(f"Added video to DB: {title} ({video_id})")
            return cursor.lastrowid or 0

    def get_videos_by_channel(self, channel_name: str) -> list[Video]:
        """Get all videos for a channel, ordered by upload date descending.

        Args:
            channel_name: Name of the channel

        Returns:
            List of Video objects, newest first
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM videos
                WHERE channel_name = ?
                ORDER BY upload_date DESC, downloaded_at DESC
                """,
                (channel_name,),
            ).fetchall()
            return [self._row_to_video(row) for row in rows]

    def get_all_videos(self) -> list[Video]:
        """Get all videos in the database.

        Returns:
            List of all Video objects
        """
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM videos ORDER BY downloaded_at DESC").fetchall()
            return [self._row_to_video(row) for row in rows]

    def get_video_by_id(self, video_id: str) -> Video | None:
        """Get a video by its YouTube video ID.

        Args:
            video_id: YouTube video ID

        Returns:
            Video object or None if not found
        """
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM videos WHERE video_id = ?", (video_id,)).fetchone()
            return self._row_to_video(row) if row else None

    def delete_video(self, video_id: str, delete_file: bool = True) -> bool:
        """Delete a video from the database and optionally from disk.

        Args:
            video_id: YouTube video ID
            delete_file: Whether to also delete the file from disk

        Returns:
            True if deleted, False if not found
        """
        video = self.get_video_by_id(video_id)
        if not video:
            return False

        if delete_file:
            # Delete video file
            video_path = Path(video.file_path)
            if video_path.exists():
                video_path.unlink()
                logger.info(f"Deleted file: {video_path}")

            # Delete info.json if exists
            if video.info_json_path:
                info_path = Path(video.info_json_path)
                if info_path.exists():
                    info_path.unlink()
                    logger.debug(f"Deleted info.json: {info_path}")

        with self._get_connection() as conn:
            conn.execute("DELETE FROM videos WHERE video_id = ?", (video_id,))
            conn.commit()
            logger.info(f"Removed from DB: {video.title} ({video_id})")

        return True

    def clear_all_videos(self) -> int:
        """Delete all videos from the database.

        WARNING: This is a destructive operation.

        Returns:
            Number of videos deleted
        """
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM videos")
            count = cursor.fetchone()[0]
            conn.execute("DELETE FROM videos")
            conn.commit()
            logger.warning(f"Cleared all videos from database ({count} total)")
        return count

    def get_channel_names(self) -> list[str]:
        """Get list of unique channel names in the database.

        Returns:
            List of channel names
        """
        with self._get_connection() as conn:
            rows = conn.execute("SELECT DISTINCT channel_name FROM videos ORDER BY channel_name").fetchall()
            return [row["channel_name"] for row in rows]

    def get_videos_to_cleanup(self, channel_name: str, keep_count: int) -> list[Video]:
        """Get videos that should be deleted to maintain the per-channel limit.

        Args:
            channel_name: Name of the channel
            keep_count: Number of videos to keep

        Returns:
            List of videos to delete (oldest beyond the limit, excluding pinned)
        """
        videos = self.get_videos_by_channel(channel_name)

        # Filter out pinned videos (keep_forever = True)
        unpinned_videos = [v for v in videos if not v.keep_forever]

        if len(unpinned_videos) <= keep_count:
            return []
        return unpinned_videos[keep_count:]

    def set_keep_forever(self, video_id: str, keep_forever: bool) -> bool:
        """Pin or unpin a video to prevent automatic cleanup.

        Args:
            video_id: YouTube video ID
            keep_forever: True to pin, False to unpin

        Returns:
            True if updated, False if video not found
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE videos SET keep_forever = ? WHERE video_id = ?",
                (1 if keep_forever else 0, video_id),
            )
            conn.commit()
            success = cursor.rowcount > 0

        if success:
            action = "pinned" if keep_forever else "unpinned"
            logger.info(f"Video {video_id} {action}")

        return success

    def get_channel_limit(self, channel_url: str) -> int | None:
        """Get the per-channel video limit.

        Args:
            channel_url: URL of the channel

        Returns:
            Video limit for this channel, or None if using global default
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT video_limit FROM channel_settings WHERE channel_url = ?",
                (channel_url,),
            ).fetchone()

        return row["video_limit"] if row else None

    def set_channel_limit(self, channel_url: str, limit: int) -> None:
        """Set the per-channel video limit.

        Args:
            channel_url: URL of the channel
            limit: Number of videos to keep for this channel
        """
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO channel_settings (channel_url, video_limit)
                VALUES (?, ?)
                """,
                (channel_url, limit),
            )
            conn.commit()

        logger.info(f"Set video limit for {channel_url} to {limit}")

    def delete_channel_limit(self, channel_url: str) -> None:
        """Remove per-channel video limit (revert to global default).

        Args:
            channel_url: URL of the channel
        """
        with self._get_connection() as conn:
            conn.execute(
                "DELETE FROM channel_settings WHERE channel_url = ?",
                (channel_url,),
            )
            conn.commit()

        logger.info(f"Removed custom limit for {channel_url} (using global default)")

    def _row_to_video(self, row: sqlite3.Row) -> Video:
        """Convert a database row to a Video object."""
        # Get keep_forever with fallback for older databases
        try:
            keep_forever = bool(row["keep_forever"])
        except (KeyError, IndexError):
            keep_forever = False

        return Video(
            id=row["id"],
            channel_name=row["channel_name"],
            channel_url=row["channel_url"],
            video_id=row["video_id"],
            title=row["title"],
            upload_date=row["upload_date"] or "",
            file_path=row["file_path"],
            file_size=row["file_size"] or 0,
            info_json_path=row["info_json_path"],
            downloaded_at=datetime.fromisoformat(row["downloaded_at"]) if row["downloaded_at"] else datetime.now(),
            keep_forever=keep_forever,
        )

    def get_stats(self) -> dict:
        """Get database statistics.

        Returns:
            Dictionary with stats (total videos, total size, channels)
        """
        with self._get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
            total_size = conn.execute("SELECT SUM(file_size) FROM videos").fetchone()[0] or 0
            channels = conn.execute("SELECT COUNT(DISTINCT channel_name) FROM videos").fetchone()[0]

        return {
            "total_videos": total,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "channel_count": channels,
        }

    def cleanup_orphans(self) -> int:
        """Remove database entries where the file no longer exists.

        Returns:
            Number of orphan entries removed
        """
        videos = self.get_all_videos()
        removed = 0

        for video in videos:
            if not video.file_exists:
                with self._get_connection() as conn:
                    conn.execute("DELETE FROM videos WHERE video_id = ?", (video.video_id,))
                    conn.commit()
                logger.info(f"Removed orphan entry: {video.title}")
                removed += 1

        if removed:
            logger.info(f"Cleaned up {removed} orphan database entries")
        return removed
