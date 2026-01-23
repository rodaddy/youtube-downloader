# Enhancement #7: Auto-Cleanup of Downloaded Content

**Priority:** High
**Complexity:** Low
**Status:** Proposed

---

## Problem Statement

No automatic cleanup mechanism for downloaded videos:
- Channels with 436+ videos can accidentally download everything (just happened!)
- Old watched content accumulates and wastes storage
- No way to enforce "keep only last N videos per channel"
- Manual deletion is tedious and error-prone

---

## Proposed Solution

Automatic cleanup system with multiple strategies and safety checks.

---

## Cleanup Strategies

### Strategy 1: Keep Only Last N Videos Per Channel

**Most Useful for Current Issue**

**Settings:**
```bash
# .env
CLEANUP_ENABLED=true
CLEANUP_STRATEGY=keep_last_n
CLEANUP_KEEP_LAST_N=3  # Keep only the 3 most recent videos per channel
CLEANUP_RESPECT_PINNED=true  # Never delete pinned/keeper videos
```

**How It Works:**
1. For each channel, get all downloaded videos sorted by upload date (newest first)
2. Keep the first N videos (most recent)
3. Delete videos at position N+1 and beyond
4. Respect pinned videos (never delete)
5. Update download archive (remove deleted video IDs)

**Example:**
```
Channel: NateBJones (135 videos downloaded)

After cleanup with KEEP_LAST_N=3:
- Keep: Video #1, #2, #3 (newest)
- Delete: Videos #4-135 (132 videos deleted)
- Result: Only 3 most recent videos remain
```

---

### Strategy 2: Delete Videos Older Than X Days

**Settings:**
```bash
CLEANUP_STRATEGY=age_based
CLEANUP_MAX_AGE_DAYS=30  # Delete videos older than 30 days
```

**How It Works:**
1. Check video upload date from metadata
2. Delete if older than threshold
3. Respect pinned videos

---

### Strategy 3: Delete Watched Videos (Plex Integration)

**Settings:**
```bash
CLEANUP_STRATEGY=watched
CLEANUP_WATCHED_AFTER_DAYS=7  # Delete videos 7 days after watched
CLEANUP_WATCHED_MIN_PERCENT=90  # Only if watched >= 90%
```

**How It Works:**
1. Query Plex API for watch status
2. Delete videos marked as "watched" (with minimum watch percentage)
3. Optional: Wait X days after watched before deleting
4. Respect pinned videos

---

### Strategy 4: Storage Limit

**Settings:**
```bash
CLEANUP_STRATEGY=storage_limit
CLEANUP_MAX_STORAGE_GB=50  # Keep total storage under 50GB
```

**How It Works:**
1. Calculate total storage used by downloads
2. If over limit, delete oldest videos until under threshold
3. Respect pinned videos

---

## Implementation

### Database Schema Updates

**Add columns to videos table:**
```sql
ALTER TABLE videos ADD COLUMN pinned BOOLEAN DEFAULT 0;
ALTER TABLE videos ADD COLUMN last_watched_at REAL;
ALTER TABLE videos ADD COLUMN watch_percent INTEGER DEFAULT 0;
```

### New Module: `cleanup.py`

