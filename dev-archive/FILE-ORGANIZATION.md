# File Organization for GitHub Release

## Files for GitHub (Public Repo)

### Core Application
- `src/youtube_downloader/` - All source code
- `templates/` - Flask HTML templates
- `pyproject.toml` - Package configuration
- `uv.lock` - Dependency lock file
- `README.md` - Main documentation
- `LICENSE` - MIT License
- `CONTRIBUTING.md` - Contribution guidelines

### Configuration Examples
- `.env.example` - Environment variables template
- `channels.txt.example` - Example channels list
- `deploy.yml.example` - Ansible playbook template (generic placeholders)
- `inventory.example.yml` - Ansible inventory template
- `youtube-downloader.service` - Generic systemd service file
- `templates/env.j2` - Ansible Jinja2 template for .env generation

### What Users Do
1. Copy examples to actual files:
   ```bash
   cp .env.example .env
   cp channels.txt.example channels.txt
   cp deploy.yml.example deploy.yml
   cp inventory.example.yml inventory.yml
   ```

2. Edit with their specific values (IPs, tokens, channels)

3. Deploy using their customized files

## Files Gitignored (Stay Local)

### Your Actual Configs (Private)
- `.env` - Your actual environment config
- `channels.txt` - Your actual YouTube channels
- `deploy.yml` - Your actual Ansible playbook (with real IPs: 10.71.20.30, etc.)
- `inventory.yml` - Your actual inventory (with Plex token)
- `data/` - Runtime database and config
- `downloads/` - Downloaded videos
- `logs/` - Application logs

### Development Artifacts (dev-archive/)
- `DEV-STATUS.md` - Development notes
- `SPEC.md` - Original specification
- `PLEX-THUMBNAIL-INVESTIGATION.md` - Investigation notes from fixing Plex thumbnails
- `PLEX-THUMBNAIL-FIX.md` - Documentation of the Plex poster upload solution
- `DEPLOYMENT.md` - Homelab-specific deployment guide (CTID 210, VLAN 20, etc.)
- `run.py` - Old entry point (replaced by CLI)
- `channels.txt` - Your actual channel list

## Before GitHub Push Checklist

- [ ] Verify no credentials in committed files
- [ ] Verify .gitignore blocks all sensitive files
- [ ] Test that examples work (copy and customize)
- [ ] Update pyproject.toml with your GitHub username
- [ ] Update README.md repository URLs
- [ ] Set author name in pyproject.toml
- [ ] Create GitHub repository
- [ ] Push to GitHub

## After GitHub Push

Your local repository will have:
- All public files (tracked by git)
- All your private configs (gitignored)
- dev-archive/ folder (gitignored) with your investigation notes

Others who clone will get:
- All public files
- Example templates they customize
- No access to your private data