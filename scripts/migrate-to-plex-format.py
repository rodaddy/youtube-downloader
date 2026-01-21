#!/usr/bin/env python3
"""Migrate existing YouTube downloads to Plex YouTube Agent format.

This script renames existing downloaded files from:
    {uploader}/{date}_{title}.{ext}

To the Plex YouTube Agent compatible format:
    {uploader} [{channel_id}]/{title} [{video_id}].{ext}
"""

import json
import re
import shutil
from pathlib import Path


def sanitize_filename(name: str) -> str:
    """Remove or replace invalid filename characters."""
    # Replace characters that are problematic in filenames
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '')
    # Collapse multiple spaces
    name = re.sub(r'\s+', ' ', name)
    return name.strip()


def migrate_downloads(download_dir: Path, dry_run: bool = True) -> None:
    """Migrate all downloads to Plex-compatible naming.

    Args:
        download_dir: Root download directory
        dry_run: If True, only print what would be done without making changes
    """
    if not download_dir.exists():
        print(f"ERROR: Download directory not found: {download_dir}")
        return

    print(f"{'DRY RUN - ' if dry_run else ''}Migrating downloads in: {download_dir}")
    print("=" * 60)

    # Track channel renames to avoid duplicate work
    channel_renames: dict[Path, Path] = {}

    # First pass: collect all info.json files and their metadata
    migrations = []

    for info_file in download_dir.rglob("*.info.json"):
        # Skip channel/playlist level info files
        if "_-_Videos.info.json" in info_file.name:
            continue
        if "_-_Uploads.info.json" in info_file.name:
            continue

        try:
            with open(info_file) as f:
                info = json.load(f)
        except Exception as e:
            print(f"WARNING: Could not read {info_file}: {e}")
            continue

        video_id = info.get("id")
        title = info.get("title")
        uploader = info.get("uploader")
        channel_id = info.get("channel_id")

        if not all([video_id, title, uploader, channel_id]):
            print(f"WARNING: Missing metadata in {info_file}")
            continue

        # Skip if already in correct format (has [video_id] in name)
        if f"[{video_id}]" in info_file.stem:
            print(f"SKIP (already migrated): {info_file.name}")
            continue

        # Build new paths
        old_channel_dir = info_file.parent
        new_channel_name = sanitize_filename(f"{uploader} [{channel_id}]")
        new_channel_dir = download_dir / new_channel_name

        # Store channel rename mapping
        if old_channel_dir not in channel_renames:
            channel_renames[old_channel_dir] = new_channel_dir

        # Find associated files (video, thumbnail, etc.)
        base_name = info_file.stem.replace(".info", "")
        associated_files = list(old_channel_dir.glob(f"{base_name}*"))

        # New base name for files
        new_base = sanitize_filename(f"{title} [{video_id}]")

        for old_file in associated_files:
            # Determine new filename
            if old_file.suffix == ".json" and ".info" in old_file.stem:
                new_name = f"{new_base}.info.json"
            elif "-fanart" in old_file.stem or "-poster" in old_file.stem:
                # Keep fanart/poster suffix
                suffix_match = re.search(r'(-fanart|-poster)', old_file.stem)
                suffix = suffix_match.group(1) if suffix_match else ""
                new_name = f"{new_base}{suffix}{old_file.suffix}"
            else:
                new_name = f"{new_base}{old_file.suffix}"

            migrations.append({
                "old_path": old_file,
                "new_dir": new_channel_dir,
                "new_name": new_name,
            })

    # Print and execute migrations
    if not migrations:
        print("No files need migration.")
        return

    print(f"\nFound {len(migrations)} files to migrate\n")

    # Create new channel directories first
    for old_dir, new_dir in channel_renames.items():
        if old_dir != new_dir:
            print(f"RENAME DIR: {old_dir.name}")
            print(f"        TO: {new_dir.name}")
            if not dry_run:
                new_dir.mkdir(parents=True, exist_ok=True)

    print()

    # Move files
    for m in migrations:
        old_path = m["old_path"]
        new_path = m["new_dir"] / m["new_name"]

        # Truncate display for readability
        old_display = old_path.name[:50] + "..." if len(old_path.name) > 50 else old_path.name
        new_display = new_path.name[:50] + "..." if len(new_path.name) > 50 else new_path.name

        print(f"MOVE: {old_display}")
        print(f"  TO: {new_display}")

        if not dry_run:
            try:
                new_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old_path), str(new_path))
            except Exception as e:
                print(f"  ERROR: {e}")

    # Clean up empty old directories
    if not dry_run:
        for old_dir in channel_renames.keys():
            if old_dir.exists() and not any(old_dir.iterdir()):
                print(f"\nRemoving empty directory: {old_dir.name}")
                old_dir.rmdir()

    print("\n" + "=" * 60)
    if dry_run:
        print("DRY RUN COMPLETE - No changes made")
        print("Run with --execute to apply changes")
    else:
        print("MIGRATION COMPLETE")


if __name__ == "__main__":
    import sys

    # Default download directory
    default_dir = Path("/Volumes/media_files/media_services/youtube/YoutubeDownloads")

    # Check for --execute flag
    dry_run = "--execute" not in sys.argv

    # Check for custom path
    custom_path = None
    for arg in sys.argv[1:]:
        if arg != "--execute" and not arg.startswith("-"):
            custom_path = Path(arg)
            break

    download_dir = custom_path or default_dir

    migrate_downloads(download_dir, dry_run=dry_run)
