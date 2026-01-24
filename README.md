# YouTube Downloader

Automated YouTube channel downloader with Plex integration and web UI.

## Features

- 📥 **Automatic Downloads** - Monitor YouTube channels and download latest videos
- 🖼️ **Plex Integration** - Auto-upload thumbnails to Plex via API
- 🎨 **Poster Letterboxing** - Auto-converts 16:9 thumbnails to 2:3 Plex poster format with black bars
- 📝 **Smart Title Cleanup** - Strips redundant channel prefixes for cleaner display
- 🌐 **Web UI** - Manage channels and monitor downloads via browser
- 🔒 **Smart Authentication** - Optional auth with local network bypass (like Sonarr/Radarr)
- 📊 **Database Tracking** - SQLite database tracks downloaded videos
- 🎯 **Per-Channel Limits** - Keep only N most recent videos per channel
- ⏰ **Scheduled Downloads** - Automatic recurring downloads every 2 hours
- 🎬 **Quality Control** - Configure max quality (e.g., 1080p)
- 🛠️ **CLI & Web UI** - Use command-line or web interface

## Quick Start

### Installation

```bash
# Install via pip (recommended)
pip install youtube-downloader[plex]

# Or install from source
git clone https://github.com/yourusername/youtube-downloader.git
cd youtube-downloader
pip install -e .[plex]
```

### Configuration

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your settings:
   ```bash
   DOWNLOAD_DIR=/path/to/downloads
   VIDEOS_PER_CHANNEL=2

   # Optional: Plex integration
   PLEX_URL=http://your-plex-server:32400
   PLEX_TOKEN=your_plex_token
   PLEX_LIBRARY_ID=your_library_id

   # Optional: Web UI authentication
   ADMIN_USERNAME=admin
   ADMIN_PASSWORD=your_secure_password
   AUTH_BYPASS_LOCAL=true  # Skip auth for local network
   ```

3. Create `channels.txt` with YouTube channel URLs:
   ```
   https://www.youtube.com/@channelname1
   https://www.youtube.com/@channelname2
   ```

### Usage

**Start the web server:**
```bash
youtube-downloader serve
# or just:
youtube-downloader
```

Then open http://localhost:5001 in your browser.

**Download from command line:**
```bash
# Download all configured channels
youtube-downloader download --all

# Download specific channel
youtube-downloader download https://www.youtube.com/@channelname
```

**View configuration:**
```bash
youtube-downloader config
```

**List channels:**
```bash
youtube-downloader channels
```

## Plex Integration

The Plex integration automatically:
1. Downloads videos with `yt-dlp`
2. Renames thumbnails to `-poster.jpg` format
3. Uploads posters to Plex via API after each download
4. Locks posters to prevent Plex from overwriting them

This works even if your Plex library uses the "None" agent.

### Poster Letterboxing

YouTube thumbnails are 16:9 (widescreen), but Plex displays movies as 2:3 posters. The downloader automatically letterboxes thumbnails by:
1. Resizing to 1000px width
2. Adding black bars top/bottom to create 1000x1500 (2:3) poster
3. Saving as the `-poster.jpg` file

**Requirement:** ImageMagick must be installed:
```bash
# macOS
brew install imagemagick

# Ubuntu/Debian
sudo apt install imagemagick

# If ImageMagick is not found, letterboxing is skipped (thumbnails still work, just 16:9)
```

### Title Cleanup

Many YouTube channels add redundant prefixes to every video title (e.g., "Arsenal latest news - ..."). The downloader automatically strips common prefixes for cleaner display in Plex:
- "Arsenal latest news -" → Stripped for Charles Watts videos
- "Arsenal news -" → Stripped
- "FPL GWxx -" → Stripped for FPL channels

This makes video titles more distinguishable in your library.

**Getting your Plex token:**
1. Sign in to Plex Web App
2. Play any media item
3. Click "..." → "Get Info" → "View XML"
4. Look for `X-Plex-Token=...` in the URL

