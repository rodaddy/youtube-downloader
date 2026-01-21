# Enhancement #5: Bulk Operations

**Priority:** Low
**Complexity:** Low
**Status:** Proposed

---

## Problem Statement

Users can only perform actions on individual channels/videos:
- Download one channel at a time (unless using "Download All")
- Delete one video at a time
- Pin/unpin one video at a time

Need batch operations for:
- Managing large libraries (100+ videos)
- Cleanup operations (delete old videos in bulk)
- Applying settings to multiple channels

---

## Proposed Solution

Add bulk selection UI with batch operations.

---

## UI Design

### Bulk Selection Mode

**Header Toolbar Addition:**

```html
<div class="header-buttons">
    <button onclick="toggleBulkMode()" id="bulkModeBtn" class="icon-btn" title="Bulk operations">☑️</button>
    <!-- existing buttons: logs, settings, etc. -->
</div>

<!-- Bulk Actions Bar (hidden by default) -->
<div id="bulkActionsBar" style="display: none; background: #1f2a1f; padding: 15px; margin-bottom: 20px; border-radius: 8px;">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <div>
            <span id="selectedCount">0</span> items selected
            <button onclick="selectAll()" class="secondary" style="margin-left: 10px;">Select All</button>
            <button onclick="deselectAll()" class="outline">Deselect All</button>
        </div>
        <div>
            <button onclick="bulkDownload()" class="icon-btn" title="Download selected">⬇️</button>
            <button onclick="bulkDelete()" class="icon-btn" title="Delete selected">🗑️</button>
            <button onclick="bulkPin()" class="icon-btn" title="Pin selected">📌</button>
            <button onclick="bulkUnpin()" class="icon-btn" title="Unpin selected">📍</button>
            <button onclick="bulkSetQuality()" class="icon-btn" title="Set quality">🎬</button>
            <button onclick="bulkEnable()" class="icon-btn" title="Enable">✅</button>
            <button onclick="bulkDisable()" class="icon-btn" title="Disable">⏸️</button>
        </div>
    </div>
</div>
```

### Channel Cards with Checkboxes

**In Bulk Mode:**

```html
<div class="channel-card" data-channel-url="${url}">
    <input type="checkbox" class="bulk-checkbox" onchange="updateBulkSelection()">
    <div class="channel-name">JoshJohnsonComedy</div>
    <!-- rest of card -->
</div>
```

### Video List with Checkboxes

**In Bulk Mode:**

```html
<div class="video-item" data-video-id="${id}">
    <input type="checkbox" class="bulk-checkbox" onchange="updateBulkSelection()">
    <div class="video-title">${title}</div>
    <!-- rest of item -->
</div>
```

---

## Bulk Operations

### 1. Bulk Download

**Action:** Download multiple channels at once
**API:** `POST /api/bulk/download`
**Request:**
```json
{
  "channel_urls": [
    "https://youtube.com/@Channel1",
    "https://youtube.com/@Channel2",
    "https://youtube.com/@Channel3"
  ]
}
```
**Response:**
```json
{
  "download_ids": ["id1", "id2", "id3"],
  "queued": 3
}
```

### 2. Bulk Delete

**Action:** Delete multiple videos
**API:** `POST /api/bulk/delete`
**Request:**
```json
{
  "video_ids": ["vid1", "vid2", "vid3"]
}
```
**Response:**
```json
{
  "deleted": 3,
  "freed_space_mb": 1250
}
```
**Confirmation:** "Delete 3 videos? This will free 1.25 GB."

### 3. Bulk Pin/Unpin

**Action:** Pin/unpin multiple videos (keeper feature)
**API:** `POST /api/bulk/pin` / `POST /api/bulk/unpin`
**Request:**
```json
{
  "video_ids": ["vid1", "vid2", "vid3"]
}
```

### 4. Bulk Set Quality

**Action:** Apply quality profile to multiple channels
**API:** `POST /api/bulk/quality`
**Request:**
```json
{
  "channel_urls": ["url1", "url2"],
  "quality_profile": "720p"
}
```
**UI:** Modal with quality dropdown

### 5. Bulk Enable/Disable

**Action:** Enable or disable multiple channels
**API:** `POST /api/bulk/enable` / `POST /api/bulk/disable`
**Request:**
```json
{
  "channel_urls": ["url1", "url2", "url3"]
}
```

