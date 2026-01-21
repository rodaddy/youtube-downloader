# Plex Thumbnail Investigation - Session Notes

**Date:** 2026-01-21
**Status:** ✅ RESOLVED - See [PLEX-THUMBNAIL-FIX.md](PLEX-THUMBNAIL-FIX.md) for solution

## Goal

Get Plex to display thumbnails for YouTube videos downloaded via yt-dlp.

## Resolution Summary

The library was using agent `com.plexapp.agents.none` which doesn't support Local Media Assets. Solution: Upload posters directly via Plex API after each download and lock them to prevent overwrites. See [PLEX-THUMBNAIL-FIX.md](PLEX-THUMBNAIL-FIX.md) for full details.

---

## Environment

- **Plex Server:** `your-plex-server:32400`
- **Download Location:** `/path/to/youtube/downloads`
- **Mount on Plex:** `/mnt/media/youtube/downloads`
- **Plex Token:** `your_plex_token_here`

---

## What We Tried

### 1. YouTube-Agent.bundle + Absolute Series Scanner

**Approach:** Install TubeSync's recommended Plex plugins
- Absolute Series Scanner: Custom scanner for YouTube folder structure
- YouTube-Agent.bundle: Fetches metadata from YouTube API

**Result:** FAILED

**Why:**
- Both are Python 2 code
- Absolute Series Scanner has `ur'...'` syntax (Python 2 only)
- YouTube-Agent crashes with: `AttributeError: type object 'object' has no attribute '__getattr__'`
- Plex's newer Framework uses Python 3, these plugins are incompatible

**Files installed (can be removed):**
- `/var/lib/plexmediaserver/Library/Application Support/Plex Media Server/Scanners/Series/Absolute Series Scanner.py`
- `/var/lib/plexmediaserver/Library/Application Support/Plex Media Server/Plug-ins/YouTube-Agent.bundle`

---

### 2. Plex Series Agent + TV Shows Library

**Approach:** Use Plex's built-in TV Series agent with standard scanner

**Result:** FAILED - 0 items found

**Why:**
- Plex Series Scanner expects: `Show Name/Season 01/S01E01 - Title.mp4`
- Our structure is: `{channel} [{channel_id}]/{title} [{video_id}].mp4`
- Scanner doesn't recognize YouTube folder structure as TV shows

**Library created:** Section 13 (can be deleted)

---

### 3. Movies Library + Embedded Thumbnails

**Approach:** Use Movies library type, rely on yt-dlp's `--embed-thumbnail`

**Result:** PARTIAL - Videos recognized, thumbnails NOT displayed

**Details:**
- Plex Movie Scanner recognizes all videos ✓
- Titles extracted correctly ✓
- Metadata embedded in MP4 (verified with ffprobe) ✓
- Plex metadata claims `hasThumbnail="1"` ✓
- **BUT actual thumbnail URLs return 404**

**The Bug:**
```
Plex looks for: /Media/localhost/a/310e3be1f0a7052f31362249886c07865a5261b.bundle/Contents/Thumbnails/thumb1.jpg
File does not exist → 404 Not Found
```

Plex claims thumbnails exist but never actually extracted them from the embedded mjpeg stream.

**Library:** Section 11 "YouTubeDownload" - this is the working library (minus thumbnails)

---

### 4. Local Media Assets with External Thumbnails

