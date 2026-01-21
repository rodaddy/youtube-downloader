#!/usr/bin/env python3
"""Fix video file modification times based on upload dates from .info.json files.

This script reads the upload_date from each .info.json file and sets the
corresponding video file's modification time to match. This helps Plex
sort videos correctly by their actual upload date.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path


def parse_upload_date(upload_date: str) -> float:
    """Convert upload_date string (YYYYMMDD) to Unix timestamp.

    Args:
        upload_date: Date string in YYYYMMDD format (e.g., "20250115")

    Returns:
        Unix timestamp as float
    """
    if not upload_date or len(upload_date) != 8:
        raise ValueError(f"Invalid upload_date format: {upload_date}")

    dt = datetime.strptime(upload_date, "%Y%m%d")
    return dt.timestamp()


def find_video_file(info_file: Path) -> Path | None:
    """Find the video file corresponding to an .info.json file.

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


def fix_timestamps(download_dir: Path, dry_run: bool = False) -> dict[str, int]:
    """Fix video file timestamps based on upload dates.

    Args:
        download_dir: Path to the download directory
        dry_run: If True, show what would be changed without making changes

    Returns:
        Dict with counts: {"updated": N, "skipped": N, "errors": N}
    """
    counts = {"updated": 0, "skipped": 0, "errors": 0}

    print(f"Scanning for videos in: {download_dir}")
    if dry_run:
        print("🔍 DRY RUN MODE - No changes will be made\n")

    # Find all .info.json files recursively
    info_files = list(download_dir.rglob("*.info.json"))
    print(f"Found {len(info_files)} .info.json files\n")

    for info_file in info_files:
        try:
            # Read the .info.json file
            with open(info_file) as f:
                info = json.load(f)

            upload_date = info.get("upload_date", "")
            if not upload_date:
                print(f"⚠️  No upload_date in {info_file.name}")
                counts["skipped"] += 1
                continue

            # Find the corresponding video file
            video_file = find_video_file(info_file)
            if not video_file:
                print(f"⚠️  Video file not found for {info_file.name}")
                counts["skipped"] += 1
                continue

            # Parse upload date and convert to timestamp
            timestamp = parse_upload_date(upload_date)

            # Get current modification time
            current_mtime = video_file.stat().st_mtime

            # Check if already correct (within 1 day tolerance)
            if abs(current_mtime - timestamp) < 86400:  # 86400 seconds = 1 day
                counts["skipped"] += 1
                continue

            # Show what will be changed
            video_name = video_file.name
            current_date = datetime.fromtimestamp(current_mtime).strftime("%Y-%m-%d")
            new_date = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")

            print(f"📅 {video_name[:60]}")
            print(f"   Current: {current_date} → New: {new_date}")

            if not dry_run:
                # Set both access time and modification time
                os.utime(video_file, (timestamp, timestamp))
                counts["updated"] += 1
                print("   ✅ Updated")
            else:
                counts["updated"] += 1
                print("   Would update")

            print()

        except Exception as e:
            print(f"❌ Error processing {info_file.name}: {e}\n")
            counts["errors"] += 1

    return counts


def main():
    """Main entry point."""
    # Default download directory
    default_dir = Path("/Volumes/media_files/media_services/youtube/YoutubeDownloads")

    # Parse arguments
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv

    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        download_dir = Path(sys.argv[1])
    else:
        download_dir = default_dir

    if not download_dir.exists():
        print(f"❌ Download directory not found: {download_dir}")
        sys.exit(1)

    print("=" * 70)
    print("Fix Video Timestamps")
    print("=" * 70)
    print()

    # Run the fix
    counts = fix_timestamps(download_dir, dry_run=dry_run)

    # Summary
    print("=" * 70)
    print("Summary:")
    print(f"  ✅ Updated: {counts['updated']}")
    print(f"  ⏭️  Skipped: {counts['skipped']}")
    print(f"  ❌ Errors:  {counts['errors']}")
    print("=" * 70)

    if dry_run:
        print("\n💡 Run without --dry-run to apply changes")
    else:
        print("\n✅ Timestamps updated! Plex should re-sort videos on next scan.")


if __name__ == "__main__":
    main()