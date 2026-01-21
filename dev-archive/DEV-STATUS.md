# Development Status & Next Steps

**Last Updated:** 2026-01-20 (Initial creation)

## Current Status: PROTOTYPE COMPLETE ✅

A working prototype exists but needs production refactoring.

---

## What Works Right Now

### Files Created
- `app.py` - Flask app with download logic (monolithic, ~220 lines)
- `templates/index.html` - Dark mode web UI
- `channels.txt` - 6 YouTube channel URLs
- `.env` - Configuration (1 video per channel, 1080p, test mode)
- `pyproject.toml` - Basic dependencies (Flask, python-dotenv)
- `README.md` - Usage instructions
- `SPEC.md` - Original requirements

### Features Implemented
- ✅ Web UI at http://localhost:5000
- ✅ Load channels from `channels.txt`
- ✅ Download latest N videos per channel
- ✅ Real-time progress tracking
- ✅ yt-dlp integration
- ✅ File organization by channel name
- ✅ Archive to prevent re-downloads
- ✅ Environment-based configuration

### Verified Working
- yt-dlp downloads successfully (tested manually)
- Flask app structure is sound
- UI renders correctly

---

## Current Problems

### Technical Debt
1. **Monolithic code** - Everything in one 220-line file
2. **No type hints** - Not type-safe
3. **No logging** - Just print statements
4. **No error handling** - Downloads fail silently
5. **Threading** - Should use async
6. **No tests** - Can't verify changes
7. **No config validation** - Errors happen at runtime

### Not Production Ready
- No structured logging
- No error recovery
- No monitoring
- No graceful shutdown
- No rate limiting

---

## Next Session: Execute Refactoring Plan

**Follow:** `/Users/rico/.claude/plans/composed-coalescing-lobster.md`

This plan contains 10 sequential steps to transform the prototype into production code.

### Step-by-Step Execution

**CRITICAL: Do ONE step at a time, verify, then move to next**

1. **Add dependencies** (pydantic, loguru) → `uv sync`
2. **Create package structure** → src/youtube_downloader/
3. **Implement config.py** → Pydantic settings
4. **Implement logger.py** → Structured logging
5. **Implement models.py** → Type-safe data models
6. **Refactor downloader.py** → Extract download logic
7. **Refactor app.py** → Clean Flask routes
8. **Add .gitignore** → Protect secrets
9. **Update README** → Reflect new structure
10. **Create run.py** → Entry point

### Verification After Each Step

Run these after EVERY step:
```bash
# Check imports work
python -c "from youtube_downloader import app"

# Run the app
uv run run.py

# Test download (when ready)
curl -X POST http://localhost:5000/api/download/channel \
  -H "Content-Type: application/json" \
  -d '{"channel_url": "https://www.youtube.com/@NateBJones"}'
```

---

## Configuration Reference

### Current .env Settings
```ini
DOWNLOAD_DIR=/Users/rico/Downloads/youtube_stuff
VIDEOS_PER_CHANNEL=1
VIDEO_FORMAT=bestvideo[height<=1080][vcodec^=avc]+bestaudio[acodec=aac]/best[height<=1080]
OUTPUT_FORMAT=mp4
HOST=127.0.0.1
PORT=5000
DEBUG=true
TEST_MODE=true  # Only uses first channel from channels.txt
```

### Channels (channels.txt)
1. https://www.youtube.com/@NateBJones
2. https://www.youtube.com/@CharlesWattsAFCnews
3. https://www.youtube.com/@mythicalkitchen
4. https://www.youtube.com/@FPLMate
5. https://www.youtube.com/@TheDiaryOfACEO
6. https://www.youtube.com/@FPLRaptor

---

## Context for AI Assistant

### User Preferences
- **Package manager:** uv (NOT pip)
- **Code style:** Production-grade Python
- **Approach:** One thing at a time, verify each step
- **Communication:** Explain what you're doing, no walls of code

### What User Wants
- Clean, maintainable code
- Type hints everywhere
- Proper error handling
- Structured logging
- Production-ready architecture

### What User Hates
- Doing 10 things at once
- TubeSync-style overcomplicated bullshit
- Assumptions without explanation
- Code without documentation

---

## Quick Start (Next Session)

```bash
# Navigate to project
cd /Volumes/ThunderBolt/Development/homelab-media-automation/youtube-downloader

# Read the refactoring plan
cat ~/.claude/plans/composed-coalescing-lobster.md

# Start with Step 1
uv add pydantic pydantic-settings loguru

# Follow plan step-by-step from there
```

---

## If Starting Fresh

If this is your first time seeing this project:

1. **Read:** `SPEC.md` - Understand what we're building
2. **Read:** `README.md` - See how to use current prototype
3. **Read:** `DEV-STATUS.md` (this file) - Understand where we are
4. **Read:** Plan file - Know what to do next
5. **Execute:** One step at a time from the plan

---

## Dependencies

**Required:**
- Python 3.10+
- uv (package manager)
- yt-dlp (system-wide or in PATH)

**Python packages:**
- Flask
- python-dotenv
- (More to be added during refactoring)

---

## Deployment Target (Future)

After refactoring complete:
- Deploy to LXC: media-automation (10.71.20.30)
- Download to: `/mnt/media/TV_Shows/youtube_stuff/`
- Plex library integration
- Systemd service
- Nginx reverse proxy

But NOT YET - finish refactoring first.