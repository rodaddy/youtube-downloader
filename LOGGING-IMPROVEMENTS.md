# YouTube Downloader - Logging & Resilience Improvements

## Summary

Comprehensive logging, error handling, and rate limit protection to solve "Download failed with exit code 1" issues and prevent YouTube throttling.

---

## 🔍 Problems Fixed

### Before
- ❌ Generic "exit code 1" errors with no details
- ❌ No retry logic for transient failures
- ❌ Lost error messages from yt-dlp
- ❌ No timeout handling (stuck downloads)
- ❌ No log viewing in web UI
- ❌ All downloads fire simultaneously (triggers YouTube rate limits)

### After
- ✅ Detailed error messages explaining WHY downloads fail
- ✅ Automatic retry with exponential backoff (3 attempts)
- ✅ Smart error classification (retryable vs permanent)
- ✅ 10-minute timeout per attempt
- ✅ Complete log viewer in web UI with filtering
- ✅ Download queue to avoid YouTube rate limits (1 at a time, 10s delay)

---

## 📊 Logging Improvements

### Enhanced Error Messages

Instead of:
```
Download failed with exit code 1
```

Now see:
```
[JoshJohnsonComedy] yt-dlp failed with exit code 1
[JoshJohnsonComedy] Error: Rate limited by YouTube - will retry with backoff
[JoshJohnsonComedy] Last output lines:
...actual yt-dlp error details...
[JoshJohnsonComedy] Retrying in 5s... (attempt 2/3)
```

### Error Classification

**Retryable Errors (will auto-retry):**
- Rate limiting (HTTP 429)
- Network timeouts
- Connection resets
- DNS failures
- Temporary unavailability

**Non-Retryable Errors (fail immediately):**
- Video unavailable/deleted
- Private videos
- Age-restricted (requires login)
- Invalid URLs
- Premieres not started yet

### Structured Logging

All log messages now include:
- `[ChannelName]` prefix for easy filtering
- Attempt number (1/3, 2/3, 3/3)
- Last 15 lines of yt-dlp output on failure
- Retry countdown timers
- Timeout status

---

## 🔁 Retry Logic

### Configuration
```python
MAX_RETRIES = 3              # 3 attempts total
RETRY_DELAY_BASE = 5         # 5 seconds base delay
TIMEOUT_SECONDS = 600        # 10 minutes per attempt
```

### Exponential Backoff

- **Attempt 1 fails** → Wait 5 seconds → Retry
- **Attempt 2 fails** → Wait 10 seconds → Retry
- **Attempt 3 fails** → Permanent failure

### Smart Retry Logic

```python
def parse_ytdlp_error(output_lines):
    """Parse yt-dlp output to determine:
    1. What actually went wrong (meaningful error message)
    2. Whether it's worth retrying (retryable vs permanent)
    """
```

**Example Flow:**

1. Network timeout → Retry automatically
2. Video is private → Fail immediately (no retry)
3. Rate limited → Retry with longer delays

---

## 📥 Download Queue System

### Rate Limit Protection

**Problem:** Multiple simultaneous downloads trigger YouTube rate limiting (HTTP 429 errors).

**Solution:** Serialize downloads through a queue with delays between starts.

### Configuration

```python
MAX_CONCURRENT_DOWNLOADS = 1  # Only 1 channel downloads at a time
DOWNLOAD_START_DELAY = 10     # Wait 10 seconds between starting downloads
```

### How It Works

1. **Queueing:** When "Download All Channels" is clicked, all channels are added to a queue (not started simultaneously)
2. **Worker Thread:** Background thread processes the queue one download at a time
3. **Delay Between Downloads:** After completing a download, waits 10 seconds before starting the next
4. **Status Tracking:** Web UI shows queue size and active downloads in real-time

### Example Flow

```
[User clicks "Download All Channels" with 5 channels]

Queue: [Channel1, Channel2, Channel3, Channel4, Channel5]

Time 00:00 → Start Channel1 (queue: 4 waiting)
Time 00:00 → Channel1 downloading...
Time 05:30 → Channel1 complete
Time 05:30 → Wait 10 seconds...
Time 05:40 → Start Channel2 (queue: 3 waiting)
Time 05:40 → Channel2 downloading...
...and so on
```

### Web UI Queue Status

**Location:** Above "Active Downloads" section

