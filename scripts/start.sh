#!/usr/bin/env bash
# Canonical startup script for youtube-downloader
# Usage: ./scripts/start.sh

set -e

cd "$(dirname "$0")/.."

echo "🛑 Stopping any existing youtube-downloader processes..."
pkill -f "youtube-downloader serve" 2>/dev/null || true
pkill -f "python.*youtube_downloader" 2>/dev/null || true
sleep 2

echo "🚀 Starting youtube-downloader..."
nohup uv run youtube-downloader serve >> logs/app-startup.log 2>&1 &

echo "⏳ Waiting for app to start (Flask reloader takes ~5-7 seconds)..."
sleep 7

# Check if port 5001 is listening
if lsof -i :5001 > /dev/null 2>&1; then
    echo "✅ App started successfully on port 5001"
    echo "📊 Check status: curl http://localhost:5001/api/stats"
    echo "📝 Logs: tail -f logs/app.log"
else
    echo "❌ App failed to start - check logs/app-startup.log"
    tail -20 logs/app-startup.log
    exit 1
fi
