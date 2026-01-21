# Enhancement #6: Webhook System

**Priority:** Medium
**Complexity:** Medium
**Status:** Proposed

---

## Problem Statement

No way to integrate with external systems automatically:
- Plex library refresh is manual (or relies on Plex scanning)
- Home Assistant automations can't react to download events
- Custom scripts can't trigger on completion
- No CI/CD integration for testing

---

## Proposed Solution

Flexible webhook system that POSTs JSON payloads to configured URLs on specific events.

---

## Supported Events

| Event | Trigger | Payload |
|-------|---------|---------|
| `download.started` | Channel download begins | channel_url, download_id |
| `download.completed` | Download succeeds | channel_url, video_count, size_mb |
| `download.failed` | Download fails after retries | channel_url, error_message |
| `download.progress` | Download progress update (optional) | download_id, progress_percent |
| `video.added` | New video added to library | video_id, title, channel |
| `video.deleted` | Video deleted from library | video_id, title, channel |
| `queue.empty` | Download queue is empty | queue_stats |
| `storage.warning` | Storage threshold reached | used_gb, total_gb, percent |

---

## Configuration

### .env Settings

```bash
# Webhook Configuration
WEBHOOKS_ENABLED=true

# Define webhooks (comma-separated list of webhook IDs)
WEBHOOK_IDS=plex_refresh,home_assistant,custom

# Webhook 1: Plex Library Refresh
WEBHOOK_plex_refresh_URL=http://homeassistant.local:32400/library/sections/15/refresh
WEBHOOK_plex_refresh_METHOD=GET
WEBHOOK_plex_refresh_EVENTS=download.completed
WEBHOOK_plex_refresh_HEADERS=X-Plex-Token:YOUR_TOKEN

# Webhook 2: Home Assistant
WEBHOOK_home_assistant_URL=http://homeassistant.local:8123/api/webhook/youtube_download
WEBHOOK_home_assistant_METHOD=POST
WEBHOOK_home_assistant_EVENTS=download.completed,download.failed
WEBHOOK_home_assistant_HEADERS=Authorization:Bearer YOUR_HA_TOKEN,Content-Type:application/json

# Webhook 3: Custom Script
WEBHOOK_custom_URL=http://10.71.1.100:8000/youtube-event
WEBHOOK_custom_METHOD=POST
WEBHOOK_custom_EVENTS=*  # All events
WEBHOOK_custom_TIMEOUT=10
WEBHOOK_custom_RETRY_COUNT=3
```

### Alternative: Database Configuration

Store webhooks in database for dynamic management via UI.

```sql
CREATE TABLE IF NOT EXISTS webhooks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    method TEXT DEFAULT 'POST',
    events TEXT NOT NULL,  -- Comma-separated or '*' for all
    headers TEXT,  -- JSON object
    enabled BOOLEAN DEFAULT 1,
    timeout INTEGER DEFAULT 10,
    retry_count INTEGER DEFAULT 1,
    created_at REAL DEFAULT (strftime('%s', 'now'))
);
```

---

## Payload Format

### Standard Payload Structure

All webhooks receive:

```json
{
  "event": "download.completed",
  "timestamp": 1737487200,
  "source": "youtube-downloader",
  "version": "1.0.0",
  "data": {
    // Event-specific data
  }
}
```

### Event-Specific Payloads

**`download.started`:**
```json
{
  "event": "download.started",
  "timestamp": 1737487200,
  "data": {
    "download_id": "abc-123",
    "channel_url": "https://youtube.com/@JoshJohnsonComedy",
    "channel_name": "JoshJohnsonComedy",
    "video_limit": 3
  }
}
```

**`download.completed`:**
```json
{
  "event": "download.completed",
  "timestamp": 1737487335,
  "data": {
    "download_id": "abc-123",
    "channel_url": "https://youtube.com/@JoshJohnsonComedy",
    "channel_name": "JoshJohnsonComedy",
    "video_count": 3,
    "size_mb": 450.5,
    "duration_seconds": 135,
    "videos": [
      {
        "video_id": "dQw4w9WgXcQ",
        "title": "Example Video",
        "file_path": "/path/to/video.mp4",
        "size_mb": 150.2
      }
    ]
  }
}
```