**Display:**
- **Active:** "1 downloading" (green) when a download is in progress
- **Queued:** "N downloads queued" (orange) when downloads are waiting
- **Info:** "(10s delay between downloads)" reminder

**Example:**
```
📥 Queue Status: 1 downloading | 4 downloads queued (10s delay between downloads)
```

### Benefits

1. **Avoids Rate Limits:** YouTube sees requests spaced out, not bursts
2. **Automatic Pacing:** No manual intervention needed
3. **Better Error Handling:** Errors in one download don't affect others
4. **Resource Control:** Prevents system overload from parallel downloads
5. **Predictable Behavior:** Downloads happen in order, one at a time

---

## 📺 Web UI Improvements

### New: Log Viewer Modal (📋 Button)

**Features:**
- **Modal popup** - Click 📋 button in header to open
- Real-time log viewer (auto-refreshes every 5 seconds when open)
- Filter by log level (ERROR, WARNING, INFO, DEBUG)
- Search logs by keyword
- Color-coded log levels:
  - 🔴 ERROR (red)
  - 🟠 WARNING (orange)
  - 🟢 INFO (green)
  - ⚪ DEBUG (gray)
- Download full log file (💾 button)
- Shows last 200 lines (configurable)
- Auto-scrolls to newest entries
- Large modal (1200px wide) for better readability

**Location:** Header toolbar → 📋 button

### New: Server Restart Button

**Features:**
- Restart server from web UI (Settings → Server Control)
- Smart restart behavior:
  - **Debug mode** (default): Triggers Flask auto-reload
  - **Production mode**: Sends SIGHUP for graceful restart
- Confirmation dialog to prevent accidental restarts
- Auto-reloads web page after restart

**Location:** Settings modal → Server Control section

### Auto-Reload for Development

**Flask auto-reload is enabled by default** (`DEBUG=True`):

✅ **Code changes auto-reload** - Edit any `.py` file and Flask restarts automatically
✅ **No manual restart needed** - Just save your file and refresh the browser
✅ **Fast development loop** - Changes appear in ~1-2 seconds

**To toggle debug mode:**
```bash
# In .env file
DEBUG=true   # Auto-reload enabled (default)
DEBUG=false  # Production mode, no auto-reload
```

**When to use the restart button:**
- Changed `.env` configuration (not code)
- Need to reload config without code changes
- Running in production (DEBUG=false)

### API Endpoints

**GET `/api/logs`**
- Query params: `lines`, `level`, `search`
- Returns filtered log entries with stats

**GET `/api/logs/download`**
- Downloads full log file as attachment

**POST `/api/logs/level`** (auth required)
- Change logging level dynamically
- Body: `{"level": "DEBUG"}` or INFO, WARNING, ERROR

**POST `/api/restart`** (auth required)
- Restart the server
- Debug mode: triggers auto-reload
- Production: sends SIGHUP signal

---

## 🚀 Performance Improvements

### Timeout Handling

Each download attempt now has a 10-minute timeout:
- Prevents stuck downloads from blocking queue
- Automatically kills hung yt-dlp processes
- Retries after timeout (if attempts remain)

### Progress Tracking

Enhanced progress logging:
```
[ChannelName] Download attempt 1/3 (ID: abc-123)
[ChannelName] [download] 45.2% of 123MB at 2.5MB/s ETA 00:45
[ChannelName] Download completed successfully
```

---

## 📝 Testing

