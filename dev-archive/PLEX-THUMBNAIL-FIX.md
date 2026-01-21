# Plex Thumbnail Fix - Resolution

## Problem

Thumbnails weren't displaying in Plex library grid view for YouTube videos, despite being downloaded correctly.

## Root Cause

The YouTubeDownload library was using agent `com.plexapp.agents.none`, which doesn't support:
- Local Media Assets scanning (couldn't auto-detect `-poster.jpg` files)
- Automatic poster selection

## Solution

Upload posters directly via Plex API after each download:

1. **Rename thumbnails** from `.jpg` to `-poster.jpg` format (Plex naming convention)
2. **Upload via API** using python-plexapi library's `uploadPoster()` method
3. **Lock posters** using `lockPoster()` to prevent Plex from overwriting them

## Implementation

### Code Changes

**src/youtube_downloader/plex.py**:
- Updated `upload_poster()` to lock posters after upload
- Updated `upload_thumbnails_for_directory()` to look for `-poster.jpg` files

**src/youtube_downloader/downloader.py**:
- Re-added `PlexIntegration` import
- Initialize Plex integration in `__init__()` if configured
- Call `plex.sync_thumbnails()` after successful downloads

**.env.example**:
- Added Plex configuration variables:
  - `PLEX_URL`
  - `PLEX_TOKEN`
  - `PLEX_LIBRARY_ID`

### Configuration

Add to `.env` file:

```bash
PLEX_URL=http://your-plex-server:32400
PLEX_TOKEN=your_plex_token_here
PLEX_LIBRARY_ID=your_library_id
```

## How It Works

1. yt-dlp downloads video with `--write-thumbnail` and `--convert-thumbnails jpg`
2. `_rename_thumbnails_for_plex()` renames `.jpg` → `-poster.jpg`
3. If Plex integration is enabled:
   - Triggers library refresh
   - Waits for scan to complete
   - Finds all videos in library
   - Matches video files to `-poster.jpg` files
   - Uploads each poster via API
   - Locks each poster to prevent overwrites

## Permissions Fix

The Plex metadata directory (`/var/lib/plexmediaserver/Library/Application Support/Plex Media Server/Metadata`) is a symlink to `/mnt/media/Plex/metadata`, which is a CIFS mount.

Fixed ownership on Proxmox host:

```bash
# /etc/fstab on proxmox02 (10.71.1.8)
//10.71.1.11/media_files /mnt/PlexMedia cifs credentials=/root/.smbcredentials,iocharset=utf8,uid=999,gid=999,file_mode=0664,dir_mode=0775,_netdev,x-systemd.automount 0 0
```

Added `uid=999,gid=999` to ensure Plex user (UID 999) can write to the mount.

## Testing

Uploaded all 8 existing videos successfully:

```bash
cd youtube-downloader
uv run python upload_all_posters.py

# Result:
✅ Uploaded: 8
❌ Errors: 0
⚠️  Skipped: 0
```

All posters now display correctly in Plex library grid view.

## Future Downloads

With Plex integration enabled in `.env`, all future downloads will:
1. Download video + thumbnail
2. Rename thumbnail to `-poster.jpg`
3. Upload poster to Plex via API
4. Lock poster to prevent overwrites

No manual intervention required.
