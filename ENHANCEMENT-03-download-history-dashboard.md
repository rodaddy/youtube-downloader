# Enhancement #3: Download History Dashboard

**Priority:** Medium
**Complexity:** Low
**Status:** Proposed

---

## Problem Statement

Current UI only shows:
- **Active Downloads** (currently running)
- **Downloaded Videos** (file list grouped by channel)

Missing:
- Historical download attempts (success/failure over time)
- Trends and statistics
- Quick retry for failed downloads
- Search and filter capabilities

---

## Proposed Solution

Add a "Download History" section showing all download attempts with stats, trends, and retry functionality.

---

## UI Design

### New Section: Download History

**Location:** Between "Active Downloads" and "Downloaded Videos"

```html
<div class="section">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <h2>📊 Download History</h2>
        <div>
            <select id="historyFilter" onchange="loadHistory()">
                <option value="all">All</option>
                <option value="success">Success Only</option>
                <option value="failed">Failed Only</option>
                <option value="today">Today</option>
                <option value="week">This Week</option>
            </select>
            <input type="text" id="historySearch" placeholder="Search channel..." onkeyup="loadHistory()">
        </div>
    </div>

    <!-- Stats Cards -->
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-value">127</div>
            <div class="stat-label">Total Downloads</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">95%</div>
            <div class="stat-label">Success Rate</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">12.4 GB</div>
            <div class="stat-label">This Week</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">5</div>
            <div class="stat-label">Failed (Last 7d)</div>
        </div>
    </div>

    <!-- History Table -->
    <div id="historyTable"></div>
</div>
```

### History Table Format

```
Channel               | Videos | Status    | Duration | Size    | Time                | Actions
---------------------|--------|-----------|----------|---------|---------------------|--------
JoshJohnsonComedy    | 3/3    | ✅ Success | 2m 15s   | 450 MB  | 2026-01-21 14:22   | 🔄 📋
LastWeekTonight      | 2/3    | ⚠️ Partial | 1m 45s   | 320 MB  | 2026-01-21 14:15   | 🔄 📋 ⚠️
HasanAbi             | 0/3    | ❌ Failed  | 0m 08s   | 0 MB    | 2026-01-21 14:10   | 🔄 📋
```

**Actions:**
- 🔄 = Retry download
- 📋 = View logs for this download
- ⚠️ = Show error details

---

## Database Schema

### New Table: `download_history`

```sql
CREATE TABLE IF NOT EXISTS download_history (
    id TEXT PRIMARY KEY,
    channel_url TEXT NOT NULL,
    channel_name TEXT NOT NULL,
    status TEXT NOT NULL,  -- 'success', 'failed', 'partial'
    videos_attempted INTEGER DEFAULT 0,
    videos_downloaded INTEGER DEFAULT 0,
    error_message TEXT,
    started_at REAL NOT NULL,
    completed_at REAL,
    duration_seconds INTEGER,
    total_size_bytes INTEGER DEFAULT 0,
    created_at REAL DEFAULT (strftime('%s', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_history_channel ON download_history(channel_url);
CREATE INDEX IF NOT EXISTS idx_history_status ON download_history(status);
CREATE INDEX IF NOT EXISTS idx_history_date ON download_history(created_at);
```

### Migration

**In `database.py`:**

```python
def _init_db(self) -> None:
    """Initialize database schema."""
    # ... existing tables ...

    # Download history table
    self.conn.execute("""
        CREATE TABLE IF NOT EXISTS download_history (
            id TEXT PRIMARY KEY,
            channel_url TEXT NOT NULL,
            channel_name TEXT NOT NULL,
            status TEXT NOT NULL,
            videos_attempted INTEGER DEFAULT 0,
            videos_downloaded INTEGER DEFAULT 0,
            error_message TEXT,
            started_at REAL NOT NULL,
            completed_at REAL,
            duration_seconds INTEGER,
            total_size_bytes INTEGER DEFAULT 0,
            created_at REAL DEFAULT (strftime('%s', 'now'))
        )
    """)
    self.conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_history_channel ON download_history(channel_url)"
    )
    self.conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_history_status ON download_history(status)"
    )
    self.conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_history_date ON download_history(created_at)"
    )
    self.conn.commit()
```

---

## API Endpoints

### GET `/api/history`

**Query Params:**
- `filter` - "all", "success", "failed", "today", "week"
- `search` - Channel name search
- `limit` - Number of results (default: 50)
- `offset` - Pagination offset

**Response:**
```json
{
  "history": [
    {
      "id": "abc-123",
      "channel_name": "JoshJohnsonComedy",
      "channel_url": "https://youtube.com/@JoshJohnsonComedy",
      "status": "success",
      "videos_attempted": 3,
      "videos_downloaded": 3,
      "started_at": 1737487200,
      "completed_at": 1737487335,
      "duration_seconds": 135,
      "total_size_bytes": 471859200
    }
  ],
  "stats": {
    "total_downloads": 127,
    "success_count": 121,
    "failed_count": 6,
    "success_rate": 95.3,
    "total_size_gb": 52.4,
    "avg_duration_seconds": 142
  }
}
```

### GET `/api/history/<download_id>`

**Response:**
```json
{
  "id": "abc-123",
  "channel_name": "JoshJohnsonComedy",
  "status": "failed",
  "error_message": "Members-only content (skipped)",
  "videos_attempted": 3,
  "videos_downloaded": 2,
  "logs": [
    "[JoshJohnsonComedy] Download attempt 1/3",
    "[JoshJohnsonComedy] Downloading video 1 of 3",
    "[JoshJohnsonComedy] ERROR: Members-only content",
    "[JoshJohnsonComedy] Retrying in 5s...",
    "..."
  ]
}
```

