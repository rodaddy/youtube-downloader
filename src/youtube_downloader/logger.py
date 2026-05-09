"""Logging configuration for YouTube Downloader.

This module provides centralized logging setup using loguru with both
console and file handlers.
"""

import sys
from pathlib import Path

from loguru import logger


def setup_logger(debug: bool = False, log_dir: Path | None = None) -> None:
    """Configure logging with console and file handlers.

    Args:
        debug: If True, set console logging to DEBUG level, otherwise INFO
        log_dir: Directory for log files. Defaults to ./logs relative to cwd
    """
    # Remove default loguru handler
    logger.remove()

    # Add console handler with appropriate level
    console_level = "DEBUG" if debug else "INFO"
    logger.add(
        sys.stderr,
        level=console_level,
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
            "<level>{message}</level>"
        ),
    )

    # Create log directory if provided
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "app.log"
    else:
        # Fallback to current directory (not recommended)
        log_file = Path("app.log")

    # Add file handler with rotation
    logger.add(
        log_file,
        level="DEBUG",
        rotation="10 MB",
        retention="7 days",
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    )