```python
from dataclasses import dataclass
from pathlib import Path
from typing import List
import time
from loguru import logger

@dataclass
class CleanupStats:
    videos_deleted: int
    space_freed_mb: float
    channels_processed: int

class CleanupManager:
    def __init__(self, database: "Database", settings: "Settings"):
        self.database = database
        self.settings = settings

    def cleanup_keep_last_n(self, keep_count: int = 3) -> CleanupStats:
        """Keep only the last N videos per channel."""
        stats = CleanupStats(videos_deleted=0, space_freed_mb=0, channels_processed=0)

        # Get all channels
        channels = self.database.get_all_channels()

        for channel in channels:
            # Get videos for this channel, sorted by upload date (newest first)
            videos = self.database.get_channel_videos(
                channel.url,
                order_by="upload_date DESC"
            )

            # Keep first N, delete the rest
            videos_to_delete = videos[keep_count:]

            for video in videos_to_delete:
                # Skip pinned videos
                if video.pinned:
                    logger.info(f"Skipping pinned video: {video.title}")
                    continue

                # Get file size before deletion
                file_path = Path(video.file_path)
                if file_path.exists():
                    size_mb = file_path.stat().st_size / 1024 / 1024
                    stats.space_freed_mb += size_mb

                # Delete video
                self.database.delete_video(video.video_id, delete_file=True)
                stats.videos_deleted += 1

                logger.info(
                    f"Deleted old video: {video.title} "
                    f"({size_mb:.2f} MB) from {channel.name}"
                )

            stats.channels_processed += 1

        logger.info(
            f"Cleanup complete: {stats.videos_deleted} videos deleted, "
            f"{stats.space_freed_mb:.2f} MB freed"
        )
        return stats

    def cleanup_by_age(self, max_age_days: int) -> CleanupStats:
        """Delete videos older than specified days."""
        cutoff_timestamp = time.time() - (max_age_days * 86400)
        stats = CleanupStats(videos_deleted=0, space_freed_mb=0, channels_processed=0)

        videos = self.database.get_videos_older_than(cutoff_timestamp)

        for video in videos:
            if video.pinned:
                continue

            file_path = Path(video.file_path)
            if file_path.exists():
                size_mb = file_path.stat().st_size / 1024 / 1024
                stats.space_freed_mb += size_mb

            self.database.delete_video(video.video_id, delete_file=True)
            stats.videos_deleted += 1

        return stats

    def cleanup_watched(
        self,
        min_watch_percent: int = 90,
        watched_after_days: int = 0
    ) -> CleanupStats:
        """Delete watched videos from Plex."""
        stats = CleanupStats(videos_deleted=0, space_freed_mb=0, channels_processed=0)

        # Query Plex for watched videos
        # (Requires Plex integration fix from Enhancement #2)
        if not self.database.plex_manager:
            logger.warning("Plex integration not available for cleanup")
            return stats

        # Get all videos from database
        videos = self.database.get_all_videos()

        for video in videos:
            if video.pinned:
                continue

            # Check Plex watch status
            plex_item = self.database.plex_manager.get_video(video.video_id)
            if not plex_item:
                continue

            if plex_item.isWatched and plex_item.viewOffset >= (min_watch_percent / 100):
                # Check if enough time has passed since watched
                if watched_after_days > 0:
                    if not video.last_watched_at:
                        continue
                    days_since_watched = (time.time() - video.last_watched_at) / 86400
                    if days_since_watched < watched_after_days:
                        continue

                # Delete watched video
                file_path = Path(video.file_path)
                if file_path.exists():
                    size_mb = file_path.stat().st_size / 1024 / 1024
                    stats.space_freed_mb += size_mb

                self.database.delete_video(video.video_id, delete_file=True)
                stats.videos_deleted += 1

        return stats
```

---

## API Endpoints

### Trigger Manual Cleanup

```python
@app.route("/api/cleanup", methods=["POST"])
@auth.login_required
def trigger_cleanup():
    """Trigger manual cleanup."""
    data = request.json
    strategy = data.get("strategy", "keep_last_n")

    if strategy == "keep_last_n":
        keep_count = data.get("keep_count", 3)
        stats = cleanup_manager.cleanup_keep_last_n(keep_count)
    elif strategy == "age_based":
        max_age_days = data.get("max_age_days", 30)
        stats = cleanup_manager.cleanup_by_age(max_age_days)
    elif strategy == "watched":
        stats = cleanup_manager.cleanup_watched()
    else:
        return jsonify({"error": "Invalid strategy"}), 400

    return jsonify({
        "videos_deleted": stats.videos_deleted,
        "space_freed_mb": stats.space_freed_mb,
        "channels_processed": stats.channels_processed
    })

@app.route("/api/cleanup/preview", methods=["POST"])
@auth.login_required
def preview_cleanup():
    """Preview what would be deleted without actually deleting."""
    # Same logic as trigger_cleanup but with preview=True
    # Returns list of videos that WOULD be deleted
```

---

## UI Changes

### Settings Modal - Cleanup Section

```html
<div style="background: #1f2a1f; padding: 20px; border-radius: 8px;">
    <h3 style="color: #4CAF50;">🧹 Auto-Cleanup</h3>

    <div class="form-group">
        <label>
            <input type="checkbox" id="cleanupEnabled"> Enable Auto-Cleanup
        </label>
    </div>

    <div class="form-group">
        <label for="cleanupStrategy">Cleanup Strategy:</label>
        <select id="cleanupStrategy">
            <option value="keep_last_n">Keep Only Last N Videos Per Channel</option>
            <option value="age_based">Delete Videos Older Than X Days</option>
            <option value="watched">Delete Watched Videos (Plex)</option>
            <option value="storage_limit">Storage Limit</option>
        </select>
    </div>

    <!-- Strategy-specific settings -->
    <div id="keepLastNSettings" class="strategy-settings">
        <label for="keepLastN">Keep Last N Videos:</label>
        <input type="number" id="keepLastN" value="3" min="1" max="100">
    </div>

    <div id="ageBasedSettings" class="strategy-settings" style="display: none;">
        <label for="maxAgeDays">Delete Videos Older Than (Days):</label>
        <input type="number" id="maxAgeDays" value="30" min="1" max="365">
    </div>

    <div class="form-group">
        <label>
            <input type="checkbox" id="respectPinned" checked> Respect Pinned Videos (Never Delete)
        </label>
    </div>

    <div class="form-group">
        <button onclick="previewCleanup()">🔍 Preview Cleanup</button>
        <button onclick="triggerCleanup()">🧹 Run Cleanup Now</button>
    </div>
</div>
```

### Cleanup Preview Modal

