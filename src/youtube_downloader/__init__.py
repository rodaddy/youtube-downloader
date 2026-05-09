"""YouTube Downloader - Production-grade YouTube channel downloader."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("youtube-downloader")
except PackageNotFoundError:
    __version__ = "1.0.0"
