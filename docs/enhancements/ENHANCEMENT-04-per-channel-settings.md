# Enhancement #4: Per-Channel Settings

**Priority:** Medium
**Complexity:** Low
**Status:** Proposed

---

## Problem Statement

All channels use global defaults:
- Same video count limit (3 videos per channel)
- Same quality setting (bestvideo+bestaudio)
- Same download schedule (every 2 hours)

Users need flexibility for different channel types:
- **News channels** → More videos (10+), lower quality (720p), frequent updates
- **High-value creators** → Fewer videos (5), highest quality (4K), less frequent
- **Podcast channels** → Audio-only, many episodes (20+)

---

## Proposed Solution

Per-channel overrides stored in database with UI configuration.

---

## Database Schema

### Existing Table: `channels`

Already has `video_limit` column (added in previous enhancements):

```sql
CREATE TABLE IF NOT EXISTS channels (
    channel_url TEXT PRIMARY KEY,
    channel_name TEXT,
    video_limit INTEGER,  -- NULL = use global default
    created_at REAL DEFAULT (strftime('%s', 'now')),
    last_downloaded REAL
);
```

### New Columns to Add:

```sql
ALTER TABLE channels ADD COLUMN quality_profile TEXT DEFAULT NULL;  -- NULL = use global
ALTER TABLE channels ADD COLUMN download_frequency TEXT DEFAULT NULL;  -- 'hourly', 'daily', 'weekly', NULL = global
ALTER TABLE channels ADD COLUMN enabled BOOLEAN DEFAULT 1;  -- Allow disabling without deletion
ALTER TABLE channels ADD COLUMN priority INTEGER DEFAULT 0;  -- Download order (higher = first)
ALTER TABLE channels ADD COLUMN notes TEXT DEFAULT NULL;  -- User notes
```

---

## Quality Profiles

### Predefined Profiles

```python
QUALITY_PROFILES = {
    "4k": {
        "format": "bestvideo[height>=2160]+bestaudio/best",
        "description": "4K (2160p) - Highest quality, large files"
    },
    "1080p": {
        "format": "bestvideo[height>=1080]+bestaudio/best",
        "description": "Full HD (1080p) - High quality"
    },
    "720p": {
        "format": "bestvideo[height>=720]+bestaudio/best",
        "description": "HD (720p) - Balanced quality/size"
    },
    "480p": {
        "format": "bestvideo[height>=480]+bestaudio/best",
        "description": "SD (480p) - Smaller files"
    },
    "audio": {
        "format": "bestaudio/best",
        "description": "Audio only - Podcasts/music"
    },
    "default": {
        "format": "bestvideo+bestaudio/best",
        "description": "Best available quality"
    }
}
```

---

## UI Design

### Channel Card Enhancements

**Existing:**
```html
<div class="channel-card">
    <div class="channel-name">JoshJohnsonComedy</div>
    <button onclick="downloadChannel(url)">Download</button>
</div>
```

**Enhanced:**
```html
<div class="channel-card">
    <div class="channel-header">
        <div class="channel-name">JoshJohnsonComedy</div>
        <div class="channel-badges">
            <span class="badge badge-quality">1080p</span>
            <span class="badge badge-limit">5 videos</span>
            <span class="badge badge-priority" title="High priority">⭐⭐⭐</span>
        </div>
    </div>
    <div class="channel-actions">
        <button onclick="downloadChannel(url)">Download</button>
        <button onclick="editChannel(url)" class="icon-btn">⚙️</button>
        <button onclick="toggleChannel(url)" class="icon-btn">
            ${enabled ? '✅' : '⏸️'}
        </button>
    </div>
</div>
```

### Channel Settings Modal