**Approach:**
- yt-dlp saves external `.jpg` thumbnail files
- Renamed to `-thumb.jpg` format (Plex's expected naming)
- Local Media Assets agent should pick them up

**Result:** FAILED - Plex ignored external thumbnails

**Files exist:**
```
Italian Chinese Food vs. Chinese Italian Food [1ineAYDxg9E].mp4
Italian Chinese Food vs. Chinese Italian Food [1ineAYDxg9E]-thumb.jpg  ← ignored
Italian Chinese Food vs. Chinese Italian Food [1ineAYDxg9E].info.json
```

---

### 5. Plex API Upload (Code Written, Not Tested)

**Approach:**
- After download, query Plex API for video's ratingKey
- POST thumbnail directly to `/library/metadata/{ratingKey}/posters`

**Status:** Code written in `src/youtube_downloader/plex.py`, not tested

**Files modified:**
- `src/youtube_downloader/plex.py` - NEW, PlexIntegration class
- `src/youtube_downloader/config.py` - Added plex_url, plex_token, plex_library_id
- `src/youtube_downloader/downloader.py` - Calls plex.sync_thumbnails() after download
- `.env` - Added PLEX_URL, PLEX_TOKEN, PLEX_LIBRARY_ID

---

## Current State

### Working
- yt-dlp downloads videos correctly
- Thumbnails embedded in MP4 files (verified: `ffprobe` shows `codec_name=mjpeg`)
- External thumbnail files saved as `-thumb.jpg`
- Plex Movies library (section 11) recognizes all videos
- Video metadata (title, description) displays correctly

### Not Working
- Plex does not display thumbnails
- Embedded thumbnails not extracted by Plex
- External thumbnails ignored by Local Media Assets

---

## yt-dlp Command Used

```python
cmd = [
    "yt-dlp",
    "--format", "bestvideo[height<=1080][vcodec^=avc]+bestaudio[acodec=aac]/best[height<=1080]",
    "--playlist-end", "2",
    "--download-archive", str(archive_file),
    "--output", "{download_dir}/%(uploader)s [%(channel_id)s]/%(title)s [%(id)s].%(ext)s",
    "--embed-metadata",
    "--embed-thumbnail",      # Embeds thumbnail in MP4
    "--write-info-json",
    "--write-thumbnail",      # Also saves external .jpg
    "--convert-thumbnails", "jpg",
    "--no-mtime",
    "--progress",
    f"{channel_url}/videos",
]
```

---

## Plex Libraries

| Section | Name | Type | Agent | Status |
|---------|------|------|-------|--------|
| 11 | YouTubeDownload | Movies | com.plexapp.agents.none | Videos work, no thumbnails |
| 12 | YouTube | TV Shows | com.plexapp.agents.youtube | DELETED (agent was broken) |
| 13 | YouTube | TV Shows | tv.plex.agents.series | 0 items (scanner doesn't recognize structure) |

---

## Untested Options

1. **API Upload** - Code exists in `plex.py`, needs testing
2. **Delete Plex cache and rescan** - Force thumbnail regeneration
3. **Different container format** - Maybe MKV handles thumbnails differently?
4. **Jellyfin** - Has working YouTube metadata plugin (user rejected, paid for Plex)

---

## Key Files

```
youtube-downloader/
├── src/youtube_downloader/
│   ├── plex.py          # NEW - Plex API integration (untested)
│   ├── config.py        # Updated - Added Plex settings
│   ├── downloader.py    # Updated - Calls Plex sync after download
│   ├── app.py
│   ├── database.py
│   └── ...
├── .env                  # Has PLEX_URL, PLEX_TOKEN, PLEX_LIBRARY_ID
└── data/
    └── videos.db         # SQLite tracking database
```

---

## Commands for Investigation

```bash
# SSH to Plex server
ssh root@10.71.1.35

# Check if thumbnails embedded in video
ffprobe "video.mp4" 2>&1 | grep mjpeg

# List Plex libraries
curl -s "http://127.0.0.1:32400/library/sections?X-Plex-Token=TOKEN"

# Check library contents
curl -s "http://127.0.0.1:32400/library/sections/11/all?X-Plex-Token=TOKEN"

# Try to fetch a thumbnail (returns 404)
curl -s "http://127.0.0.1:32400/library/metadata/84396/thumb/1768969149?X-Plex-Token=TOKEN"

# Check Plex logs
tail -f "/var/lib/plexmediaserver/Library/Application Support/Plex Media Server/Logs/Plex Media Server.log"
```

---

## Next Session Suggestions

1. **Test the API upload** - Run `plex.sync_thumbnails()` and see if it works
2. **Check Plex thumbnail generation settings** - Maybe disabled?
3. **Try deleting library metadata and rescanning**
4. **Research why Plex fails to extract embedded mjpeg thumbnails**
5. **Consider poster upload via Plex web UI** - Does manual upload work?
