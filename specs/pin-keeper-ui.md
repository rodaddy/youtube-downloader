# Pin/Keeper Feature UI Specification

## Status: Backend Complete ✅ | Frontend Pending ⏳

## Overview
Add UI controls to pin/unpin videos, preventing automatic cleanup and adding them to a Plex "Keepers" collection.

---

## Backend API (Already Implemented)

### Pin/Unpin Video
```http
PATCH /api/videos/<video_id>/pin
Content-Type: application/json

{
  "keep_forever": true  // or false to unpin
}
```

**Response:**
```json
{
  "message": "Video pinned successfully",
  "keep_forever": true
}
```

**Error (403 Forbidden):**
```json
{
  "error": "This video is pinned. Unpin it first to delete.",
  "pinned": true
}
```

### Get Videos (Updated)
```http
GET /api/videos
```

**Response includes new fields:**
```json
{
  "videos": {
    "Channel Name": [
      {
        "video_id": "abc123",
        "title": "Video Title",
        "keep_forever": false,  // NEW: Pin status
        "channel_url": "https://youtube.com/@channel",  // NEW: For settings lookup
        // ... other existing fields
      }
    ]
  }
}
```

---

## Frontend Changes Needed

### 1. Update Video Card Rendering

**File:** `templates/index.html`
**Function:** `renderVideos(videosByChannel)` (around line 576)

**Current Structure:**
```html
<div class="video-item">
  <div class="video-title">{title}</div>
  <div class="video-meta">{size} • {date}</div>
  <button onclick="deleteVideo('{video_id}')">🗑️ Delete</button>
</div>
```

**Add Pin Button:**
```html
<div class="video-item" data-pinned="${video.keep_forever}">
  <div class="video-title">
    ${video.keep_forever ? '📌 ' : ''}${video.title}
  </div>
  <div class="video-meta">{size} • {date}</div>
  <div style="display: flex; gap: 8px;">
    <button
      class="secondary"
      onclick="togglePin('${video.video_id}', ${!video.keep_forever})"
      title="${video.keep_forever ? 'Unpin video' : 'Pin video (prevent cleanup)'}">
      ${video.keep_forever ? '📌 Unpin' : '📍 Pin'}
    </button>
    <button
      class="danger"
      onclick="deleteVideo('${video.video_id}')"
      ${video.keep_forever ? 'disabled title="Unpin first to delete"' : ''}>
      🗑️
    </button>
  </div>
</div>
```

**CSS for Pinned Videos (add to `<style>` section):**
```css
.video-item[data-pinned="true"] {
  border-left: 3px solid #4CAF50;
  background: linear-gradient(to right, rgba(76, 175, 80, 0.1), transparent);
}

.video-item[data-pinned="true"] .video-title {
  font-weight: 600;
}

button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

### 2. Add JavaScript Functions

**Location:** `<script>` section in `templates/index.html`

```javascript
async function togglePin(videoId, keepForever) {
  const action = keepForever ? 'pin' : 'unpin';
  const confirmMsg = keepForever
    ? 'Pin this video? It will be kept forever and added to Plex Keepers collection.'
    : 'Unpin this video? It may be deleted during cleanup.';

  if (!confirm(confirmMsg)) {
    return;
  }

  try {
    const response = await fetch(`/api/videos/${videoId}/pin`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keep_forever: keepForever })
    });

    const data = await response.json();

    if (response.ok) {
      alert(data.message);
      loadVideos(); // Refresh video list
    } else {
      alert('Error: ' + (data.error || 'Failed to ' + action + ' video'));
    }
  } catch (error) {
    console.error('Pin toggle error:', error);
    alert('Failed to ' + action + ' video');
  }
}
```

**Update deleteVideo function to handle pinned videos:**
```javascript
async function deleteVideo(videoId) {
  if (!confirm('Delete this video permanently?')) {
    return;
  }

  try {
    const response = await fetch(`/api/videos/${videoId}`, {
      method: 'DELETE'
    });

    const data = await response.json();

    if (response.ok) {
      alert(data.message);
      loadVideos();
    } else if (response.status === 403 && data.pinned) {
      // Video is pinned
      alert(data.error + '\n\nUnpin the video first if you want to delete it.');
    } else {
      alert('Error: ' + (data.error || 'Failed to delete video'));
    }
  } catch (error) {
    console.error('Delete error:', error);
    alert('Failed to delete video');
  }
}
```

---

## Testing Checklist

- [ ] Pin button appears on all videos
- [ ] Clicking "Pin" shows confirmation and pins video
- [ ] Pinned videos show 📌 icon in title
- [ ] Pinned videos have green border/highlight
- [ ] Delete button is disabled for pinned videos
- [ ] Clicking delete on pinned video shows appropriate error
- [ ] Unpinning removes visual indicators
- [ ] Video list refreshes after pin/unpin
- [ ] Plex "Keepers" collection updates (check Plex UI)

---

## Known Backend Behavior

1. **Automatic Cleanup:** Pinned videos are excluded from cleanup (already implemented)
2. **Plex Integration:** When video is pinned, it's added to "Keepers" collection if Plex is enabled
3. **Delete Protection:** API returns 403 Forbidden when trying to delete pinned video

---

## Implementation Notes

- Keep existing video card styling
- Use existing button classes (`secondary`, `danger`)
- Follow existing confirmation pattern (browser `confirm()` dialogs)
- Maintain existing error handling patterns
- Video list already fetches from `/api/videos` - no change needed, just use new fields
