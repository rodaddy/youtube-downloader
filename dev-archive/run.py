#!/usr/bin/env python3
"""Entry point for YouTube Downloader application."""

from youtube_downloader.app import create_app
from youtube_downloader.config import Settings

if __name__ == "__main__":
    settings = Settings()
    app = create_app(settings)
    app.run(host=settings.host, port=settings.port, debug=settings.debug)
