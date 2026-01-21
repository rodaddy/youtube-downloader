# Enhancement #1: Notification System

**Priority:** High
**Complexity:** Low
**Status:** Proposed

---

## Problem Statement

Users have no visibility into download completion or failures without manually checking the web UI or logs. For automated workflows (scheduler running every 2 hours), it's critical to know when:

- Downloads complete successfully
- Downloads fail persistently after retries
- Storage is running low
- Queue is backing up

---

## Proposed Solution

Multi-channel notification system supporting Discord, Email, and Pushover with configurable triggers.

### Notification Triggers

| Trigger | Priority | Example Message |
|---------|----------|-----------------|
| Download Success | Low | ✅ Downloaded 3 videos from JoshJohnsonComedy |
| Download Failure | High | ❌ JoshJohnsonComedy failed after 3 retries: Members-only content |
| Daily Summary | Medium | 📊 Daily Summary: 15 videos downloaded, 2 failures, 1.2GB used |
| Storage Warning | High | ⚠️ Storage 90% full (450GB / 500GB) |
| Queue Backup | Medium | 📥 Queue backed up: 10 channels waiting |

---

## Technical Design

### Configuration (.env additions)

```bash
# Notification Settings
NOTIFICATIONS_ENABLED=true

# Discord
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_NOTIFY_ON=success,failure,daily_summary  # Comma-separated

# Email (SMTP)
EMAIL_ENABLED=false
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
EMAIL_FROM=youtube-downloader@yourdomain.com
EMAIL_TO=you@example.com
EMAIL_NOTIFY_ON=failure,daily_summary

# Pushover
PUSHOVER_ENABLED=false
PUSHOVER_USER_KEY=your-user-key
PUSHOVER_API_TOKEN=your-api-token
PUSHOVER_NOTIFY_ON=failure
```

### Implementation

**New Module:** `src/youtube_downloader/notifications.py`

```python
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class NotificationLevel(Enum):
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    INFO = "info"

@dataclass
class Notification:
    level: NotificationLevel
    title: str
    message: str
    channel_name: Optional[str] = None
    video_count: Optional[int] = None

class NotificationManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.discord = DiscordNotifier(settings) if settings.discord_enabled else None
        self.email = EmailNotifier(settings) if settings.email_enabled else None
        self.pushover = PushoverNotifier(settings) if settings.pushover_enabled else None

    def send(self, notification: Notification) -> None:
        """Send notification to all enabled channels."""
        # Check if this trigger is enabled for each channel
        # Send to enabled channels

class DiscordNotifier:
    def send(self, notification: Notification) -> None:
        # POST to Discord webhook with embed

class EmailNotifier:
    def send(self, notification: Notification) -> None:
        # Send via SMTP

class PushoverNotifier:
    def send(self, notification: Notification) -> None:
        # POST to Pushover API
```

### Integration Points

**In `downloader.py`:**

```python
# After successful download
if self.notification_manager:
    self.notification_manager.send(Notification(
        level=NotificationLevel.SUCCESS,
        title="Download Complete",
        message=f"Downloaded {video_count} videos from {channel_name}",
        channel_name=channel_name,
        video_count=video_count
    ))

# After permanent failure
if self.notification_manager:
    self.notification_manager.send(Notification(
        level=NotificationLevel.ERROR,
        title="Download Failed",
        message=f"{channel_name} failed: {error_msg}",
        channel_name=channel_name
    ))
```

**In `scheduler.py`:**

```python
# Daily summary (scheduled task)
def send_daily_summary():
    stats = database.get_daily_stats()
    notification_manager.send(Notification(
        level=NotificationLevel.INFO,
        title="Daily Summary",
        message=f"Downloaded {stats.videos} videos, {stats.failures} failures, {stats.size_gb}GB used"
    ))
```

---

## UI Changes

**Settings Modal - New Section:**

```html
<div style="background: #1f2a1f; padding: 20px; border-radius: 8px;">
    <h3 style="color: #4CAF50;">🔔 Notifications</h3>

    <div class="form-group">
        <label>
            <input type="checkbox" id="discordEnabled"> Enable Discord Notifications
        </label>
        <input type="url" id="discordWebhook" placeholder="Discord Webhook URL">
    </div>

    <div class="form-group">
        <label>Notify On:</label>
        <label><input type="checkbox" value="success"> Successful downloads</label>
        <label><input type="checkbox" value="failure"> Failed downloads</label>
        <label><input type="checkbox" value="daily_summary"> Daily summary</label>
    </div>

    <button onclick="testNotification()">🧪 Send Test Notification</button>
</div>
```

