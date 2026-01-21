# YouTube Downloader - Development Specifications

## Feature Implementation Status

### ✅ Completed Features

#### 1. Core Download System
- Flask web application with REST API
- yt-dlp integration for video downloads
- SQLite database for video tracking
- Scheduler (2-hour automatic downloads)
- Per-video subfolder structure for easier cleanup
- Plex thumbnail integration

#### 2. Video Management
- Direct download from arbitrary channels
- Add/remove channels via UI
- Nuclear cleanup option (delete everything)
- Database cleanup (remove orphaned entries)
- Sync old files to new structure

#### 3. Pin/Keeper Feature (Backend Only)
**Status:** Backend ✅ | Frontend ⏳

**Completed:**
- Database schema with `keep_forever` column
- API endpoints for pin/unpin
- Delete protection for pinned videos
- Plex "Keepers" collection integration
- Automatic cleanup exclusion

**See:** `pin-keeper-ui.md` for frontend implementation details

#### 4. Per-Channel Video Limits (Backend Only)
**Status:** Backend ✅ | Frontend ⏳

**Completed:**
- Database table `channel_settings`
- API endpoints for get/set channel limits
- Cleanup respects per-channel overrides
- Fallback to global default

**See:** `per-channel-limits-ui.md` for frontend implementation details

---

## Pending UI Implementation

### Quick Overview

**Files to Modify:**
- `templates/index.html` - Main web UI

**Changes Needed:**

1. **Pin Feature UI** (~50 lines)
   - Add pin button to video cards
   - Add `togglePin()` JavaScript function
   - Update `deleteVideo()` to handle pinned videos
   - Add CSS for pinned video styling

2. **Channel Settings UI** (~150 lines)
   - Add settings icon (⚙️) to channel cards
   - Add channel settings modal (HTML)
   - Add channel settings JavaScript functions
   - Wire up save/cancel handlers

**Estimated Implementation Time:** 30-45 minutes

---

## Testing Backend Features (Without UI)

### Pin a Video via API
```bash
# Get a video ID
curl -s http://localhost:5001/api/videos | python3 -c "import sys, json; d = json.load(sys.stdin); print(list(d['videos'].values())[0][0]['video_id'])"

# Pin it
curl -X PATCH http://localhost:5001/api/videos/VIDEO_ID/pin \
  -H "Content-Type: application/json" \
  -d '{"keep_forever": true}'

# Verify in Plex
# → Check for "Keepers" collection in YouTube library
```

### Set Per-Channel Limit via API
```bash
# URL encode the channel URL
CHANNEL="https://www.youtube.com/@channelname"
ENCODED=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$CHANNEL', safe=''))")

# Set custom limit
curl -X PUT "http://localhost:5001/api/channels/$ENCODED/settings" \
  -H "Content-Type: application/json" \
  -d '{"video_limit": 10}'

# Get settings
curl -s "http://localhost:5001/api/channels/$ENCODED/settings" | python3 -m json.tool
```

---

## Architecture Notes

### Database Schema

**videos table:**
```sql
CREATE TABLE videos (
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
    keep_forever INTEGER DEFAULT 0  -- NEW: Pin status
);
```

**channel_settings table:**
```sql
CREATE TABLE channel_settings (
    channel_url TEXT PRIMARY KEY,
    video_limit INTEGER NOT NULL
);
```

### API Endpoints Summary

| Method | Endpoint | Purpose | Auth |
|--------|----------|---------|------|
| GET | `/api/videos` | List all videos (includes `keep_forever`, `channel_url`) | No |
| PATCH | `/api/videos/<id>/pin` | Pin/unpin video | Yes |
| DELETE | `/api/videos/<id>` | Delete video (blocked if pinned) | No |
| GET | `/api/channels/<url>/settings` | Get channel limit | Yes |
| PUT | `/api/channels/<url>/settings` | Set/remove channel limit | Yes |

---

## Development Workflow

### 1. Testing New Features

```bash
# Start Flask app
cd youtube-downloader
uv run python -m youtube_downloader.cli serve

# In another terminal, test API
curl http://localhost:5001/api/stats
```

### 2. Database Inspection

```bash
# Access database
sqlite3 youtube-downloader/data/videos.db

# Check schema
.schema videos
.schema channel_settings

# Query pinned videos
SELECT video_id, title, keep_forever FROM videos WHERE keep_forever = 1;

# Query channel settings
SELECT * FROM channel_settings;
```

### 3. Plex Integration Testing

**Verify Keepers Collection:**
1. Navigate to Plex → YouTube library
2. Click "Collections" tab
3. Look for "Keepers" collection
4. Verify pinned videos appear there

---

## Known Issues & Limitations

1. **Plex Collection Sync:** Only runs when pinning/unpinning via API. Manual database edits won't trigger sync.

2. **Channel URL Encoding:** Always use `encodeURIComponent()` in JavaScript when passing channel URLs to API.

3. **Database Migration:** `keep_forever` column is added automatically on first run. Existing videos default to `keep_forever=0` (not pinned).

4. **Scheduler & Pin:** Pinned videos are excluded from cleanup but included in "latest N videos" download count.

---

## Future Enhancements

- [ ] Bulk pin/unpin operations
- [ ] Pin expiration (keep for X days)
- [ ] Download priority for pinned videos
- [ ] Export/import pin settings
- [ ] Per-channel custom download quality
- [ ] Tag system (beyond pin/unpin)

---

## Questions or Issues?

**Backend Code:**
- `src/youtube_downloader/database.py` - Database operations
- `src/youtube_downloader/app.py` - Flask routes
- `src/youtube_downloader/plex.py` - Plex integration
- `src/youtube_downloader/downloader.py` - Download & cleanup logic

**Frontend Code:**
- `templates/index.html` - Web UI (all HTML/CSS/JS in one file)

**Database Location:**
- Development: `youtube-downloader/data/videos.db`
- Production: Configured via `DATA_DIR` environment variable
