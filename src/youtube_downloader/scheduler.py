"""Background scheduler for automatic downloads.

This module provides scheduled download jobs using APScheduler.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

if TYPE_CHECKING:
    from .config import Settings


class DownloadScheduler:
    """Manages scheduled download jobs."""

    def __init__(self, settings: "Settings") -> None:
        """Initialize the scheduler.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self.scheduler = BackgroundScheduler()
        self._download_callback: Optional[Callable[[], None]] = None
        self._cleanup_callback: Optional[Callable[[], None]] = None
        self._is_running = False
        self._last_run: Optional[datetime] = None
        self._next_run: Optional[datetime] = None
        self._last_cleanup_run: Optional[datetime] = None
        self._next_cleanup_run: Optional[datetime] = None

    def set_download_callback(self, callback: Callable[[], None]) -> None:
        """Set the callback function for scheduled downloads.

        Args:
            callback: Function to call when download is triggered
        """
        self._download_callback = callback

    def set_cleanup_callback(self, callback: Callable[[], None]) -> None:
        """Set the callback function for scheduled cleanup/structure enforcement.

        Args:
            callback: Function to call for cleanup (e.g., _enforce_directory_structure)
        """
        self._cleanup_callback = callback

    def start(self, interval_hours: float = 2.0, cleanup_interval_hours: float = 1.0) -> None:
        """Start the scheduler with the specified interval.

        Args:
            interval_hours: Hours between download runs
            cleanup_interval_hours: Hours between cleanup/structure enforcement runs
        """
        if self._is_running:
            logger.warning("Scheduler already running")
            return

        if not self._download_callback:
            logger.error("No download callback set - cannot start scheduler")
            return

        # Add the download job
        self.scheduler.add_job(
            self._run_download,
            trigger=IntervalTrigger(hours=interval_hours),
            id="download_job",
            name="Scheduled Download",
            replace_existing=True,
        )

        # Add the cleanup job (runs more frequently)
        if self._cleanup_callback:
            self.scheduler.add_job(
                self._run_cleanup,
                trigger=IntervalTrigger(hours=cleanup_interval_hours),
                id="cleanup_job",
                name="Directory Cleanup",
                replace_existing=True,
            )

        self.scheduler.start()
        self._is_running = True

        # Get next run times
        job = self.scheduler.get_job("download_job")
        if job and job.next_run_time:
            self._next_run = job.next_run_time

        cleanup_job = self.scheduler.get_job("cleanup_job")
        if cleanup_job and cleanup_job.next_run_time:
            self._next_cleanup_run = cleanup_job.next_run_time

        logger.info(
            f"Scheduler started - downloads every {interval_hours} hours. "
            f"Next run: {self._next_run}"
        )
        if self._cleanup_callback:
            logger.info(
                f"Cleanup job - runs every {cleanup_interval_hours} hours. "
                f"Next run: {self._next_cleanup_run}"
            )

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._is_running:
            self.scheduler.shutdown(wait=False)
            self._is_running = False
            logger.info("Scheduler stopped")

    def run_now(self) -> None:
        """Trigger an immediate download run."""
        if self._download_callback:
            logger.info("Manual download triggered")
            self._run_download()
        else:
            logger.error("No download callback set")

    def _run_download(self) -> None:
        """Execute the download callback and update run times."""
        self._last_run = datetime.now()
        logger.info(f"Starting scheduled download at {self._last_run}")

        try:
            if self._download_callback:
                self._download_callback()
        except Exception as e:
            logger.exception(f"Scheduled download failed: {e}")

        # Update next run time
        job = self.scheduler.get_job("download_job")
        if job and job.next_run_time:
            self._next_run = job.next_run_time
            logger.info(f"Next scheduled download: {self._next_run}")

    def _run_cleanup(self) -> None:
        """Execute the cleanup callback and update run times."""
        self._last_cleanup_run = datetime.now()
        logger.info(f"Starting scheduled cleanup at {self._last_cleanup_run}")

        try:
            if self._cleanup_callback:
                self._cleanup_callback()
        except Exception as e:
            logger.exception(f"Scheduled cleanup failed: {e}")

        # Update next run time
        job = self.scheduler.get_job("cleanup_job")
        if job and job.next_run_time:
            self._next_cleanup_run = job.next_run_time
            logger.info(f"Next scheduled cleanup: {self._next_cleanup_run}")

    def get_status(self) -> dict:
        """Get scheduler status.

        Returns:
            Dictionary with scheduler status info
        """
        return {
            "is_running": self._is_running,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "next_run": self._next_run.isoformat() if self._next_run else None,
            "interval_hours": self._get_interval_hours(),
        }

    def _get_interval_hours(self) -> Optional[float]:
        """Get the current interval in hours."""
        job = self.scheduler.get_job("download_job")
        if job and hasattr(job.trigger, "interval"):
            return job.trigger.interval.total_seconds() / 3600
        return None

    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._is_running
