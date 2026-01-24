"""Plex integration for uploading thumbnails.

This module provides the PlexIntegration class that handles uploading
video thumbnails directly to Plex via its API, bypassing broken metadata agents.
"""

import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests
from loguru import logger
from plexapi.server import PlexServer


class PlexIntegration:
    """Handles Plex API calls for thumbnail uploads.

    Attributes:
        url: Plex server base URL (e.g., http://10.71.1.35:32400)
        token: Plex authentication token
        library_id: Library section ID for YouTube videos
    """

    def __init__(self, url: str, token: str, library_id: int) -> None:
        """Initialize Plex integration.

        Args:
            url: Plex server URL
            token: Plex authentication token
            library_id: Library section ID
        """
        self.url = url.rstrip("/")
        self.token = token
        self.library_id = library_id
        self._session = requests.Session()
        self._session.headers.update({
            "X-Plex-Token": token,
            "Accept": "application/json",
        })

        # Initialize PlexServer instance for high-level API operations
        self.plex = PlexServer(self.url, self.token)
        self.library = self.plex.library.sectionByID(library_id)

    def _get(self, endpoint: str, **kwargs) -> requests.Response:
        """Make a GET request to Plex API."""
        url = f"{self.url}{endpoint}"
        return self._session.get(url, **kwargs)

    def _post(self, endpoint: str, **kwargs) -> requests.Response:
        """Make a POST request to Plex API."""
        url = f"{self.url}{endpoint}"
        return self._session.post(url, **kwargs)

    def _put(self, endpoint: str, **kwargs) -> requests.Response:
        """Make a PUT request to Plex API."""
        url = f"{self.url}{endpoint}"
        return self._session.put(url, **kwargs)

    def refresh_library(self) -> bool:
        """Trigger a library scan.

        Returns:
            True if refresh was triggered successfully
        """
        try:
            response = self._get(f"/library/sections/{self.library_id}/refresh")
            if response.status_code == 200:
                logger.info(f"Plex library {self.library_id} refresh triggered")
                return True
            else:
                logger.warning(
                    f"Plex refresh failed: {response.status_code} {response.text}"
                )
                return False
        except requests.RequestException as e:
            logger.error(f"Plex refresh error: {e}")
            return False

    def is_scanning(self) -> bool:
        """Check if the library is currently scanning.

        Returns:
            True if library is scanning
        """
        try:
            response = self._get(f"/library/sections/{self.library_id}")
            if response.status_code == 200:
                data = response.json()
                directory = data.get("MediaContainer", {}).get("Directory", [])
                if directory:
                    # Check for scanning attribute
                    return directory[0].get("scanning", False)
            return False
        except (requests.RequestException, ValueError) as e:
            logger.debug(f"Error checking scan status: {e}")
            return False

    def wait_for_scan(self, timeout: int = 120, poll_interval: int = 3) -> bool:
        """Wait for library scan to complete.

        Args:
            timeout: Maximum time to wait in seconds
            poll_interval: Time between status checks

        Returns:
            True if scan completed, False if timeout
        """
        start_time = time.time()

        # Give Plex a moment to start the scan
        time.sleep(2)

        while time.time() - start_time < timeout:
            if not self.is_scanning():
                logger.info("Plex library scan completed")
                return True
            logger.debug("Plex library still scanning...")
            time.sleep(poll_interval)

        logger.warning(f"Plex scan timeout after {timeout}s")
        return False

    def get_all_items(self) -> list[dict]:
        """Get all items in the library with their file paths.

        Works with both Movies and TV Shows library types.

        Returns:
            List of item dicts with ratingKey, title, and file path
        """
        items = []

        try:
            response = self._get(f"/library/sections/{self.library_id}/all")
            if response.status_code != 200:
                logger.error(f"Failed to get library items: {response.status_code}")
                return items

            data = response.json()
            metadata = data.get("MediaContainer", {}).get("Metadata", [])

            for item in metadata:
                item_type = item.get("type", "")

                if item_type == "movie":
                    # Movies library - items are at top level
                    media = item.get("Media", [])
                    if media and media[0].get("Part"):
                        file_path = media[0]["Part"][0].get("file", "")
                        items.append({
                            "ratingKey": item.get("ratingKey"),
                            "title": item.get("title", ""),
                            "file": file_path,
                            "thumb": item.get("thumb"),
                        })

                elif item_type == "show":
                    # TV Shows library - need to get episodes
                    show_key = item.get("ratingKey")
                    if not show_key:
                        continue

                    ep_response = self._get(f"/library/metadata/{show_key}/allLeaves")
                    if ep_response.status_code != 200:
                        continue

                    ep_data = ep_response.json()
                    episodes = ep_data.get("MediaContainer", {}).get("Metadata", [])

                    for ep in episodes:
                        media = ep.get("Media", [])
                        if media and media[0].get("Part"):
                            file_path = media[0]["Part"][0].get("file", "")
                            items.append({
                                "ratingKey": ep.get("ratingKey"),
                                "title": ep.get("title", ""),
                                "grandparentTitle": ep.get("grandparentTitle", ""),
                                "file": file_path,
                                "thumb": ep.get("thumb"),
                            })

        except (requests.RequestException, ValueError, KeyError) as e:
            logger.error(f"Error getting library items: {e}")

        return items

    def find_episode_by_file(self, file_path: str) -> Optional[int]:
        """Find episode ratingKey by matching file path.

        Args:
            file_path: Path to the video file

        Returns:
            Episode ratingKey or None if not found
        """
        # Normalize the file path for comparison
        file_name = Path(file_path).name

        episodes = self.get_all_episodes()
        for ep in episodes:
            ep_file = ep.get("file", "")
            if Path(ep_file).name == file_name:
                return ep.get("ratingKey")

        return None

    def upload_poster(self, rating_key: int, image_path: str) -> bool:
        """Upload an image as the poster for a Plex item.

        Uses python-plexapi library's built-in uploadPoster method.
        Uploads binary data directly instead of using filepath (which requires
        Plex server to access the file locally). Also locks the poster to prevent
        Plex from overwriting it.

        Args:
            rating_key: Plex item ratingKey
            image_path: Path to the image file (local machine path)

        Returns:
            True if upload succeeded
        """
        image_file = Path(image_path)
        if not image_file.exists():
            logger.warning(f"Thumbnail not found: {image_path}")
            return False

        try:
            # Fetch the item from Plex by ratingKey (use full path)
            item = self.plex.fetchItem(f"/library/metadata/{rating_key}")

            # Upload using file-like object (works even if Plex server can't access local path)
            with open(image_file, "rb") as f:
                item.uploadPoster(filepath=f)

            # Lock poster so Plex doesn't overwrite it
            item.lockPoster()

            logger.info(f"Uploaded and locked poster for '{item.title}' (ratingKey {rating_key})")
            return True

        except Exception as e:
            logger.error(f"Poster upload error for ratingKey {rating_key}: {e}")
            return False

    def upload_metadata(self, rating_key: int, title: Optional[str] = None,
                       summary: Optional[str] = None, date: Optional[str] = None) -> bool:
        """Upload metadata (title, summary, date) for a Plex item.

        Args:
            rating_key: Plex item ratingKey
            title: Full title (with emojis if present)
            summary: Description
            date: Release date in YYYY-MM-DD format

        Returns:
            True if upload succeeded
        """
        try:
            # Fetch the item from Plex by ratingKey
            item = self.plex.fetchItem(f"/library/metadata/{rating_key}")

            # Build edit dictionary with locked fields
            # PlexAPI uses field.value and field.locked syntax for editing with locks
            edits = {}
            locks = {}

            if title is not None:
                edits['title.value'] = title
                edits['title.locked'] = 1
            if summary is not None:
                edits['summary.value'] = summary
                edits['summary.locked'] = 1
            if date is not None:
                edits['originallyAvailableAt.value'] = date
                edits['originallyAvailableAt.locked'] = 1

            if not edits:
                logger.warning(f"No metadata provided for ratingKey {rating_key}")
                return False

            # Apply edits with locks using edit() method
            item.edit(**edits)

            logger.info(f"Updated metadata for '{item.title}' (ratingKey {rating_key})")
            return True

        except Exception as e:
            logger.error(f"Metadata upload error for ratingKey {rating_key}: {e}")
            return False

    def upload_thumbnails_for_directory(self, download_dir: Path) -> int:
        """Upload thumbnails for all videos in a directory.

        Matches video files to their -poster.jpg thumbnails and uploads
        them to the corresponding Plex items. Locks each poster after upload
        to prevent Plex from overwriting it.

        Args:
            download_dir: Directory containing downloaded videos

        Returns:
            Number of thumbnails successfully uploaded
        """
        uploaded = 0

        # Get all items from Plex (works for both Movies and TV Shows)
        items = self.get_all_items()
        logger.info(f"Found {len(items)} items in Plex library")

        # Build a map of filename -> ratingKey
        file_to_key: dict[str, int] = {}
        for item in items:
            item_file = item.get("file", "")
            if item_file:
                file_to_key[Path(item_file).name] = item["ratingKey"]

        # Find all poster files and upload them (search in Season folders)
        for channel_dir in download_dir.iterdir():
            if not channel_dir.is_dir():
                continue

            # Check for Season folders (TV Shows structure)
            for season_dir in channel_dir.iterdir():
                if not season_dir.is_dir() or not season_dir.name.startswith("Season"):
                    continue

                # Match .jpg files (our thumbnails are named same as video + .jpg)
                for poster_file in season_dir.glob("*.jpg"):
                    # Get corresponding video filename (same name, different extension)
                    base_name = poster_file.stem  # Remove .jpg
                    video_extensions = [".mp4", ".mkv", ".webm"]

                    for ext in video_extensions:
                        video_name = f"{base_name}{ext}"
                        if video_name in file_to_key:
                            rating_key = file_to_key[video_name]

                            # Upload and lock poster
                            if self.upload_poster(rating_key, str(poster_file)):
                                uploaded += 1
                            break

        logger.info(f"Uploaded {uploaded} thumbnails to Plex")
        return uploaded

    def sync_thumbnails(self, download_dir: Path) -> int:
        """Refresh library and upload all missing thumbnails.

        This is the main entry point for thumbnail sync.

        Args:
            download_dir: Directory containing downloaded videos

        Returns:
            Number of thumbnails uploaded
        """
        logger.info("Starting Plex thumbnail sync")

        # Trigger library refresh
        if not self.refresh_library():
            logger.warning("Could not trigger library refresh, continuing anyway")

        # Wait for scan to complete
        self.wait_for_scan()

        # Upload thumbnails
        return self.upload_thumbnails_for_directory(download_dir)

    def sync_metadata(self, download_dir: Path) -> int:
        """Refresh library and upload metadata from .info.json files.

        Scans all downloaded videos, reads their .info.json files, and uploads
        title, summary, and date metadata to Plex.

        Args:
            download_dir: Directory containing downloaded videos

        Returns:
            Number of items with metadata uploaded
        """
        import json
        from datetime import datetime

        logger.info("Starting Plex metadata sync")

        # Trigger library refresh
        if not self.refresh_library():
            logger.warning("Could not trigger library refresh, continuing anyway")

        # Wait for scan to complete
        self.wait_for_scan()

        uploaded = 0

        # Get all items from Plex
        items = self.get_all_items()
        logger.info(f"Found {len(items)} items in Plex library")

        # Build a map of filename -> ratingKey
        file_to_key: dict[str, int] = {}
        for item in items:
            item_file = item.get("file", "")
            if item_file:
                file_to_key[Path(item_file).name] = item["ratingKey"]

        # Find all .info.json files and upload metadata
        for channel_dir in download_dir.iterdir():
            if not channel_dir.is_dir():
                continue

            # Check for Season folders (TV Shows structure)
            for season_dir in channel_dir.iterdir():
                if not season_dir.is_dir() or not season_dir.name.startswith("Season"):
                    continue

                for info_file in season_dir.glob("*.info.json"):
                    try:
                        # Read metadata from .info.json
                        with open(info_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)

                        # Extract fields
                        full_title = data.get('title', '')  # Includes emojis
                        description = data.get('description', '')
                        upload_date = data.get('upload_date', '')  # YYYYMMDD format

                        # Convert upload_date to YYYY-MM-DD
                        if upload_date and len(upload_date) == 8:
                            dt = datetime.strptime(upload_date, "%Y%m%d")
                            date_str = dt.strftime("%Y-%m-%d")
                        else:
                            date_str = None

                        # Find corresponding video file
                        # Remove compound .info.json extension (stem only removes last suffix)
                        base_name = info_file.with_suffix("").with_suffix("").name
                        video_extensions = [".mp4", ".mkv", ".webm"]

                        for ext in video_extensions:
                            video_name = f"{base_name}{ext}"
                            if video_name in file_to_key:
                                rating_key = file_to_key[video_name]

                                # Upload metadata
                                if self.upload_metadata(
                                    rating_key,
                                    title=full_title,
                                    summary=description[:1000],  # Plex limit
                                    date=date_str
                                ):
                                    uploaded += 1
                                break

                    except Exception as e:
                        logger.error(f"Error processing {info_file}: {e}")

        logger.info(f"Uploaded metadata for {uploaded} items")
        return uploaded

    def get_or_create_keepers_collection(self):
        """Get or create the 'Keepers' collection.

        Returns:
            Plex collection object
        """
        try:
            # Try to find existing collection
            collections = self.library.collections()
            for collection in collections:
                if collection.title == "Keepers":
                    logger.debug("Found existing Keepers collection")
                    return collection

            # Create new collection
            logger.info("Creating Keepers collection")
            return self.library.createCollection(
                title="Keepers",
                items=[],  # Start empty
            )

        except Exception as e:
            logger.error(f"Error creating Keepers collection: {e}")
            return None

    def add_to_keepers(self, video_file_path: str) -> bool:
        """Add a video to the Keepers collection.

        Args:
            video_file_path: Path to the video file

        Returns:
            True if added successfully
        """
        try:
            # Find the Plex item by file path
            items = self.get_all_items()
            video_name = Path(video_file_path).name

            rating_key = None
            for item in items:
                if Path(item.get("file", "")).name == video_name:
                    rating_key = item.get("ratingKey")
                    break

            if not rating_key:
                logger.warning(f"Video not found in Plex: {video_name}")
                return False

            # Get or create Keepers collection
            collection = self.get_or_create_keepers_collection()
            if not collection:
                return False

            # Fetch the item and add to collection
            item = self.plex.fetchItem(f"/library/metadata/{rating_key}")
            collection.addItems(item)

            logger.info(f"Added '{item.title}' to Keepers collection")
            return True

        except Exception as e:
            logger.error(f"Error adding to Keepers: {e}")
            return False

    def remove_from_keepers(self, video_file_path: str) -> bool:
        """Remove a video from the Keepers collection.

        Args:
            video_file_path: Path to the video file

        Returns:
            True if removed successfully
        """
        try:
            # Find the Plex item by file path
            items = self.get_all_items()
            video_name = Path(video_file_path).name

            rating_key = None
            for item in items:
                if Path(item.get("file", "")).name == video_name:
                    rating_key = item.get("ratingKey")
                    break

            if not rating_key:
                logger.debug(f"Video not found in Plex: {video_name}")
                return False

            # Get Keepers collection
            collection = self.get_or_create_keepers_collection()
            if not collection:
                return False

            # Fetch the item and remove from collection
            item = self.plex.fetchItem(f"/library/metadata/{rating_key}")
            collection.removeItems(item)

            logger.info(f"Removed '{item.title}' from Keepers collection")
            return True

        except Exception as e:
            logger.error(f"Error removing from Keepers: {e}")
            return False

    def sync_keepers_collection(self, pinned_file_paths: list[str]) -> dict[str, int]:
        """Sync the Keepers collection with pinned videos.

        Args:
            pinned_file_paths: List of file paths for pinned videos

        Returns:
            Dict with counts: {"added": N, "removed": N}
        """
        counts = {"added": 0, "removed": 0}

        try:
            collection = self.get_or_create_keepers_collection()
            if not collection:
                logger.error("Could not get/create Keepers collection")
                return counts

            # Get current collection items
            current_items = collection.items()
            current_files = set()

            for item in current_items:
                # Get file path for this item
                media = item.media
                if media and media[0].parts:
                    file_path = media[0].parts[0].file
                    current_files.add(Path(file_path).name)

            # Build set of pinned filenames
            pinned_files = {Path(p).name for p in pinned_file_paths}

            # Find items to add (pinned but not in collection)
            to_add = pinned_files - current_files
            for filename in to_add:
                # Find full path
                full_path = next((p for p in pinned_file_paths if Path(p).name == filename), None)
                if full_path and self.add_to_keepers(full_path):
                    counts["added"] += 1

            # Find items to remove (in collection but not pinned)
            to_remove = current_files - pinned_files
            for filename in to_remove:
                # Build a dummy path for removal (only filename matters)
                if self.remove_from_keepers(str(Path("/dummy") / filename)):
                    counts["removed"] += 1

            logger.info(f"Keepers sync: added {counts['added']}, removed {counts['removed']}")

        except Exception as e:
            logger.error(f"Error syncing Keepers collection: {e}")

        return counts

    def get_watched_videos(self) -> list[str]:
        """Get list of file paths for all watched videos in the library.

        Returns:
            List of absolute file paths for watched videos
        """
        watched_files = []

        try:
            # Get all items from library
            items = self.get_all_items()

            for item in items:
                rating_key = item.get("ratingKey")
                file_path = item.get("file", "")

                if not rating_key or not file_path:
                    continue

                # Fetch full item details to get watch status
                try:
                    plex_item = self.plex.fetchItem(f"/library/metadata/{rating_key}")
                    if plex_item.isWatched:
                        watched_files.append(file_path)
                        logger.debug(f"Watched: {Path(file_path).name}")
                except Exception as e:
                    logger.debug(f"Error checking watch status for {file_path}: {e}")
                    continue

            logger.info(f"Found {len(watched_files)} watched videos in Plex")

        except Exception as e:
            logger.error(f"Error getting watched videos: {e}")

        return watched_files