```html
<div class="modal-overlay" id="channelSettingsModal">
    <div class="modal">
        <h2>⚙️ Channel Settings</h2>
        <p class="channel-url" id="editChannelUrl"></p>

        <div class="form-group">
            <label for="channelName">Channel Name</label>
            <input type="text" id="channelName" placeholder="Custom display name">
        </div>

        <div class="form-group">
            <label for="videoLimit">Videos Per Download</label>
            <input type="number" id="videoLimit" min="1" max="50" placeholder="3 (default)">
            <small>Leave empty to use global default (3)</small>
        </div>

        <div class="form-group">
            <label for="qualityProfile">Quality Profile</label>
            <select id="qualityProfile">
                <option value="">Default (Best available)</option>
                <option value="4k">4K (2160p) - Highest quality</option>
                <option value="1080p">Full HD (1080p)</option>
                <option value="720p">HD (720p)</option>
                <option value="480p">SD (480p)</option>
                <option value="audio">Audio Only</option>
            </select>
        </div>

        <div class="form-group">
            <label for="downloadFrequency">Download Frequency</label>
            <select id="downloadFrequency">
                <option value="">Default (Global schedule)</option>
                <option value="hourly">Every hour</option>
                <option value="daily">Once per day</option>
                <option value="weekly">Once per week</option>
                <option value="manual">Manual only</option>
            </select>
        </div>

        <div class="form-group">
            <label for="channelPriority">Download Priority</label>
            <select id="channelPriority">
                <option value="0">Normal</option>
                <option value="1">High ⭐</option>
                <option value="2">Very High ⭐⭐</option>
                <option value="3">Critical ⭐⭐⭐</option>
            </select>
            <small>Higher priority channels download first in queue</small>
        </div>

        <div class="form-group">
            <label>
                <input type="checkbox" id="channelEnabled"> Enabled
            </label>
            <small>Disable to skip in scheduled downloads without removing</small>
        </div>

        <div class="form-group">
            <label for="channelNotes">Notes</label>
            <textarea id="channelNotes" rows="3" placeholder="Optional notes..."></textarea>
        </div>

        <div class="modal-buttons">
            <button type="button" class="outline" onclick="closeChannelSettings()">Cancel</button>
            <button type="button" onclick="saveChannelSettings()">Save Settings</button>
        </div>
    </div>
</div>
```

---

## API Endpoints

### GET `/api/channels/<channel_url>/settings`

**Response:**
```json
{
  "channel_url": "https://youtube.com/@JoshJohnsonComedy",
  "channel_name": "Josh Johnson",
  "video_limit": 5,
  "quality_profile": "1080p",
  "download_frequency": "daily",
  "enabled": true,
  "priority": 2,
  "notes": "Comedy sketches and commentary"
}
```

### PUT `/api/channels/<channel_url>/settings`

**Request:**
```json
{
  "channel_name": "Josh Johnson",
  "video_limit": 5,
  "quality_profile": "1080p",
  "download_frequency": "daily",
  "enabled": true,
  "priority": 2,
  "notes": "Comedy sketches"
}
```

### POST `/api/channels/<channel_url>/toggle`

**Action:** Enable/disable channel

**Response:**
```json
{
  "channel_url": "...",
  "enabled": false
}
```

---

## Implementation

### Database Methods

**In `database.py`:**

```python
def update_channel_settings(
    self,
    channel_url: str,
    channel_name: Optional[str] = None,
    video_limit: Optional[int] = None,
    quality_profile: Optional[str] = None,
    download_frequency: Optional[str] = None,
    enabled: Optional[bool] = None,
    priority: Optional[int] = None,
    notes: Optional[str] = None
) -> None:
    """Update channel-specific settings."""
    # Build dynamic UPDATE query for provided fields
    # NULL values mean "use global default"

def get_channel_settings(self, channel_url: str) -> dict:
    """Get channel settings with defaults filled in."""
    # Query database
    # Fill NULL values with global defaults
    # Return complete settings dict

def get_enabled_channels(self) -> list[str]:
    """Get list of enabled channel URLs."""
    cursor = self.conn.execute(
        "SELECT channel_url FROM channels WHERE enabled = 1 ORDER BY priority DESC, channel_url"
    )
    return [row[0] for row in cursor.fetchall()]
```

