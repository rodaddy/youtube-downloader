"""Command-line interface for YouTube Downloader.

This module provides a Click-based CLI for running the server and managing downloads.
"""

import os
import signal
import sys
from pathlib import Path

import click

from .app import create_app
from .config import Settings
from .database import Database
from .downloader import DownloadManager
from .logger import setup_logger


def _pid_file_path() -> Path:
    """Get the path to the PID file."""
    settings = Settings.load_with_overrides()
    data_dir = settings.project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "youtube-downloader.pid"


def _write_pid() -> None:
    """Write the current process PID to the PID file."""
    pid_path = _pid_file_path()
    pid_path.write_text(str(os.getpid()))


def _cleanup_old_process() -> None:
    """Stop any previously running instance using the PID file.

    Only kills the specific process recorded in the PID file, avoiding
    the dangerous `pkill -9 -f` pattern that can nuke unrelated processes.
    """
    pid_path = _pid_file_path()

    if not pid_path.exists():
        return

    try:
        old_pid = int(pid_path.read_text().strip())
    except (ValueError, OSError):
        # Corrupt PID file -- just remove it
        pid_path.unlink(missing_ok=True)
        return

    # Check if the process is still running
    try:
        os.kill(old_pid, 0)  # Signal 0 = existence check
    except ProcessLookupError:
        # Process already gone -- clean up stale PID file
        pid_path.unlink(missing_ok=True)
        return
    except PermissionError:
        # Process exists but we can't signal it
        click.echo(f"⚠️  Process {old_pid} exists but can't be signaled (permission denied)")
        pid_path.unlink(missing_ok=True)
        return

    # Process is alive -- send SIGTERM (graceful) first, then SIGKILL if needed
    click.echo(f"🔄 Stopping previous instance (PID {old_pid})...")
    try:
        os.kill(old_pid, signal.SIGTERM)
        # Give it a moment to shut down
        import time

        for _ in range(10):
            time.sleep(0.5)
            try:
                os.kill(old_pid, 0)
            except ProcessLookupError:
                click.echo("✅ Previous instance stopped gracefully")
                break
        else:
            # Still alive after 5 seconds -- force kill
            click.echo(f"⚠️  Force-killing previous instance (PID {old_pid})...")
            os.kill(old_pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # Already gone

    pid_path.unlink(missing_ok=True)


@click.group()
@click.version_option(version="1.0.0", prog_name="youtube-downloader")
def cli() -> None:
    """YouTube Downloader - Automated channel downloader with Plex integration."""
    pass


@cli.command()
@click.option(
    "--host",
    default=None,
    help="Server host address (overrides .env)",
)
@click.option(
    "--port",
    type=int,
    default=None,
    help="Server port (overrides .env)",
)
@click.option(
    "--debug/--no-debug",
    default=None,
    help="Enable debug mode (overrides .env)",
)
def serve(host: str | None, port: int | None, debug: bool | None) -> None:
    """Start the web server (default command)."""
    # Clean up any existing instance via PID file
    _cleanup_old_process()

    # Write our PID so future invocations can find us
    _write_pid()

    settings = Settings.load_with_overrides()

    # Apply CLI overrides
    if host is not None:
        object.__setattr__(settings, "host", host)
    if port is not None:
        object.__setattr__(settings, "port", port)
    if debug is not None:
        object.__setattr__(settings, "debug", debug)

    # Create and run Flask app
    app = create_app(settings)
    try:
        app.run(host=settings.host, port=settings.port, debug=settings.debug)
    finally:
        # Clean up PID file on exit
        pid_path = _pid_file_path()
        pid_path.unlink(missing_ok=True)


@cli.command()
@click.argument("channel_url", required=False)
@click.option(
    "--all",
    "download_all",
    is_flag=True,
    help="Download from all channels in channels.txt",
)
def download(channel_url: str | None, download_all: bool) -> None:
    """Download videos from a YouTube channel.

    CHANNEL_URL: YouTube channel URL to download from
    """
    if not channel_url and not download_all:
        click.echo("Error: Provide a CHANNEL_URL or use --all", err=True)
        sys.exit(1)

    settings = Settings.load_with_overrides()
    setup_logger(debug=settings.debug, log_dir=settings.log_dir)

    # Initialize database
    db_path = settings.project_root / "data" / "videos.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(db_path)

    # Create download manager
    manager = DownloadManager(settings, database=database)

    if download_all:
        click.echo("📥 Downloading from all channels...")
        download_ids = manager.download_all_channels()
        click.echo(f"✅ Started {len(download_ids)} downloads")
    else:
        click.echo(f"📥 Downloading from: {channel_url}")
        download_id = manager.start_download(channel_url)  # type: ignore
        click.echo(f"✅ Download started (ID: {download_id})")

    click.echo("\n💡 Tip: Use 'youtube-downloader serve' to monitor progress in web UI")


@cli.command()
def channels() -> None:
    """List configured channels from channels.txt."""
    settings = Settings.load_with_overrides()
    manager = DownloadManager(settings)

    channels_list = manager.load_channels()

    if not channels_list:
        click.echo("No channels configured in channels.txt", err=True)
        sys.exit(1)

    click.echo(f"📺 Configured channels ({len(channels_list)}):\n")
    for i, channel in enumerate(channels_list, 1):
        click.echo(f"  {i}. {channel}")


@cli.command()
def scan() -> None:
    """Scan download directory and import existing videos into database."""
    settings = Settings.load_with_overrides()
    setup_logger(debug=settings.debug, log_dir=settings.log_dir)

    # Initialize database
    db_path = settings.project_root / "data" / "videos.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(db_path)

    # Create download manager
    manager = DownloadManager(settings, database=database)

    click.echo("🔍 Scanning for existing videos...")
    added = manager.scan_existing_videos()
    click.echo(f"✅ Added {added} videos to database")


@cli.command()
@click.option(
    "--download-dir",
    type=click.Path(exists=False, path_type=Path),
    help="Set download directory",
)
@click.option(
    "--videos-per-channel",
    type=int,
    help="Set number of videos to keep per channel",
)
def config(download_dir: Path | None, videos_per_channel: int | None) -> None:
    """View or update runtime configuration."""
    settings = Settings.load_with_overrides()

    if download_dir or videos_per_channel:
        # Update configuration
        settings.update_runtime_config(
            download_dir=download_dir,
            videos_per_channel=videos_per_channel,
        )
        click.echo("✅ Configuration updated:")
    else:
        click.echo("📋 Current configuration:")

    click.echo(f"  Download directory: {settings.download_dir}")
    click.echo(f"  Videos per channel: {settings.videos_per_channel}")
    click.echo(f"  Plex integration: {'enabled' if settings.plex_enabled else 'disabled'}")
    click.echo(f"  Web UI auth: {'enabled' if settings.auth_enabled else 'disabled'}")

    if not download_dir and not videos_per_channel:
        click.echo("\n💡 Tip: Use --download-dir or --videos-per-channel to update")


def main() -> None:
    """Main entry point for CLI."""
    # If no command provided, default to 'serve'
    if len(sys.argv) == 1:
        sys.argv.append("serve")

    cli()


if __name__ == "__main__":
    main()
