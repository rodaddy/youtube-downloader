# YouTube Downloader - Enhancement Roadmap

**Created:** 2026-01-21
**Status:** Proposed

---

## Overview

This document summarizes all proposed enhancements with priorities, effort estimates, and implementation dependencies.

---

## Enhancement List

| # | Enhancement | Priority | Complexity | Effort | Value | Status |
|---|-------------|----------|------------|--------|-------|--------|
| 1 | [Notifications](#1-notifications) | High | Low | 2-4h | High | Proposed |
| 2 | [Fix Plex Integration](#2-fix-plex-integration) | High | Low | 1-2h | High | Proposed |
| 3 | [Download History Dashboard](#3-download-history-dashboard) | Medium | Low | 6-8h | High | Proposed |
| 4 | [Per-Channel Settings](#4-per-channel-settings) | Medium | Low | 6-8h | High | Proposed |
| 5 | [Bulk Operations](#5-bulk-operations) | Low | Low | 6-8h | Medium | Proposed |
| 6 | [Webhook System](#6-webhook-system) | Medium | Medium | 8-10h | High | Proposed |

**Total Estimated Effort:** 30-42 hours

---

## Enhancement Details

### 1. Notifications

**File:** [ENHANCEMENT-01-notifications.md](./ENHANCEMENT-01-notifications.md)

**What:** Multi-channel notification system (Discord, Email, Pushover) OR Notifiarr integration

**Why:** Automated monitoring - know when downloads complete or fail without checking UI

**Key Features:**
- Download success/failure notifications
- Daily summary reports
- Storage warnings
- **Recommended:** Use Notifiarr instead of custom integrations

**Dependencies:**
- Enhancement #6 (Webhook System) - Use webhooks to trigger Notifiarr

**Estimated Effort:** 2-4 hours (with Notifiarr) OR 6-8 hours (custom)

---

### 2. Fix Plex Integration

**File:** [ENHANCEMENT-02-plex-integration-fix.md](./ENHANCEMENT-02-plex-integration-fix.md)

**What:** Fix current Plex integration error (invalid library ID)

**Why:** Complete existing feature - auto-upload thumbnails to Plex

**Key Features:**
- Identify correct Plex library ID
- UI to select Plex library from dropdown
- Test connection button
- Auto-refresh Plex library after downloads

**Dependencies:** None (standalone fix)

**Estimated Effort:** 1-2 hours

**Impact:** Quick win - feature already coded, just needs config fix

---

### 3. Download History Dashboard

**File:** [ENHANCEMENT-03-download-history-dashboard.md](./ENHANCEMENT-03-download-history-dashboard.md)

**What:** Historical download tracking with stats and retry functionality

**Why:** Visibility into past downloads, troubleshooting, trends

**Key Features:**
- Download history table (success/failed/partial)
- Stats cards (success rate, total size, etc.)
- Filter by status, date, channel
- Retry failed downloads
- View logs for specific download

**Dependencies:** None

**Estimated Effort:** 6-8 hours

---

### 4. Per-Channel Settings

**File:** [ENHANCEMENT-04-per-channel-settings.md](./ENHANCEMENT-04-per-channel-settings.md)

**What:** Customize settings per channel (video limit, quality, schedule)

**Why:** Different channels need different treatment (news vs premium vs podcasts)

**Key Features:**
- Per-channel video limits
- Quality profiles (4K, 1080p, 720p, audio-only)
- Download frequency (hourly, daily, weekly, manual)
- Priority ordering
- Enable/disable channels

**Dependencies:**
- Database schema updates (already has partial support)

**Estimated Effort:** 6-8 hours

**Use Cases:**
- News channels: 10+ videos, 720p, daily
- Premium creators: 5 videos, 4K, weekly
- Podcasts: 20 audio-only, weekly

---

### 5. Bulk Operations

**File:** [ENHANCEMENT-05-bulk-operations.md](./ENHANCEMENT-05-bulk-operations.md)

**What:** Batch operations on multiple channels/videos

**Why:** Manage large libraries efficiently

**Key Features:**
- Bulk download multiple channels
- Bulk delete videos
- Bulk pin/unpin (keeper feature)
- Bulk quality settings
- Cleanup by age (delete videos older than X days)
- Cleanup by size (delete largest N videos)

**Dependencies:**
- Enhancement #4 (Per-Channel Settings) for bulk quality/limit updates

**Estimated Effort:** 6-8 hours

---

### 6. Webhook System

**File:** [ENHANCEMENT-06-webhook-system.md](./ENHANCEMENT-06-webhook-system.md)

**What:** Flexible webhook system for external integrations

**Why:** Automate Plex refresh, Home Assistant, custom scripts

**Key Features:**
- POST/GET webhooks on events (download complete, failed, video added, etc.)
- Configurable per webhook (URL, headers, events)
- Retry logic with exponential backoff
- Test webhook button
- Async execution (non-blocking)

**Dependencies:** None

**Estimated Effort:** 8-10 hours

**Use Cases:**
- Plex library auto-refresh
- Home Assistant automations
- Custom processing scripts
- Notifiarr integration (for notifications)

---

## Recommended Implementation Order

### Phase 1: Quick Wins (3-6 hours)

1. **Enhancement #2: Fix Plex Integration** (1-2h)
   - Immediate value, already mostly implemented
   - Find library ID, update config, test
   - **Start here** - quick success

2. **Enhancement #6: Webhook System** (8-10h)
   - Foundation for notifications and automation
   - Enables Plex auto-refresh
   - Prerequisite for Notifiarr integration

### Phase 2: Core Features (12-16 hours)

3. **Enhancement #1: Notifications via Notifiarr** (2-4h)
   - Requires webhook system from Phase 1
   - Configure Notifiarr webhook
   - Test notifications

4. **Enhancement #3: Download History** (6-8h)
   - Better visibility and troubleshooting
   - Standalone feature, no dependencies

### Phase 3: Advanced Features (12-16 hours)

5. **Enhancement #4: Per-Channel Settings** (6-8h)
   - Major flexibility improvement
   - Prerequisite for bulk operations

6. **Enhancement #5: Bulk Operations** (6-8h)
   - Convenience feature for large libraries
   - Depends on per-channel settings

---

## Priority Matrix

```
High Value, Low Complexity (Do First):
├─ Enhancement #2: Fix Plex Integration
└─ Enhancement #1: Notifications (via Notifiarr)

High Value, Medium Complexity (Do Next):
├─ Enhancement #6: Webhook System
├─ Enhancement #3: Download History
└─ Enhancement #4: Per-Channel Settings

Medium Value, Low Complexity (Do Later):
└─ Enhancement #5: Bulk Operations
```

---

## Dependencies Graph

```
Enhancement #6 (Webhooks)
    └─> Enhancement #1 (Notifications via Notifiarr)

Enhancement #4 (Per-Channel Settings)
    └─> Enhancement #5 (Bulk Operations - quality/limit updates)

Enhancement #2 (Plex Fix) - Standalone
Enhancement #3 (History) - Standalone
```

---

## GitHub Issues Template

When creating GitHub issues, use this format:

```markdown
## Title
[Enhancement #X] Feature Name

## Priority
High | Medium | Low

## Complexity
Low | Medium | High

## Estimated Effort
X-Y hours

## Problem Statement
[Describe the problem this solves]

## Proposed Solution
[Brief overview]

## Dependencies
- [ ] Enhancement #N
- [ ] Feature X
- [ ] None

## Success Criteria
- [ ] Criterion 1
- [ ] Criterion 2

## References
See ENHANCEMENT-0X-filename.md for full specification
```

---

## Next Steps

1. **Create private GitHub repo** for this project
2. **Import specs** as issues or discussions
3. **Prioritize** based on immediate needs
4. **Start with Enhancement #2** (Plex fix) for quick win
5. **Build webhook system next** to enable automation

---

## Notes

- All enhancements are **optional** - app is fully functional now
- Enhancements are **independent** (except noted dependencies)
- **Notifiarr integration** recommended over custom notification code
- **Webhook system** is foundation for many integrations
- Focus on **high value, low complexity** items first

---

**Total Value:** High - These enhancements transform the app from "functional" to "production-ready" with monitoring, automation, and flexibility.

**Risk:** Low - All features are additive, won't break existing functionality.

**Maintenance:** Low - Well-architected features with clear separation of concerns.
