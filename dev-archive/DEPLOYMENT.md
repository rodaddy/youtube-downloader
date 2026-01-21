# Deployment Guide for Media-Automation LXC

This guide covers deploying YouTube Downloader to your Media-Automation LXC (CTID 210).

## Pre-Deployment Checklist

- [ ] Media-Automation LXC created (CTID 210) on proxmox02
- [ ] LXC has access to VLAN 20 (10.71.20.30)
- [ ] NFS share mounted at `/mnt/media` → TrueNAS `10.71.20.11:/mnt/TN01_media_files`
- [ ] Plex server accessible at `10.71.1.35:32400`
- [ ] Plex token obtained (see README for instructions)
- [ ] Plex library ID identified

## Quick Deployment (Ansible - Recommended)

1. **Update inventory file:**
   ```bash
   cp inventory.example.yml inventory.yml
   nano inventory.yml
   ```

   Update with your Plex token:
   ```yaml
   vars:
     plex_token: your_actual_plex_token_here
   ```

2. **Run Ansible playbook:**
   ```bash
   ansible-playbook -i inventory.yml deploy.yml
   ```

3. **Configure channels:**
   ```bash
   ssh root@10.71.20.30
   nano /opt/youtube-downloader/channels.txt
   # Add your YouTube channel URLs
   ```

4. **Restart service:**
   ```bash
   ssh root@10.71.20.30
   systemctl restart youtube-downloader
   ```

5. **Access Web UI:**
   - Internal: http://10.71.20.30:5001
   - Via SSH tunnel: `ssh -L 5001:localhost:5001 root@10.71.20.30`

## Manual Deployment

If you prefer manual deployment, follow README.md deployment section.

## Post-Deployment Configuration

### 1. Set Up Authentication (Optional)

SSH to the server and edit `.env`:
```bash
ssh root@10.71.20.30
nano /opt/youtube-downloader/.env
```

Add:
```bash
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_secure_password_here
AUTH_BYPASS_LOCAL=true
```

Restart service:
```bash
systemctl restart youtube-downloader
```

### 2. Configure Channels

Edit `/opt/youtube-downloader/channels.txt`:
```bash
https://www.youtube.com/@ChannelName1
https://www.youtube.com/@ChannelName2
```

### 3. Test Download

```bash
# SSH to server
ssh root@10.71.20.30

# Run manual download
cd /opt/youtube-downloader
.venv/bin/youtube-downloader download --all

# Check logs
journalctl -u youtube-downloader -f
```

### 4. Verify Plex Integration

1. Open Plex Web App
2. Go to YouTubeDownload library
3. Download should trigger automatically every 2 hours
4. Check logs for: `Plex sync: uploaded X thumbnails`

## Monitoring

**Service status:**
```bash
systemctl status youtube-downloader
```

**View logs:**
```bash
journalctl -u youtube-downloader -f
```

**Check disk usage:**
```bash
du -sh /mnt/media/media_services/youtube/YoutubeDownloads
```

## Updating the Application

1. **Pull latest code** (if deployed from source):
   ```bash
   ssh root@10.71.20.30
   cd /opt/youtube-downloader
   git pull
   ```

2. **Update dependencies:**
   ```bash
   sudo -u media .venv/bin/pip install --upgrade youtube-downloader[plex]
   ```

3. **Restart service:**
   ```bash
   systemctl restart youtube-downloader
   ```

## Troubleshooting

**Service won't start:**
```bash
# Check logs for errors
journalctl -u youtube-downloader -n 50

# Check permissions
ls -la /opt/youtube-downloader
ls -la /mnt/media/media_services/youtube/YoutubeDownloads
```

**Downloads failing:**
```bash
# Test yt-dlp directly
yt-dlp --version
yt-dlp https://www.youtube.com/watch?v=test_video_id
```

**Plex integration not working:**
```bash
# Test Plex connectivity
curl "http://10.71.1.35:32400/?X-Plex-Token=your_token"

# Check Plex logs
ssh root@10.71.1.35
tail -f "/var/lib/plexmediaserver/Library/Application Support/Plex Media Server/Logs/Plex Media Server.log"
```

## Backup & Restore

**Backup configuration:**
```bash
scp root@10.71.20.30:/opt/youtube-downloader/.env ./backup/.env
scp root@10.71.20.30:/opt/youtube-downloader/channels.txt ./backup/channels.txt
scp root@10.71.20.30:/opt/youtube-downloader/data/videos.db ./backup/videos.db
```

**Restore configuration:**
```bash
scp ./backup/.env root@10.71.20.30:/opt/youtube-downloader/.env
scp ./backup/channels.txt root@10.71.20.30:/opt/youtube-downloader/channels.txt
scp ./backup/videos.db root@10.71.20.30:/opt/youtube-downloader/data/videos.db
systemctl restart youtube-downloader
```

## Integration with Homelab

This service runs alongside:
- Sonarr (8989)
- Radarr (7878)
- Lidarr (8686)
- Prowlarr (9696)

All services share the same NFS mount at `/mnt/media` and run as user `media` (UID 999).

## Resource Usage

Expected resource consumption:
- **CPU:** < 1% idle, 50-100% during active downloads
- **RAM:** ~200MB
- **Disk I/O:** High during downloads, low otherwise
- **Network:** Depends on video quality and download frequency

## Next Steps

1. Monitor service for 24 hours
2. Verify automated downloads occur every 2 hours
3. Check Plex library for new videos with thumbnails
4. Adjust `VIDEOS_PER_CHANNEL` if needed
5. Set up log rotation if needed (journald handles this by default)

## Support

See main [README.md](README.md) for general troubleshooting and support options.