**New API Endpoint:**

```python
@app.route("/api/notifications/test", methods=["POST"])
@auth.login_required
def test_notification():
    """Send a test notification to verify configuration."""
    notification_manager.send(Notification(
        level=NotificationLevel.INFO,
        title="Test Notification",
        message="If you're seeing this, notifications are working!"
    ))
    return jsonify({"message": "Test notification sent"})
```

---

## Dependencies

```toml
# pyproject.toml additions
dependencies = [
    # ... existing
    "requests>=2.31.0",  # For Discord/Pushover webhooks
]
```

**Note:** Email uses stdlib `smtplib`, no additional deps.

---

## Success Criteria

- [ ] Discord webhook notifications working
- [ ] Email notifications via SMTP working
- [ ] Pushover notifications working
- [ ] Configurable triggers (success, failure, daily summary)
- [ ] Test notification button in UI
- [ ] Settings persist across restarts
- [ ] Graceful failure (if notification fails, app continues)
- [ ] Rate limiting (don't spam on bulk operations)

---

## Implementation Notes

### Phase 1: Discord Only (Simplest)
- Single webhook URL
- POST JSON with embed
- Test with success/failure notifications

### Phase 2: Email Support
- SMTP configuration
- HTML email templates
- Attachment support (logs)

### Phase 3: Pushover + Advanced Features
- Pushover API integration
- Priority levels
- Daily summary scheduler

### Error Handling
- Catch exceptions from notification services
- Log failures but don't break downloads
- Retry with exponential backoff for transient failures
- Disable channel after 5 consecutive failures

### Rate Limiting
- Max 1 notification per channel per 5 minutes
- Batch multiple downloads into single summary if rapid succession
- Daily summary only once per day (configurable time)

---

## Alternative: Notifiarr Integration

**Instead of building custom notification integrations, consider Notifiarr (https://notifiarr.com/):**

### What is Notifiarr?

Unified notification service that integrates with *arr apps, Plex, and provides:
- Discord bot interface
- Multiple notification channels (Discord, Telegram, Pushover, Email, etc.)
- Request system
- Centralized management

### Integration Approach

**Option 1: Use Webhook System (Enhancement #6)**
- Configure webhook to POST to Notifiarr API endpoint
- Notifiarr handles routing to Discord/Telegram/etc.
- Simpler implementation (no custom notification code)

**Option 2: Native Notifiarr API**
- Direct integration with Notifiarr API
- More control over notification format
- Requires API key and setup

### Configuration Example

```bash
# .env - Use Notifiarr via webhook
WEBHOOK_notifiarr_URL=https://notifiarr.com/api/v1/notification/youtube-downloader
WEBHOOK_notifiarr_METHOD=POST
WEBHOOK_notifiarr_EVENTS=download.completed,download.failed
WEBHOOK_notifiarr_HEADERS=X-API-Key:YOUR_NOTIFIARR_KEY,Content-Type:application/json
```

**Notifiarr Payload:**
```json
{
  "event": "youtube_download",
  "title": "Download Complete",
  "message": "Downloaded 3 videos from JoshJohnsonComedy",
  "priority": "normal",
  "channels": ["discord", "telegram"]
}
```

### Recommendation

Use **Notifiarr + Webhook System** instead of building custom notification integrations:
- ✅ Leverage existing infrastructure
- ✅ Centralized notification management
- ✅ Supports multiple channels without custom code
- ✅ Already familiar if using *arr stack

**Implementation Priority:**
1. Build Webhook System (Enhancement #6) - Foundation for all integrations
2. Configure Notifiarr webhook - Notifications via existing service
3. Skip custom Discord/Email/Pushover code - Use Notifiarr instead

---

## Future Enhancements

- Telegram bot integration (native)
- Slack webhooks (native)
- Custom webhook format (generic POST)
- Notification history in UI
- Per-channel notification preferences
- Notification sound/vibration settings (mobile)

---

**Estimated Effort:** 2-4 hours (with Notifiarr) OR 6-8 hours (custom integrations)
**Risk:** Low (isolated feature, optional)
**Value:** High (monitoring automation)

**Updated Recommendation:** Implement Webhook System first, then use Notifiarr for notifications.