### Download Logic Updates

**In `downloader.py`:**

```python
def download_all_channels(self) -> list[str]:
    """Download from all ENABLED channels in priority order."""
    if self.database:
        channels = self.database.get_enabled_channels()  # Respects enabled flag and priority
    else:
        channels = self.load_channels()  # Fallback to channels.txt

    download_ids = []
    for channel_url in channels:
        # Get channel-specific settings
        settings = self.database.get_channel_settings(channel_url) if self.database else {}

        # Use per-channel limits or global defaults
        video_limit = settings.get('video_limit') or self.settings.videos_per_channel
        quality = settings.get('quality_profile') or self.settings.max_quality

        download_id = self.start_download(
            channel_url,
            video_limit=video_limit,
            quality_profile=quality
        )
        download_ids.append(download_id)

    return download_ids

def start_download(
    self,
    channel_url: str,
    video_limit: Optional[int] = None,
    quality_profile: Optional[str] = None
) -> str:
    """Start download with optional overrides."""
    # Use provided limits or fall back to global settings
    # Pass to _download_channel
```

### Scheduler Updates

**In `scheduler.py`:**

```python
def should_download_channel(self, channel_url: str) -> bool:
    """Check if channel should be downloaded based on frequency setting."""
    if not self.database:
        return True  # No database = download all

    settings = self.database.get_channel_settings(channel_url)

    if not settings.get('enabled'):
        return False  # Disabled channels never download

    frequency = settings.get('download_frequency')
    if not frequency:  # NULL = use global schedule
        return True

    last_download = self.database.get_last_download_time(channel_url)
    if not last_download:
        return True  # Never downloaded = download now

    hours_since = (time() - last_download) / 3600

    if frequency == 'hourly':
        return hours_since >= 1
    elif frequency == 'daily':
        return hours_since >= 24
    elif frequency == 'weekly':
        return hours_since >= 168
    elif frequency == 'manual':
        return False  # Never auto-download

    return True  # Default = download
```

---

## Success Criteria

- [ ] Per-channel video limits work
- [ ] Quality profiles applied correctly
- [ ] Download frequency respected by scheduler
- [ ] Enable/disable channels without deletion
- [ ] Priority ordering in queue
- [ ] Settings persist across restarts
- [ ] UI shows channel badges (quality, limit, priority)
- [ ] Settings modal saves and loads correctly
- [ ] NULL values correctly use global defaults

---

## Migration

**Existing channels.txt:**
- Import into database with default settings
- Preserve video_limit if already set
- All other fields NULL (use globals)

**Backward Compatibility:**
- If database doesn't exist, fall back to channels.txt
- Global settings still work if no per-channel overrides

---

## Example Use Cases

### Use Case 1: News Channel (High Volume)

```
Channel: LastWeekTonight
Settings:
  - video_limit: 15 (more than default 3)
  - quality_profile: 720p (smaller files)
  - download_frequency: daily
  - priority: 1 (high)
  - enabled: true

Result: Downloads 15 videos in 720p once per day, queued first
```

### Use Case 2: Podcast (Audio Only)

```
Channel: JoeRoganExperience
Settings:
  - video_limit: 20
  - quality_profile: audio (no video)
  - download_frequency: weekly
  - priority: 0 (normal)
  - enabled: true

Result: Downloads 20 audio-only episodes once per week
```

### Use Case 3: Premium Creator (4K)

```
Channel: MKBHD
Settings:
  - video_limit: 5
  - quality_profile: 4k
  - download_frequency: daily
  - priority: 2 (very high)
  - enabled: true

Result: Downloads 5 videos in 4K daily, queued early
```

---

**Estimated Effort:** 6-8 hours
**Risk:** Medium (touches download and scheduler logic)
**Value:** High (major flexibility improvement)
