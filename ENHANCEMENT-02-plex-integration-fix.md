# Enhancement #2: Fix Plex Integration

**Priority:** High
**Complexity:** Low
**Status:** Proposed

---

## Problem Statement

Plex integration is partially implemented but failing with:

```
WARNING: Failed to initialize Plex integration: Invalid library sectionID: 11
```

This prevents automatic thumbnail uploads to Plex after downloads complete.

---

## Current Behavior

**What Works:**
- Local thumbnail generation (`-poster.jpg` files created)
- Thumbnails saved alongside video files
- Plex-compatible naming structure

**What Doesn't Work:**
- Auto-upload thumbnails to Plex server
- Plex library refresh after new downloads
- Thumbnail sync shows `uploaded 0 thumbnails`

---

## Root Cause

**Configuration Issue:** `PLEX_LIBRARY_ID=11` in `.env` doesn't match actual YouTube library section ID on Plex server.

**Evidence:**
```python
# From app startup logs
self.plex = PlexIntegration(
    url=settings.plex_url,  # http://homeassistant.local:32400
    token=settings.plex_token,  # Valid token
    library_id=settings.plex_library_id,  # 11 (WRONG)
)
# Raises: Invalid library sectionID: 11
```

---

## Proposed Solution

### Step 1: Find Correct Library ID

**Method 1: Plex API**
```bash
# List all library sections
curl -X GET "http://homeassistant.local:32400/library/sections" \
  -H "X-Plex-Token: YOUR_TOKEN" | jq '.MediaContainer.Directory[] | {key, title, type}'

# Expected output:
# { "key": "1", "title": "Movies", "type": "movie" }
# { "key": "2", "title": "TV Shows", "type": "show" }
# { "key": "15", "title": "YouTube", "type": "movie" }  # <-- This one!
```

**Method 2: Plex Web UI**
1. Open Plex → Settings → Libraries
2. Click on YouTube library
3. URL will show: `/web/index.html#!/settings/server/.../library/sections/15`
4. The number (15) is the library ID

**Method 3: CLI Tool (Add to app)**
```python
# New CLI command: youtube-downloader plex-info
@cli.command()
def plex_info():
    """Show Plex library information."""
    plex = PlexServer(settings.plex_url, settings.plex_token)
    for section in plex.library.sections():
        print(f"ID: {section.key:3} | Type: {section.type:8} | Title: {section.title}")
```

### Step 2: Update Configuration

```bash
# .env
PLEX_LIBRARY_ID=15  # Update to correct ID (example)
```

### Step 3: Verify Integration

```python
# Test in Python console
from youtube_downloader.plex import PlexIntegration

plex = PlexIntegration(
    url="http://homeassistant.local:32400",
    token="YOUR_TOKEN",
    library_id="15"
)

# Should not raise exception
print(f"Connected to library: {plex.library.title}")
```

---

## Implementation Changes

### Add Validation on Startup

**In `plex.py`:**

```python
class PlexIntegration:
    def __init__(self, url: str, token: str, library_id: str):
        try:
            self.server = PlexServer(url, token)
            self.library = self.server.library.sectionByID(library_id)
            logger.info(f"Plex connected: {self.library.title} (ID: {library_id})")
        except NotFound:
            available = [
                f"{s.key}: {s.title} ({s.type})"
                for s in self.server.library.sections()
            ]
            logger.error(
                f"Invalid library ID {library_id}. Available libraries:\n" +
                "\n".join(available)
            )
            raise ValueError(f"Invalid Plex library ID: {library_id}")
```

### Add Plex Info Endpoint

**In `app.py`:**

```python
@app.route("/api/plex/libraries")
@auth.login_required
def get_plex_libraries():
    """List available Plex libraries for configuration."""
    if not settings.plex_enabled:
        return jsonify({"error": "Plex not configured"}), 400

    try:
        from plexapi.server import PlexServer
        plex = PlexServer(settings.plex_url, settings.plex_token)
        libraries = [
            {
                "id": section.key,
                "title": section.title,
                "type": section.type,
                "item_count": section.totalSize
            }
            for section in plex.library.sections()
        ]
        return jsonify({"libraries": libraries})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
```

### UI Enhancement

**Settings Modal - Plex Section:**

```html
<div class="form-group">
    <label>
        <input type="checkbox" id="plexEnabled"> Enable Plex Integration
    </label>
</div>

<div id="plexSettings" style="display: none;">
    <input type="url" id="plexUrl" placeholder="http://plex.local:32400">
    <input type="text" id="plexToken" placeholder="Plex Token">

    <label for="plexLibrary">YouTube Library:</label>
    <select id="plexLibrary">
        <option value="">-- Select Library --</option>
        <!-- Populated via /api/plex/libraries -->
    </select>

    <button onclick="refreshPlexLibraries()">🔄 Refresh Libraries</button>
    <button onclick="testPlexConnection()">🧪 Test Connection</button>
</div>
```

---

## Success Criteria

- [ ] Correct Plex library ID identified
- [ ] `.env` updated with correct ID
- [ ] Integration initializes without errors
- [ ] Thumbnails upload to Plex after download
- [ ] Plex library auto-refreshes after new content
- [ ] UI shows available Plex libraries in dropdown
- [ ] Test connection button validates config

---

## Testing Steps

1. **Find Library ID:**
   ```bash
   curl "http://homeassistant.local:32400/library/sections?X-Plex-Token=YOUR_TOKEN" | jq
   ```

2. **Update Config:**
   ```bash
   # .env
   PLEX_LIBRARY_ID=<correct_id>
   ```

3. **Restart App:**
   ```bash
   # Should see: "Plex connected: YouTube (ID: 15)"
   # Should NOT see: "Failed to initialize Plex integration"
   ```

4. **Test Thumbnail Sync:**
   - Download a channel
   - Check logs for: "Plex sync: uploaded N thumbnails"
   - Verify thumbnails appear in Plex web UI

5. **Test Library Refresh:**
   - Download new videos
   - Check Plex "Recently Added" shows new content
   - Verify metadata (title, date) is correct

---

## Migration Notes

**Existing Users:**
- Update `.env` with correct library ID
- No code changes needed (just config)
- Existing thumbnails will be synced on next download

**New Users:**
- UI will show library dropdown for easy selection
- Auto-detect YouTube library if only one movie library exists
- Fallback to manual ID entry if auto-detection fails

---

## Documentation Updates

**README.md - Plex Setup:**

```markdown
### Plex Integration (Optional)

1. Create a YouTube library in Plex (type: Movies)
2. Get your Plex token: https://support.plex.tv/articles/204059436/
3. Find your library ID:
   ```bash
   curl "http://plex.local:32400/library/sections?X-Plex-Token=YOUR_TOKEN" | jq
   ```
4. Update `.env`:
   ```
   PLEX_ENABLED=true
   PLEX_URL=http://plex.local:32400
   PLEX_TOKEN=your-token-here
   PLEX_LIBRARY_ID=15  # Your YouTube library ID
   ```
```

---

**Estimated Effort:** 1-2 hours
**Risk:** Low (config fix, existing code works)
**Value:** High (completes Plex workflow)
