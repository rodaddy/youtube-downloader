# YouTube Downloader - Simple Web UI

## Problem Statement

TubeSync is overcomplicated with broken codec matching, format requirements, and indexing overhead. We just need a simple way to download YouTube videos to a folder that Plex can index.

## Solution

Build a minimal web UI that:
- Takes a YouTube URL
- Downloads the video using yt-dlp
- Saves to a configurable folder
- Shows download progress
- Lists downloaded files

## Requirements

### Core Features
1. **Single URL Download**
   - Paste YouTube URL (video, channel, playlist)
   - Click "Download"
   - Shows real-time progress
   - Notifies when complete

2. **Download Management**
   - List all downloaded videos
   - Show file size, date downloaded
   - Delete files from UI (optional)

3. **Configuration**
   - Download directory (configurable)
   - Video quality preference (720p, 1080p, best)
   - Format preference (mp4, mkv, webm)

### Technical Stack
- **Backend:** Flask (Python 3)
- **Frontend:** Plain HTML + JavaScript (no frameworks)
- **Download Engine:** yt-dlp
- **Storage:** Local filesystem

### Architecture

```
youtube-downloader/
├── app.py              # Flask backend
├── templates/
│   └── index.html      # Web UI
├── requirements.txt    # Python dependencies
└── config.py           # Configuration (download dir, quality, etc.)
```

### API Endpoints

**POST /download**
- Input: `{"url": "https://youtube.com/watch?v=..."}`
- Returns: `{"download_id": "abc123", "status": "queued"}`

**GET /status/<download_id>**
- Returns: `{"status": "downloading|complete|error", "progress": 45, "message": "..."}`

**GET /files**
- Returns: `[{"name": "video.mp4", "size": 30000000, "date": "2026-01-20"}]`

**GET /**
- Serves HTML UI

### Download Logic

1. Receive URL from user
2. Validate YouTube URL
3. Generate unique download ID
4. Spawn background thread to run yt-dlp
5. Update status as download progresses
6. Save to configured directory
7. Notify completion

### Configuration Options

```python
DOWNLOAD_DIR = "/path/to/youtube_stuff"  # Configurable
VIDEO_QUALITY = "best[height<=1080]"     # 720p, 1080p, best
OUTPUT_FORMAT = "mp4"                     # mp4, mkv, webm
```

### Deployment Strategy

**Phase 1 - Local Testing (Tonight)**
- Run on local machine (Mac)
- Download to ~/Downloads/youtube_stuff
- Test basic functionality

**Phase 2 - LXC Deployment (Later)**
- Deploy to media-automation LXC (10.71.20.30)
- Download to /mnt/media/TV_Shows/youtube_stuff/
- Add to systemd for auto-start
- Configure nginx reverse proxy (optional)

**Phase 3 - Plex Integration (Optional)**
- Create Plex library pointing to youtube_stuff/
- Videos automatically appear in Plex
- Proper metadata (optional - could use NFO files)

## Success Criteria

- Paste YouTube URL → Video downloads → File appears in folder
- Download completes in under 2 minutes for typical video
- UI shows progress updates
- Works with videos, playlists, channels
- No codec errors, format mismatches, or TubeSync bullshit

## Out of Scope (For Now)

- Automatic channel monitoring (can add later)
- Scheduled downloads
- User authentication
- Multiple download directories
- Advanced metadata editing
- Subtitle downloads (yt-dlp can do this, just not exposing it yet)

## Why This Beats TubeSync

| Feature | TubeSync | Our App |
|---------|----------|---------|
| Codec matching | Broken | Don't care, use best available |
| Format requirements | Strict, breaks downloads | Flexible, just works |
| Indexing overhead | Indexes 1000s of videos | Download what you want |
| Setup complexity | Docker, database, web UI config | Run Flask, paste URL |
| Works? | No | Yes |

## Implementation Time Estimate

**Phase 1 (Tonight):** 30-60 minutes
- Basic Flask app
- HTML form
- yt-dlp integration
- Download status tracking

**Total:** ~1 hour to working prototype