**Finding your library ID:**
1. Open Plex Web App
2. Go to your YouTube library
3. Look at the URL: `.../library/sections/14/all` (14 is the library ID)

## Authentication

**Local Network Bypass (Default):**
- Requests from private IPs (10.x, 172.16-31.x, 192.168.x, 127.x) skip authentication
- External requests require username/password
- Works like Sonarr/Radarr/etc.

**Disable authentication entirely:**
```bash
# Leave ADMIN_USERNAME and ADMIN_PASSWORD blank in .env
```

**Require auth for all requests:**
```bash
AUTH_BYPASS_LOCAL=false
```

## Deployment (Systemd)

### Manual Setup

1. Install system dependencies:
   ```bash
   sudo apt install python3 python3-pip yt-dlp ffmpeg imagemagick
   ```

2. Create service user:
   ```bash
   sudo useradd -r -s /bin/false -u 999 media
   ```

3. Install application:
   ```bash
   sudo mkdir -p /opt/youtube-downloader
   sudo chown media:media /opt/youtube-downloader
   cd /opt/youtube-downloader
   sudo -u media python3 -m venv .venv
   sudo -u media .venv/bin/pip install youtube-downloader[plex]
   ```

4. Configure environment:
   ```bash
   sudo cp .env.example /opt/youtube-downloader/.env
   sudo nano /opt/youtube-downloader/.env
   sudo chown media:media /opt/youtube-downloader/.env
   sudo chmod 600 /opt/youtube-downloader/.env
   ```

5. Install service:
   ```bash
   sudo cp youtube-downloader.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now youtube-downloader
   ```

### Ansible Deployment

For automated deployment to a server:

1. Copy and edit inventory:
   ```bash
   cp inventory.example.yml inventory.yml
   nano inventory.yml  # Update with your server details
   ```

2. Run playbook:
   ```bash
   ansible-playbook -i inventory.yml deploy.yml
   ```

The playbook:
- Installs dependencies
- Creates service user
- Sets up Python environment
- Configures systemd service
- Starts the application

## CLI Reference

```
youtube-downloader [COMMAND] [OPTIONS]

Commands:
  serve                  Start the web server (default)
  download [URL]         Download from a channel
  channels               List configured channels
  scan                   Scan and import existing videos
  config                 View/update configuration

Options (serve):
  --host TEXT            Server host (default: 127.0.0.1)
  --port INTEGER         Server port (default: 5001)
  --debug / --no-debug   Enable debug mode

Options (download):
  --all                  Download from all channels
```

## Development

**Install development dependencies:**
```bash
pip install -e .[dev]
```

**Run tests:**
```bash
pytest
```

**Format code:**
```bash
black src/
```

**Lint:**
```bash
ruff check src/
```

## Troubleshooting

**Downloads failing:**
- Check `yt-dlp` is installed: `which yt-dlp`
- Update yt-dlp: `pip install --upgrade yt-dlp`
- Check logs: `journalctl -u youtube-downloader -f`

**Plex thumbnails not uploading:**
- Verify `PLEX_TOKEN` and `PLEX_LIBRARY_ID` in `.env`
- Test Plex connection: `curl http://your-plex:32400/?X-Plex-Token=yourtoken`
- Check logs for "Plex sync: uploaded X thumbnails"

**Permission errors:**
- Ensure download directory is writable by service user
- Check systemd service user/group settings
- Verify NFS/CIFS mount permissions if using network storage

## Architecture

- **Flask** - Web server and API
- **yt-dlp** - YouTube video downloader
- **APScheduler** - Recurring download scheduler
- **SQLite** - Download tracking database
- **python-plexapi** - Plex API integration
- **Click** - Command-line interface
- **ImageMagick** - Thumbnail letterboxing (optional, graceful fallback)

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Support

- **Issues:** https://github.com/yourusername/youtube-downloader/issues
- **Discussions:** https://github.com/yourusername/youtube-downloader/discussions