**`download.failed`:**
```json
{
  "event": "download.failed",
  "timestamp": 1737487400,
  "data": {
    "download_id": "abc-123",
    "channel_url": "https://youtube.com/@Example",
    "channel_name": "Example",
    "error_message": "Members-only content (skipped)",
    "retry_count": 3
  }
}
```

**`video.added`:**
```json
{
  "event": "video.added",
  "timestamp": 1737487335,
  "data": {
    "video_id": "dQw4w9WgXcQ",
    "title": "Example Video",
    "channel_name": "JoshJohnsonComedy",
    "channel_url": "https://youtube.com/@JoshJohnsonComedy",
    "file_path": "/path/to/video.mp4",
    "size_mb": 150.2,
    "upload_date": "2026-01-20"
  }
}
```

**`storage.warning`:**
```json
{
  "event": "storage.warning",
  "timestamp": 1737487500,
  "data": {
    "used_gb": 450.2,
    "total_gb": 500.0,
    "percent_used": 90.0,
    "threshold": 90,
    "available_gb": 49.8
  }
}
```

---

## Implementation

### Webhook Manager

**New Module:** `src/youtube_downloader/webhooks.py`

```python
import json
import threading
from dataclasses import dataclass
from typing import Any, Optional
import requests
from loguru import logger

@dataclass
class WebhookConfig:
    id: str
    name: str
    url: str
    method: str = "POST"
    events: list[str] = None
    headers: dict[str, str] = None
    enabled: bool = True
    timeout: int = 10
    retry_count: int = 1

    def matches_event(self, event: str) -> bool:
        """Check if this webhook should fire for an event."""
        if not self.enabled:
            return False
        if not self.events or '*' in self.events:
            return True
        return event in self.events

class WebhookManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.webhooks: list[WebhookConfig] = []
        self._load_webhooks()

    def _load_webhooks(self) -> None:
        """Load webhook configurations from settings."""
        # Parse WEBHOOK_IDS and build WebhookConfig objects from .env
        # OR load from database if using DB storage

    def trigger(
        self,
        event: str,
        data: dict[str, Any],
        async_mode: bool = True
    ) -> None:
        """Trigger webhooks for an event.

        Args:
            event: Event name (e.g., "download.completed")
            data: Event-specific data
            async_mode: Run webhooks in background thread (default: True)
        """
        matching_webhooks = [
            wh for wh in self.webhooks
            if wh.matches_event(event)
        ]

        if not matching_webhooks:
            logger.debug(f"No webhooks configured for event: {event}")
            return

        logger.info(f"Triggering {len(matching_webhooks)} webhooks for event: {event}")

        payload = {
            "event": event,
            "timestamp": int(time.time()),
            "source": "youtube-downloader",
            "version": "1.0.0",
            "data": data
        }

        for webhook in matching_webhooks:
            if async_mode:
                threading.Thread(
                    target=self._execute_webhook,
                    args=(webhook, payload),
                    daemon=True
                ).start()
            else:
                self._execute_webhook(webhook, payload)

    def _execute_webhook(
        self,
        webhook: WebhookConfig,
        payload: dict[str, Any]
    ) -> None:
        """Execute a single webhook with retries."""
        for attempt in range(webhook.retry_count):
            try:
                if webhook.method.upper() == "GET":
                    # For GET requests (like Plex refresh), add payload as query params
                    response = requests.get(
                        webhook.url,
                        headers=webhook.headers,
                        timeout=webhook.timeout
                    )
                else:
                    # POST/PUT with JSON body
                    response = requests.request(
                        method=webhook.method,
                        url=webhook.url,
                        json=payload,
                        headers=webhook.headers,
                        timeout=webhook.timeout
                    )

                response.raise_for_status()

                logger.info(
                    f"Webhook '{webhook.name}' succeeded: {webhook.url} "
                    f"(status: {response.status_code})"
                )
                return  # Success, exit retry loop

            except requests.exceptions.RequestException as e:
                logger.warning(
                    f"Webhook '{webhook.name}' failed (attempt {attempt + 1}/{webhook.retry_count}): {e}"
                )
                if attempt < webhook.retry_count - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    logger.error(
                        f"Webhook '{webhook.name}' failed after {webhook.retry_count} attempts"
                    )

    def test_webhook(self, webhook_id: str) -> dict:
        """Send a test event to a webhook."""
        webhook = next((wh for wh in self.webhooks if wh.id == webhook_id), None)
        if not webhook:
            return {"error": "Webhook not found"}

        test_payload = {
            "event": "test",
            "timestamp": int(time.time()),
            "source": "youtube-downloader",
            "version": "1.0.0",
            "data": {
                "message": "This is a test webhook"
            }
        }

        try:
            self._execute_webhook(webhook, test_payload)
            return {"success": True, "message": "Test webhook sent"}
        except Exception as e:
            return {"success": False, "error": str(e)}
```