### View Logs
1. Navigate to web UI (http://localhost:5001)
2. Click 📋 button in header toolbar
3. See color-coded real-time logs in modal popup

### Filter Logs
- **By level**: Select ERROR/WARNING/INFO/DEBUG dropdown
- **By search**: Type keyword (e.g., "JoshJohnson", "retry", "failed")
- **Download**: Click 💾 button to download full `app.log` file
- **Refresh**: Click 🔄 button or wait for auto-refresh (every 5s)

### Test Auto-Reload
1. Start server: `uv run python -m youtube_downloader.cli serve`
2. Edit any `.py` file (e.g., add a comment in `downloader.py`)
3. Save the file
4. Watch terminal - Flask detects change and restarts automatically
5. Refresh browser - changes are live

### Test Restart Button
1. Open Settings modal (⚙️ button in header)
2. Scroll down to "🔄 Server Control" section
3. Click "🔄 Restart Server" button
4. Confirm the restart in dialog
5. Page auto-reloads after 3 seconds

### Test Retry Logic
1. Trigger downloads (click "Download All Channels")
2. Watch "Active Downloads" section
3. Click 📋 to open log viewer
4. Filter by ERROR level to see failures
5. Watch retry countdown in logs:
   ```
   ERROR | [JoshJohnsonComedy] Network timeout - will retry
   WARNING | [JoshJohnsonComedy] Retrying in 5s... (attempt 2/3)
   INFO | [JoshJohnsonComedy] Download completed successfully
   ```

---

## 🔧 Technical Details

### Files Modified

**`src/youtube_downloader/downloader.py`** (250+ lines changed)
- Added `parse_ytdlp_error()` function
- Rewrote `_download_channel()` with retry loop
- Added timeout handling
- Enhanced logging throughout
- **NEW:** Added download queue system (`queue.Queue`)
- **NEW:** Added `_process_download_queue()` worker thread
- **NEW:** Modified `start_download()` to enqueue instead of spawn threads
- **NEW:** Added `get_queue_status()` for API

**`src/youtube_downloader/app.py`** (+145 lines)
- Added `/api/logs` endpoint (read logs with filters)
- Added `/api/logs/download` endpoint (download full log)
- Added `/api/logs/level` endpoint (change log level)
- Added `/api/restart` endpoint (restart server)
- **NEW:** Added `/api/queue` endpoint (queue status)

**`templates/index.html`** (+150 lines)
- Added 📋 button in header for log viewer
- Added log viewer modal (1200px wide popup)
- Added log filtering UI (level, search)
- Added color-coded log rendering
- Added download log file button
- Added restart server button in settings
- Auto-refresh logs only when modal is open
- **NEW:** Added queue status display above active downloads
- **NEW:** Added `renderQueueStatus()` function
- **NEW:** Modified `pollStatus()` to fetch queue data

### Dependencies

No new dependencies added - uses existing:
- `loguru` (already in use)
- `queue` (standard library)
- `threading` (standard library)
- `re` (standard library)
- `pathlib` (standard library)

---

## 📖 Usage Examples

### View Error Details in Web UI

1. **See failed downloads:**
   - Filter logs by ERROR level
   - Search for specific channel name
   - Read detailed error explanation

2. **Monitor retries:**
   - Watch "Retrying in Xs..." countdown
   - See which attempt (1/3, 2/3, 3/3)
   - Understand why retry is happening

3. **Debug issues:**
   - Download full log file
   - Search for specific video IDs
   - Track download progress over time

### Example Log Output

```
2026-01-21 13:45:12 | INFO     | [JoshJohnsonComedy] Download attempt 1/3 (ID: abc-123)
2026-01-21 13:45:15 | DEBUG    | [JoshJohnsonComedy] [download] Downloading video 1 of 3
2026-01-21 13:45:18 | ERROR    | [JoshJohnsonComedy] yt-dlp failed with exit code 1
2026-01-21 13:45:18 | ERROR    | [JoshJohnsonComedy] Error: Rate limited by YouTube - will retry with backoff
2026-01-21 13:45:18 | ERROR    | [JoshJohnsonComedy] Last output lines:
ERROR: unable to download video data: HTTP Error 429: Too Many Requests
2026-01-21 13:45:18 | WARNING  | [JoshJohnsonComedy] Retrying in 5s... (attempt 2/3)
2026-01-21 13:45:23 | INFO     | [JoshJohnsonComedy] Download attempt 2/3 (ID: abc-123)
2026-01-21 13:45:35 | INFO     | [JoshJohnsonComedy] Download completed successfully
```

---

## 🎯 Benefits

1. **Troubleshooting** - Understand exactly why downloads fail
2. **Reliability** - Automatic retries handle transient errors
3. **Visibility** - Real-time log monitoring in web UI
4. **Performance** - Timeouts prevent stuck downloads
5. **Debugging** - Detailed logs with channel context
6. **Rate Limit Protection** - Queue system prevents YouTube throttling

---

## 🔮 Future Enhancements

Potential improvements (not yet implemented):

- [ ] Email/Discord notifications for persistent failures
- [ ] Retry count per channel (track failure patterns)
- [ ] Log retention policy (auto-delete old logs)
- [ ] Export logs to external logging service (e.g., Loki, Elasticsearch)
- [ ] Per-channel timeout configuration
- [ ] Configurable retry delays via settings

---

**Last Updated:** 2026-01-21
**Author:** Claude Code + Rico
**Version:** 1.1.0
