# Per-Channel Video Limits UI Specification

## Status: Backend Complete ✅ | Frontend Pending ⏳

## Overview
Allow setting custom video limits per channel instead of using the global default (3 videos).

---

## Backend API (Already Implemented)

### Get Channel Settings
```http
GET /api/channels/<channel_url>/settings
```

**Example:**
```http
GET /api/channels/https%3A%2F%2Fwww.youtube.com%2F%40channelname/settings
```

**Response:**
```json
{
  "channel_url": "https://www.youtube.com/@channelname",
  "video_limit": 5,           // Custom limit (if set)
  "using_default": false,     // false if custom, true if using global
  "default_limit": 3          // Global default from settings
}
```

**Response (Using Default):**
```json
{
  "channel_url": "https://www.youtube.com/@channelname",
  "video_limit": null,        // No custom limit
  "using_default": true,
  "default_limit": 3
}
```

### Update Channel Settings
```http
PUT /api/channels/<channel_url>/settings
Content-Type: application/json

{
  "video_limit": 10  // Set custom limit
}
```

**Response:**
```json
{
  "message": "Channel settings updated",
  "channel_url": "https://www.youtube.com/@channelname",
  "video_limit": 10
}
```

### Revert to Default
```http
PUT /api/channels/<channel_url>/settings
Content-Type: application/json

{
  "video_limit": null  // Remove custom limit
}
```

**Response:**
```json
{
  "message": "Reverted to default limit",
  "channel_url": "https://www.youtube.com/@channelname",
  "video_limit": 3  // Global default
}
```

---

## Frontend Changes Needed

### 1. Update Channel Card Rendering

**File:** `templates/index.html`
**Function:** `renderChannels()` (around line 435)

**Current Structure:**
```html
<div class="channel-card">
  <div class="channel-name">{name}</div>
  <div style="display: flex; gap: 8px;">
    <button onclick="downloadChannel('{url}')">Download Latest</button>
    <button class="danger" onclick="removeChannel('{url}')">🗑️</button>
  </div>
</div>
```

**Add Settings Icon:**
```html
<div class="channel-card">
  <div class="channel-name">{name}</div>
  <div style="display: flex; gap: 8px;">
    <button onclick="downloadChannel('{url}')" style="flex: 1;">
      Download Latest
    </button>
    <button
      class="secondary"
      onclick="openChannelSettings('${escapeHtml(url)}')"
      title="Channel settings">
      ⚙️
    </button>
    <button
      class="danger"
      onclick="removeChannel('${escapeHtml(url)}')"
      title="Remove channel">
      🗑️
    </button>
  </div>
</div>
```

### 2. Add Channel Settings Modal

**Location:** After existing modals in `templates/index.html`

```html
<!-- Channel Settings Modal -->
<div class="modal-overlay" id="channelSettingsModal" onclick="closeChannelSettingsOnOverlay(event)">
  <div class="modal">
    <h2>⚙️ Channel Settings</h2>
    <p id="channelSettingsName" style="color: #888; font-size: 14px; margin-bottom: 20px;"></p>

    <form id="channelSettingsForm" onsubmit="saveChannelSettings(event)">
      <div class="form-group">
        <label for="channelVideoLimit">Videos to Keep</label>
        <div style="display: flex; gap: 10px; align-items: center;">
          <input
            type="number"
            id="channelVideoLimit"
            min="1"
            max="100"
            placeholder="3"
            style="flex: 1;">
          <button
            type="button"
            class="secondary"
            onclick="useDefaultLimit()"
            title="Use global default">
            Use Default (3)
          </button>
        </div>
        <div style="font-size: 11px; color: #888; margin-top: 5px;">
          Leave empty or click "Use Default" to use the global setting (currently 3 videos per channel).
          Set a custom number to override for this channel only.
        </div>
      </div>

      <div style="background: #2a2a2a; padding: 15px; border-radius: 6px; margin-top: 20px;">
        <div style="font-size: 12px; color: #888; margin-bottom: 5px;">Current Status:</div>
        <div id="channelLimitStatus" style="font-size: 13px; color: #aaa;"></div>
      </div>

      <div class="modal-buttons" style="margin-top: 20px;">
        <button type="button" class="outline" onclick="closeChannelSettings()">Cancel</button>
        <button type="submit">Save Settings</button>
      </div>
    </form>
  </div>
</div>
```