---

## Integration Points

### In Download Manager

**In `downloader.py`:**

```python
class DownloadManager:
    def __init__(self, settings: Settings, database: Optional["Database"] = None):
        # ... existing init ...
        self.webhook_manager = WebhookManager(settings) if settings.webhooks_enabled else None

    def _download_channel(self, channel_url: str, download_id: str) -> None:
        # ... existing code ...

        # Trigger download started webhook
        if self.webhook_manager:
            self.webhook_manager.trigger("download.started", {
                "download_id": download_id,
                "channel_url": channel_url,
                "channel_name": channel_name,
                "video_limit": self.settings.videos_per_channel
            })

        try:
            # ... download logic ...

            # Success - trigger completion webhook
            if self.webhook_manager:
                self.webhook_manager.trigger("download.completed", {
                    "download_id": download_id,
                    "channel_url": channel_url,
                    "channel_name": channel_name,
                    "video_count": downloaded_count,
                    "size_mb": total_size_mb,
                    "duration_seconds": int(time() - start_time)
                })

        except Exception as e:
            # Failure - trigger failed webhook
            if self.webhook_manager:
                self.webhook_manager.trigger("download.failed", {
                    "download_id": download_id,
                    "channel_url": channel_url,
                    "channel_name": channel_name,
                    "error_message": str(e),
                    "retry_count": attempt
                })
```

### In Database (Video Operations)

**In `database.py`:**

```python
def add_video(self, ...) -> None:
    # ... insert video ...

    # Trigger video added webhook
    if self.webhook_manager:
        self.webhook_manager.trigger("video.added", {
            "video_id": video_id,
            "title": title,
            "channel_name": channel_name,
            "channel_url": channel_url,
            "file_path": file_path,
            "size_mb": file_size / 1024 / 1024
        })

def delete_video(self, video_id: str, delete_file: bool = False) -> None:
    # Get video info before deletion
    video = self.get_video_by_id(video_id)

    # ... delete video ...

    # Trigger video deleted webhook
    if self.webhook_manager:
        self.webhook_manager.trigger("video.deleted", {
            "video_id": video_id,
            "title": video.title,
            "channel_name": video.channel_name
        })
```

---

## UI Management

### Webhook Settings Section

**Settings Modal:**

```html
<div style="background: #1f2a1f; padding: 20px; border-radius: 8px;">
    <h3 style="color: #4CAF50;">🔗 Webhooks</h3>

    <div id="webhooksList"></div>

    <button onclick="addWebhook()" class="secondary">+ Add Webhook</button>
</div>

<!-- Add/Edit Webhook Modal -->
<div class="modal-overlay" id="webhookModal">
    <div class="modal">
        <h2>Add Webhook</h2>

        <div class="form-group">
            <label for="webhookName">Name</label>
            <input type="text" id="webhookName" placeholder="Plex Library Refresh">
        </div>

        <div class="form-group">
            <label for="webhookUrl">URL</label>
            <input type="url" id="webhookUrl" placeholder="http://plex.local:32400/...">
        </div>

        <div class="form-group">
            <label for="webhookMethod">Method</label>
            <select id="webhookMethod">
                <option value="POST">POST</option>
                <option value="GET">GET</option>
                <option value="PUT">PUT</option>
            </select>
        </div>

        <div class="form-group">
            <label>Events (select which events trigger this webhook):</label>
            <label><input type="checkbox" value="download.completed"> Download Completed</label>
            <label><input type="checkbox" value="download.failed"> Download Failed</label>
            <label><input type="checkbox" value="video.added"> Video Added</label>
            <label><input type="checkbox" value="*"> All Events</label>
        </div>

        <div class="form-group">
            <label for="webhookHeaders">Headers (JSON)</label>
            <textarea id="webhookHeaders" rows="3" placeholder='{"Authorization": "Bearer token"}'></textarea>
        </div>

        <button onclick="testWebhook()">🧪 Test Webhook</button>

        <div class="modal-buttons">
            <button type="button" class="outline" onclick="closeWebhookModal()">Cancel</button>
            <button type="button" onclick="saveWebhook()">Save Webhook</button>
        </div>
    </div>
</div>
```