```html
<div class="modal-overlay" id="cleanupPreviewModal">
    <div class="modal">
        <h2>Cleanup Preview</h2>

        <div class="stats-cards">
            <div class="stat-card">
                <div class="stat-value" id="previewVideosToDelete">0</div>
                <div class="stat-label">Videos to Delete</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="previewSpaceToFree">0 GB</div>
                <div class="stat-label">Space to Free</div>
            </div>
        </div>

        <div id="previewVideosList">
            <!-- Table of videos that will be deleted -->
        </div>

        <div class="modal-buttons">
            <button class="outline" onclick="closePreviewModal()">Cancel</button>
            <button onclick="confirmCleanup()">🗑️ Delete These Videos</button>
        </div>
    </div>
</div>
```

---

## Scheduler Integration

**Automatic cleanup runs:**
- After each scheduled download batch
- Daily at configured time (e.g., 3 AM)
- Triggered manually via UI

```python
# In scheduler.py
def _run_scheduled_downloads():
    # ... existing download logic ...

    # Run cleanup after downloads
    if settings.cleanup_enabled:
        logger.info("Running automatic cleanup")
        cleanup_manager.cleanup_keep_last_n(settings.cleanup_keep_last_n)
```

---

## Configuration (.env)

```bash
# Auto-Cleanup Settings
CLEANUP_ENABLED=true
CLEANUP_STRATEGY=keep_last_n  # Options: keep_last_n, age_based, watched, storage_limit

# Strategy: Keep Last N
CLEANUP_KEEP_LAST_N=3

# Strategy: Age-Based
CLEANUP_MAX_AGE_DAYS=30

# Strategy: Watched (Plex)
CLEANUP_WATCHED_AFTER_DAYS=7
CLEANUP_WATCHED_MIN_PERCENT=90

# Strategy: Storage Limit
CLEANUP_MAX_STORAGE_GB=50

# Safety
CLEANUP_RESPECT_PINNED=true  # Never delete pinned videos
CLEANUP_RUN_ON_SCHEDULE=true  # Run automatically after downloads
```

---

## Safety Features

1. **Pinned Video Protection:** Never delete videos marked as "pinned" (keeper feature)
2. **Preview Mode:** See what will be deleted before confirming
3. **Undo Not Possible:** Warn user that deletion is permanent
4. **Dry Run:** Test cleanup without actually deleting
5. **Logging:** Detailed logs of what was deleted and why
6. **Archive Updates:** Remove deleted video IDs from download archive

---

## Success Criteria

- [ ] Keep-last-N cleanup works correctly
- [ ] Age-based cleanup respects upload dates
- [ ] Watched cleanup integrates with Plex
- [ ] Pinned videos never deleted
- [ ] Preview shows accurate deletion list
- [ ] Space calculation accurate
- [ ] Settings persist across restarts
- [ ] Scheduler integration works
- [ ] Manual trigger works via UI
- [ ] Logs show detailed cleanup info

---

## Testing Plan

**Test Case 1: Keep Last N (Current Issue)**
1. Channel has 135 downloaded videos
2. Set CLEANUP_KEEP_LAST_N=3
3. Run cleanup
4. **Expected:** Only 3 newest videos remain, 132 deleted

**Test Case 2: Pinned Video Protection**
1. Channel has 10 videos
2. Pin video #5
3. Set CLEANUP_KEEP_LAST_N=3
4. Run cleanup
5. **Expected:** Videos #1-3 + pinned #5 remain, others deleted

**Test Case 3: Age-Based**
1. Videos uploaded 45 days ago
2. Set CLEANUP_MAX_AGE_DAYS=30
3. Run cleanup
4. **Expected:** Videos older than 30 days deleted

---

## Dependencies

- Enhancement #2 (Plex Integration Fix) - Required for watched cleanup strategy
- Database schema updates for pinned/watch tracking

---

## Implementation Priority

**Phase 1: Keep-Last-N (Immediate Need)**
- Implement keep_last_n strategy
- Add manual trigger button
- Preview functionality
- **Estimated Effort:** 3-4 hours

**Phase 2: Advanced Strategies**
- Age-based cleanup
- Watched cleanup (requires Plex fix)
- Storage limit cleanup
- **Estimated Effort:** 4-5 hours

**Phase 3: Scheduler Integration**
- Automatic cleanup after downloads
- Scheduled daily cleanup
- **Estimated Effort:** 1-2 hours

**Total Estimated Effort:** 8-11 hours

---

## Immediate Use Case

**Fix current NateBJones issue:**
```bash
# .env
CLEANUP_ENABLED=true
CLEANUP_STRATEGY=keep_last_n
CLEANUP_KEEP_LAST_N=3

# Web UI → Settings → Cleanup → Preview Cleanup
# Shows: 132 videos to delete (NateBJones), ~6.6 GB to free
# Click "Delete These Videos"
# Result: Only 3 newest NateBJones videos remain
```

---

**Estimated Effort:** 8-11 hours (Phase 1 alone: 3-4 hours)
**Risk:** Low (isolated feature, preview mode prevents accidents)
**Value:** High (solves current storage issue + prevents future problems)
