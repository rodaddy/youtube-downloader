"""Background scheduler for automatic downloads.

This module provides scheduled download jobs using APScheduler.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
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

    def start(self) -> None:
        """Start the scheduler to run on the hour, every hour.

        Runs downloads then cleanup sequentially in a single job.
        """
        if self._is_running:
            logger.warning("Scheduler already running")
            return

        if not self._download_callback:
            logger.error("No download callback set - cannot start scheduler")
            return

        # Single job: downloads + cleanup, runs on the hour
        self.scheduler.add_job(
            self._run_job,
            trigger=CronTrigger(minute=0),  # Every hour at :00
            id="hourly_job",
            name="Hourly Download & Cleanup",
            replace_existing=True,
        )

        self.scheduler.start()
        self._is_running = True

        # Get next run time
        job = self.scheduler.get_job("hourly_job")
        if job and job.next_run_time:
            self._next_run = job.next_run_time

        logger.info(f"Scheduler started - runs on the hour (:00). Next run: {self._next_run}")

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._is_running:
            self.scheduler.shutdown(wait=False)
            self._is_running = False
            logger.info("Scheduler stopped")

    def run_now(self) -> None:
        """Trigger an immediate download + cleanup run."""
        if self._download_callback:
            logger.info("Manual run triggered")
            self._run_job()
        else:
            logger.error("No download callback set")

    def _run_job(self) -> None:
        """Execute downloads then cleanup sequentially."""
        self._last_run = datetime.now()
        logger.info(f"Starting hourly job at {self._last_run}")

        # Step 1: Downloads
        try:
            if self._download_callback:
                logger.info("Running downloads...")
                self._download_callback()
        except Exception as e:
            logger.exception(f"Download phase failed: {e}")

        # Step 2: Cleanup (runs even if downloads failed)
        try:
            if self._cleanup_callback:
                logger.info("Running cleanup...")
                self._cleanup_callback()
        except Exception as e:
            logger.exception(f"Cleanup phase failed: {e}")

        # Update next run time
        job = self.scheduler.get_job("hourly_job")
        if job and job.next_run_time:
            self._next_run = job.next_run_time
            logger.info(f"Hourly job complete. Next run: {self._next_run}")

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

    def _get_interval_hours(self) -> float:
        """Get the current interval in hours (always 1.0 for hourly schedule)."""
        return 1.0

    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._is_running