### API Endpoints

```python
@app.route("/api/webhooks", methods=["GET"])
@auth.login_required
def get_webhooks():
    """List all configured webhooks."""
    return jsonify({"webhooks": [wh.__dict__ for wh in webhook_manager.webhooks]})

@app.route("/api/webhooks", methods=["POST"])
@auth.login_required
def add_webhook():
    """Add a new webhook."""
    # Create webhook from request data
    # Save to database or .env
    return jsonify({"message": "Webhook added"})

@app.route("/api/webhooks/<webhook_id>/test", methods=["POST"])
@auth.login_required
def test_webhook(webhook_id: str):
    """Send test event to webhook."""
    result = webhook_manager.test_webhook(webhook_id)
    return jsonify(result)
```

---

## Use Cases

### Use Case 1: Plex Library Auto-Refresh

```bash
# .env
WEBHOOK_plex_URL=http://homeassistant.local:32400/library/sections/15/refresh
WEBHOOK_plex_METHOD=GET
WEBHOOK_plex_EVENTS=download.completed
WEBHOOK_plex_HEADERS=X-Plex-Token:YOUR_PLEX_TOKEN
```

**Result:** Plex library refreshes automatically after each download.

### Use Case 2: Home Assistant Automation

```yaml
# Home Assistant automation.yaml
automation:
  - alias: "YouTube Download Notification"
    trigger:
      - platform: webhook
        webhook_id: youtube_download
    condition:
      - condition: template
        value_template: "{{ trigger.json.event == 'download.completed' }}"
    action:
      - service: notify.mobile_app
        data:
          title: "YouTube Download"
          message: "Downloaded {{ trigger.json.data.video_count }} videos from {{ trigger.json.data.channel_name }}"
```

### Use Case 3: Custom Script Integration

**Webhook triggers custom Python script:**

```python
# webhook_receiver.py
from flask import Flask, request

app = Flask(__name__)

@app.route("/youtube-event", methods=["POST"])
def handle_event():
    data = request.json
    event = data["event"]

    if event == "download.completed":
        # Custom logic: transcode videos, update database, send notifications
        channel = data["data"]["channel_name"]
        videos = data["data"]["video_count"]
        print(f"Downloaded {videos} videos from {channel}")

    return {"status": "ok"}
```

---

## Success Criteria

- [ ] Webhooks trigger on correct events
- [ ] Payloads contain accurate data
- [ ] Retry logic works for transient failures
- [ ] GET and POST methods supported
- [ ] Headers passed correctly
- [ ] Test webhook button works
- [ ] Webhooks run asynchronously (don't block downloads)
- [ ] Failed webhooks logged but don't crash app
- [ ] UI shows webhook status (success/failed)
- [ ] Multiple webhooks can trigger for same event

---

## Future Enhancements

- Webhook history/logs (see past executions)
- Conditional webhooks (only fire if X condition met)
- Webhook templates (pre-configured for Plex, HA, etc.)
- Webhook payload customization (user-defined JSON)
- Rate limiting (max N webhooks per minute)
- Signature verification (HMAC for security)
- Bi-directional webhooks (receive commands via webhook)

---

**Estimated Effort:** 8-10 hours
**Risk:** Low (isolated feature, optional)
**Value:** High (enables automation and integrations)