### 6. Bulk Set Video Limit

**Action:** Set video limit for multiple channels
**API:** `POST /api/bulk/video-limit`
**Request:**
```json
{
  "channel_urls": ["url1", "url2"],
  "video_limit": 10
}
```

---

## Advanced Bulk Operations

### Cleanup by Age

**UI:** Settings → Cleanup → "Delete videos older than X days"

```html
<div class="form-group">
    <label>Auto-cleanup Videos Older Than:</label>
    <input type="number" id="cleanupDays" min="7" max="365" placeholder="30">
    <span>days</span>
    <button onclick="previewCleanup()">Preview</button>
    <button onclick="executeCleanup()">Delete</button>
</div>
```

**API:** `POST /api/cleanup/by-age`
**Request:**
```json
{
  "days": 30,
  "preview": true  // Return what would be deleted without actually deleting
}
```
**Response:**
```json
{
  "preview": true,
  "videos_to_delete": 45,
  "space_to_free_mb": 5600,
  "videos": [
    {"id": "vid1", "title": "...", "age_days": 45, "size_mb": 120},
    ...
  ]
}
```

### Cleanup by Size

**UI:** "Delete largest N videos"

**API:** `POST /api/cleanup/by-size`
**Request:**
```json
{
  "count": 10,  // Delete 10 largest videos
  "preview": true
}
```

### Re-scan Metadata

**Action:** Refresh metadata for multiple videos
**Use Case:** Thumbnails missing, info.json corrupted

**API:** `POST /api/bulk/rescan`
**Request:**
```json
{
  "video_ids": ["vid1", "vid2"],
  "refresh_thumbnails": true,
  "refresh_metadata": true
}
```

---

## Implementation

### JavaScript (Frontend)

```javascript
let bulkModeActive = false;
let selectedItems = new Set();

function toggleBulkMode() {
    bulkModeActive = !bulkModeActive;

    // Show/hide checkboxes
    document.querySelectorAll('.bulk-checkbox').forEach(cb => {
        cb.style.display = bulkModeActive ? 'inline-block' : 'none';
    });

    // Show/hide bulk actions bar
    document.getElementById('bulkActionsBar').style.display =
        bulkModeActive ? 'block' : 'none';

    // Update button appearance
    document.getElementById('bulkModeBtn').classList.toggle('active', bulkModeActive);

    if (!bulkModeActive) {
        deselectAll();
    }
}

function updateBulkSelection() {
    selectedItems.clear();
    document.querySelectorAll('.bulk-checkbox:checked').forEach(cb => {
        const item = cb.closest('[data-channel-url], [data-video-id]');
        const id = item.dataset.channelUrl || item.dataset.videoId;
        selectedItems.add(id);
    });

    document.getElementById('selectedCount').textContent = selectedItems.size;
}

function selectAll() {
    document.querySelectorAll('.bulk-checkbox').forEach(cb => {
        cb.checked = true;
    });
    updateBulkSelection();
}

function deselectAll() {
    document.querySelectorAll('.bulk-checkbox').forEach(cb => {
        cb.checked = false;
    });
    updateBulkSelection();
}

async function bulkDownload() {
    const channels = Array.from(selectedItems);
    if (channels.length === 0) {
        alert('No channels selected');
        return;
    }

    if (!confirm(`Download ${channels.length} channels?`)) {
        return;
    }

    const response = await fetch('/api/bulk/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channel_urls: channels })
    });

    const data = await response.json();
    alert(`Queued ${data.queued} channels for download`);
    deselectAll();
}

async function bulkDelete() {
    const videos = Array.from(selectedItems);
    if (videos.length === 0) {
        alert('No videos selected');
        return;
    }

    // Get size preview
    const preview = await fetch('/api/bulk/delete/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ video_ids: videos })
    }).then(r => r.json());

    if (!confirm(`Delete ${videos.length} videos? This will free ${preview.space_mb} MB.`)) {
        return;
    }

    const response = await fetch('/api/bulk/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ video_ids: videos })
    });

    const data = await response.json();
    alert(`Deleted ${data.deleted} videos, freed ${data.freed_space_mb} MB`);
    deselectAll();
    loadVideos();  // Refresh
}

async function bulkSetQuality() {
    const channels = Array.from(selectedItems);
    if (channels.length === 0) {
        alert('No channels selected');
        return;
    }

    const quality = prompt('Quality profile (4k, 1080p, 720p, 480p, audio):');
    if (!quality) return;

    const response = await fetch('/api/bulk/quality', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            channel_urls: channels,
            quality_profile: quality
        })
    });

    const data = await response.json();
    alert(`Updated ${data.updated} channels to ${quality}`);
    deselectAll();
}
```