### POST `/api/history/<download_id>/retry`

**Action:** Retry a failed download

**Response:**
```json
{
  "message": "Download queued for retry",
  "new_download_id": "xyz-789"
}
```

---

## Implementation

### Track Downloads in History

**In `downloader.py`:**

```python
def _download_channel(self, channel_url: str, download_id: str) -> None:
    # ... existing code ...

    # Track in history
    start_time = time()
    videos_attempted = 0
    videos_downloaded = 0
    total_size = 0

    try:
        # Download logic...
        # Count videos from output or database

        # Success
        if self.database:
            self.database.add_download_history(
                download_id=download_id,
                channel_url=channel_url,
                channel_name=channel_name,
                status="success",
                videos_attempted=videos_attempted,
                videos_downloaded=videos_downloaded,
                started_at=start_time,
                completed_at=time(),
                total_size_bytes=total_size
            )
    except Exception as e:
        # Failure
        if self.database:
            self.database.add_download_history(
                download_id=download_id,
                channel_url=channel_url,
                channel_name=channel_name,
                status="failed",
                error_message=str(e),
                started_at=start_time,
                completed_at=time()
            )
```

### Database Methods

**In `database.py`:**

```python
def add_download_history(
    self,
    download_id: str,
    channel_url: str,
    channel_name: str,
    status: str,
    videos_attempted: int = 0,
    videos_downloaded: int = 0,
    error_message: Optional[str] = None,
    started_at: float = None,
    completed_at: float = None,
    total_size_bytes: int = 0
) -> None:
    """Add download attempt to history."""
    duration = int(completed_at - started_at) if completed_at else None

    self.conn.execute("""
        INSERT INTO download_history (
            id, channel_url, channel_name, status,
            videos_attempted, videos_downloaded, error_message,
            started_at, completed_at, duration_seconds, total_size_bytes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        download_id, channel_url, channel_name, status,
        videos_attempted, videos_downloaded, error_message,
        started_at, completed_at, duration, total_size_bytes
    ))
    self.conn.commit()

def get_download_history(
    self,
    filter_type: str = "all",
    search: str = "",
    limit: int = 50,
    offset: int = 0
) -> list:
    """Get download history with filters."""
    # SQL query with WHERE clauses based on filters
    # Return list of history records

def get_history_stats(self) -> dict:
    """Get aggregate statistics from history."""
    # SQL aggregations (COUNT, AVG, SUM)
    # Return stats dict
```

---

## UI Components

### Stats Cards CSS

```css
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 15px;
    margin-bottom: 20px;
}

.stat-card {
    background: #1f2a1f;
    padding: 20px;
    border-radius: 8px;
    text-align: center;
}

.stat-value {
    font-size: 2em;
    font-weight: bold;
    color: #4CAF50;
}

.stat-label {
    font-size: 0.9em;
    color: #888;
    margin-top: 5px;
}
```

### History Table JavaScript

```javascript
async function loadHistory() {
    const filter = document.getElementById('historyFilter').value;
    const search = document.getElementById('historySearch').value;

    const params = new URLSearchParams({ filter, search, limit: 50 });
    const response = await fetch(`/api/history?${params}`);
    const data = await response.json();

    renderHistoryStats(data.stats);
    renderHistoryTable(data.history);
}

function renderHistoryTable(history) {
    const container = document.getElementById('historyTable');

    if (history.length === 0) {
        container.innerHTML = '<div class="empty-state">No download history</div>';
        return;
    }

    const rows = history.map(item => {
        const statusIcon = item.status === 'success' ? '✅' :
                          item.status === 'partial' ? '⚠️' : '❌';
        const statusClass = `status-${item.status}`;

        return `
            <tr>
                <td>${item.channel_name}</td>
                <td>${item.videos_downloaded}/${item.videos_attempted}</td>
                <td><span class="${statusClass}">${statusIcon} ${item.status}</span></td>
                <td>${formatDuration(item.duration_seconds)}</td>
                <td>${formatSize(item.total_size_bytes)}</td>
                <td>${formatDateTime(item.started_at)}</td>
                <td class="actions">
                    <button onclick="retryDownload('${item.id}')" title="Retry">🔄</button>
                    <button onclick="viewLogs('${item.id}')" title="View Logs">📋</button>
                    ${item.error_message ? `<button onclick="showError('${item.id}')" title="Error">⚠️</button>` : ''}
                </td>
            </tr>
        `;
    }).join('');

    container.innerHTML = `
        <table class="history-table">
            <thead>
                <tr>
                    <th>Channel</th>
                    <th>Videos</th>
                    <th>Status</th>
                    <th>Duration</th>
                    <th>Size</th>
                    <th>Time</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
    `;
}

async function retryDownload(historyId) {
    if (!confirm('Retry this download?')) return;

    const response = await fetch(`/api/history/${historyId}/retry`, { method: 'POST' });
    const data = await response.json();

    alert(data.message);
    loadHistory();  // Refresh
}
```

---

## Success Criteria

- [ ] Download history table shows all attempts
- [ ] Stats cards show accurate aggregates
- [ ] Filter by status (success/failed/all)
- [ ] Filter by date range (today/week/all)
- [ ] Search by channel name
- [ ] Retry button queues failed downloads
- [ ] View logs shows download output
- [ ] Error details modal for failures
- [ ] Pagination for large history
- [ ] Export history to CSV

---

## Future Enhancements

- Charts (success rate over time, download volume)
- Download duration trends
- Most common failure reasons
- Channel performance comparison
- Scheduled report generation
- Retention policy (auto-delete old history)

---

**Estimated Effort:** 6-8 hours
**Risk:** Low (new feature, doesn't affect existing)
**Value:** High (visibility and troubleshooting)