### 3. Add JavaScript Functions

**Location:** `<script>` section in `templates/index.html`

```javascript
// Global variable to track current channel being configured
let currentChannelUrl = null;

async function openChannelSettings(channelUrl) {
  currentChannelUrl = channelUrl;

  // Extract channel name from URL
  const channelName = channelUrl.split('@')[1] || channelUrl.split('/').pop();
  document.getElementById('channelSettingsName').textContent = `Channel: ${channelName}`;

  // Fetch current settings
  try {
    const encodedUrl = encodeURIComponent(channelUrl);
    const response = await fetch(`/api/channels/${encodedUrl}/settings`);
    const data = await response.json();

    // Populate form
    const limitInput = document.getElementById('channelVideoLimit');
    if (data.using_default) {
      limitInput.value = '';
      limitInput.placeholder = data.default_limit;
    } else {
      limitInput.value = data.video_limit;
      limitInput.placeholder = data.default_limit;
    }

    // Update status display
    updateChannelLimitStatus(data);

    // Show modal
    document.getElementById('channelSettingsModal').classList.add('active');

  } catch (error) {
    console.error('Error loading channel settings:', error);
    alert('Failed to load channel settings');
  }
}

function closeChannelSettings() {
  document.getElementById('channelSettingsModal').classList.remove('active');
  currentChannelUrl = null;
}

function closeChannelSettingsOnOverlay(event) {
  if (event.target.id === 'channelSettingsModal') {
    closeChannelSettings();
  }
}

function useDefaultLimit() {
  const limitInput = document.getElementById('channelVideoLimit');
  limitInput.value = '';
}

function updateChannelLimitStatus(data) {
  const statusDiv = document.getElementById('channelLimitStatus');

  if (data.using_default) {
    statusDiv.innerHTML = `
      Using global default: <strong style="color: #4CAF50;">${data.default_limit} videos</strong>
    `;
  } else {
    statusDiv.innerHTML = `
      Custom limit: <strong style="color: #2196F3;">${data.video_limit} videos</strong>
      <span style="color: #888;">(global default: ${data.default_limit})</span>
    `;
  }
}

async function saveChannelSettings(event) {
  event.preventDefault();

  if (!currentChannelUrl) {
    return;
  }

  const limitInput = document.getElementById('channelVideoLimit');
  const limitValue = limitInput.value.trim();

  // Prepare request body
  const requestBody = {
    video_limit: limitValue === '' ? null : parseInt(limitValue, 10)
  };

  try {
    const encodedUrl = encodeURIComponent(currentChannelUrl);
    const response = await fetch(`/api/channels/${encodedUrl}/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody)
    });

    const data = await response.json();

    if (response.ok) {
      alert(data.message);
      closeChannelSettings();
    } else {
      alert('Error: ' + (data.error || 'Failed to save settings'));
    }
  } catch (error) {
    console.error('Save error:', error);
    alert('Failed to save channel settings');
  }
}
```

---

## Testing Checklist

- [ ] Settings icon (⚙️) appears on all channel cards
- [ ] Clicking settings opens modal with channel name
- [ ] Modal shows current limit status (default vs custom)
- [ ] Input placeholder shows global default
- [ ] "Use Default" button clears custom limit
- [ ] Saving custom limit updates status display
- [ ] Saving null/empty reverts to default
- [ ] Modal closes after successful save
- [ ] Error handling works for invalid limits
- [ ] Custom limits persist across page refreshes
- [ ] Cleanup respects per-channel limits

---

## Implementation Notes

- URL encoding is critical (use `encodeURIComponent()`)
- Reuse existing modal styles and patterns
- Follow existing form validation patterns
- Test with YouTube URLs containing special characters (@, /, etc.)
- Per-channel limits only affect automatic cleanup, not manual downloads