### Backend (API)

**In `app.py`:**

```python
@app.route("/api/bulk/download", methods=["POST"])
@auth.login_required
def bulk_download():
    """Download multiple channels."""
    data = request.json
    channel_urls = data.get("channel_urls", [])

    if not channel_urls:
        return jsonify({"error": "No channels provided"}), 400

    download_ids = []
    for url in channel_urls:
        download_id = download_manager.start_download(url)
        download_ids.append(download_id)

    return jsonify({
        "download_ids": download_ids,
        "queued": len(download_ids)
    })

@app.route("/api/bulk/delete", methods=["POST"])
@auth.login_required
def bulk_delete():
    """Delete multiple videos."""
    data = request.json
    video_ids = data.get("video_ids", [])

    if not video_ids:
        return jsonify({"error": "No videos provided"}), 400

    deleted = 0
    freed_space = 0

    for video_id in video_ids:
        size = database.get_video_size(video_id)
        database.delete_video(video_id, delete_file=True)
        deleted += 1
        freed_space += size

    return jsonify({
        "deleted": deleted,
        "freed_space_mb": freed_space / 1024 / 1024
    })

@app.route("/api/bulk/quality", methods=["POST"])
@auth.login_required
def bulk_set_quality():
    """Set quality profile for multiple channels."""
    data = request.json
    channel_urls = data.get("channel_urls", [])
    quality_profile = data.get("quality_profile")

    if not channel_urls or not quality_profile:
        return jsonify({"error": "Invalid request"}), 400

    updated = 0
    for url in channel_urls:
        database.update_channel_settings(url, quality_profile=quality_profile)
        updated += 1

    return jsonify({"updated": updated})

@app.route("/api/cleanup/by-age", methods=["POST"])
@auth.login_required
def cleanup_by_age():
    """Delete videos older than specified days."""
    data = request.json
    days = data.get("days", 30)
    preview = data.get("preview", False)

    cutoff_timestamp = time() - (days * 86400)
    videos_to_delete = database.get_videos_older_than(cutoff_timestamp)

    if preview:
        return jsonify({
            "preview": True,
            "videos_to_delete": len(videos_to_delete),
            "space_to_free_mb": sum(v.file_size for v in videos_to_delete) / 1024 / 1024,
            "videos": [
                {
                    "id": v.video_id,
                    "title": v.title,
                    "age_days": (time() - v.upload_date_timestamp) / 86400,
                    "size_mb": v.file_size / 1024 / 1024
                }
                for v in videos_to_delete[:50]  # Limit preview
            ]
        })

    # Actually delete
    deleted = 0
    freed = 0
    for video in videos_to_delete:
        database.delete_video(video.video_id, delete_file=True)
        deleted += 1
        freed += video.file_size

    return jsonify({
        "deleted": deleted,
        "freed_space_mb": freed / 1024 / 1024
    })
```

---

## Success Criteria

- [ ] Bulk mode toggle works
- [ ] Checkboxes appear on channels and videos
- [ ] Select all / deselect all works
- [ ] Bulk download queues multiple channels
- [ ] Bulk delete removes videos and frees space
- [ ] Bulk pin/unpin updates database
- [ ] Bulk quality setting applies to channels
- [ ] Cleanup by age preview shows what will be deleted
- [ ] Cleanup by age actually deletes files
- [ ] Selection count accurate
- [ ] Operations show confirmation dialogs

---

## Future Enhancements

- Import/export channel lists (CSV, JSON)
- Bulk re-download (force re-fetch videos)
- Bulk move to different directory
- Scheduled cleanup (auto-delete old videos)
- Bulk metadata refresh
- Tag/category management

---

**Estimated Effort:** 6-8 hours
**Risk:** Low (mostly UI, isolated operations)
**Value:** Medium (convenience for large libraries)
