#!/bin/bash
# Install Plex YouTube Agent and Absolute Series Scanner
# Works on macOS and Linux
#
# Usage: ./install-plex-youtube-agent.sh

set -e

# Detect Plex data directory
if [[ "$OSTYPE" == "darwin"* ]]; then
    PLEX_DIR="$HOME/Library/Application Support/Plex Media Server"
elif [[ -d "/var/lib/plexmediaserver/Library/Application Support/Plex Media Server" ]]; then
    PLEX_DIR="/var/lib/plexmediaserver/Library/Application Support/Plex Media Server"
else
    echo "ERROR: Could not find Plex Media Server directory"
    echo "Please set PLEX_DIR environment variable manually"
    exit 1
fi

echo "Plex directory: $PLEX_DIR"

# Create directories
SCANNERS_DIR="$PLEX_DIR/Scanners/Series"
PLUGINS_DIR="$PLEX_DIR/Plug-ins"

mkdir -p "$SCANNERS_DIR"
mkdir -p "$PLUGINS_DIR"

# Download Absolute Series Scanner
echo "Downloading Absolute Series Scanner..."
curl -fsSL -o "$SCANNERS_DIR/Absolute Series Scanner.py" \
    "https://raw.githubusercontent.com/ZeroQI/Absolute-Series-Scanner/master/Scanners/Series/Absolute%20Series%20Scanner.py"

chmod +x "$SCANNERS_DIR/Absolute Series Scanner.py"
echo "Installed: Absolute Series Scanner"

# Download YouTube Agent Bundle
echo "Downloading YouTube Agent Bundle..."
TEMP_DIR=$(mktemp -d)
cd "$TEMP_DIR"

curl -fsSL -o youtube-agent.zip \
    "https://github.com/ZeroQI/YouTube-Agent.bundle/archive/refs/heads/master.zip"

unzip -q youtube-agent.zip
rm -rf "$PLUGINS_DIR/YouTube-Agent.bundle"
mv YouTube-Agent.bundle-master "$PLUGINS_DIR/YouTube-Agent.bundle"

echo "Installed: YouTube Agent Bundle"

# Cleanup
rm -rf "$TEMP_DIR"

echo ""
echo "============================================"
echo "Installation complete!"
echo ""
echo "Next steps:"
echo "1. Restart Plex Media Server"
echo "2. Create a new library:"
echo "   - Type: TV Shows"
echo "   - Name: YouTube"
echo "   - Add folder: /path/to/YoutubeDownloads"
echo "3. Advanced settings:"
echo "   - Scanner: Absolute Series Scanner"
echo "   - Agent: YouTubeSeries"
echo "4. (Optional) Add your YouTube API key in agent settings"
echo "============================================"
