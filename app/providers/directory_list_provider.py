"""Abstract base class for directory listing providers."""

import logging
import re
from abc import abstractmethod
from typing import List, NamedTuple
from cachetools import TTLCache
from urllib3.util import Retry

from app.models.media import Movie, TVSeries
from app.providers.base import EpisodeResult, MovieResult
from app.plugins.base import PluginInterface

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Common video extensions supported by all directory providers
VIDEO_EXTENSIONS = (
    # Common & Modern
    ".mp4",
    ".m4v",
    ".mkv",
    ".webm",
    ".mov",
    ".avi",
    ".wmv",
    # High Definition / Transport Streams
    ".mts",
    ".m2ts",
    ".ts",
    ".avchd",
    # Legacy / Mobile
    ".flv",
    ".vob",
    ".ogv",
    ".3gp",
    ".3g2",
    ".mjp",
    ".m1v",
    ".m2v",
    # Professional / Flash / Other
    ".f4v",
    ".swf",
    ".asf",
    ".qt",
)

cache = TTLCache(maxsize=100, ttl=1800)


class FileEntry(NamedTuple):
    """Typed Named Tuple for file entries."""

    name: str
    path: str
    size: float  # Size in bytes


class DirectoryListProvider(PluginInterface):
    """Abstract base class for providers that parse directory listings.

    Subclasses must implement:
    - name: Provider name property
    - base_url: Base URL for the provider
    - movies_path: Path segment for movies (e.g., "/movies")
    - tv_path: Path segment for TV shows (e.g., "/shows" or "/tvs")
    - _parse_directory_html: Parse HTML to extract FileEntry list
    """

    def __init__(self):
        retry_config = Retry(
            total=5,
            backoff_factor=5,
            status_forcelist=[500, 502, 503, 504, 429],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
        )
        super().__init__(retry_config=retry_config)

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the provider name."""
        ...

    @property
    @abstractmethod
    def base_url(self) -> str:
        """Return the base URL for this provider."""
        ...

    @property
    @abstractmethod
    def movies_path(self) -> str:
        """Return the movies directory path segment."""
        ...

    @property
    @abstractmethod
    def tv_path(self) -> str:
        """Return the TV shows directory path segment."""
        ...

    @abstractmethod
    async def _parse_directory_html(self, html: str, base_url: str) -> List[FileEntry]:
        """Parse HTML content and return list of FileEntry objects.

        Args:
            html: The HTML content to parse
            base_url: The base URL for resolving relative paths

        Returns:
            List of FileEntry objects
        """
        ...

    async def get_directory_contents(self, target_url: str) -> List[FileEntry]:
        """Fetch and parse directory contents from a URL."""
        # Check cache first - manual caching for async function
        if target_url in cache:
            return cache[target_url]

        headers = {"User-Agent": "Mozilla/5.0"}

        try:
            response = await self.session.get(target_url, headers=headers)
            response.raise_for_status()
            result = await self._parse_directory_html(response.text, target_url)
            cache[target_url] = result  # Cache the result, not the coroutine
            return result
        except Exception as e:
            logger.warning(f"Error fetching directory {target_url}: {e}")
            return []

    async def get_directory(self, directory: str) -> List[FileEntry]:
        """Return directory contents."""
        return await self.get_directory_contents(directory)

    async def get_movie_entries(self) -> List[FileEntry]:
        """Return list of movies from the movies directory."""
        return await self.get_directory_contents(f"{self.base_url}{self.movies_path}")

    async def get_tv_entries(self) -> List[FileEntry]:
        """Return list of TV series from the TV directory."""
        return await self.get_directory_contents(f"{self.base_url}{self.tv_path}")

    async def get_movie_entries_by_name(self, name: str) -> List[FileEntry]:
        """Return list of movie files matching a name.

        Movies can be:
        1. Directly in /movies as files
        2. Inside a folder containing video files
        """
        movie_entries = await self.get_movie_entries()
        results = []
        name_lower = name.lower()

        for entry in movie_entries:
            entry_name_lower = entry.name.lower()

            # Check if it's a direct video file that matches the movie name
            if entry.name.endswith(VIDEO_EXTENSIONS):
                if name_lower in entry_name_lower or self._normalize_name(
                    name_lower
                ) in self._normalize_name(entry_name_lower):
                    results.append(entry)
            else:
                # It's a folder - check if folder name matches movie name
                if name_lower in entry_name_lower or self._normalize_name(
                    name_lower
                ) in self._normalize_name(entry_name_lower):
                    # Get files inside the folder
                    folder_contents = await self.get_directory_contents(entry.path)
                    for file_entry in folder_contents:
                        if file_entry.name.endswith(VIDEO_EXTENSIONS):
                            results.append(file_entry)

        return results

    def _normalize_name(self, name: str) -> str:
        """Normalize a name for fuzzy matching by removing special chars."""
        # Remove year in parentheses, dots, dashes, underscores
        name = re.sub(r"\(\d{4}\)", "", name)
        name = re.sub(r"[.\-_]", " ", name)
        name = re.sub(r"\s+", " ", name)
        return name.strip().lower()

    def get_quality_from_name(self, name: str) -> str:
        """Return quality from name including resolution and type."""
        name_lower = name.lower()

        # Detect resolution
        resolution = ""
        if "2160p" in name_lower or "4k" in name_lower or "uhd" in name_lower:
            resolution = "2160p"
        elif "1080p" in name_lower:
            resolution = "1080p"
        elif "720p" in name_lower:
            resolution = "720p"
        elif "480p" in name_lower:
            resolution = "480p"

        # Detect quality type
        quality_type = ""
        if "remux" in name_lower:
            quality_type = "REMUX"
        elif "bluray" in name_lower or "blu-ray" in name_lower or "bdrip" in name_lower:
            quality_type = "BluRay"
        elif "web-dl" in name_lower or "webdl" in name_lower:
            quality_type = "WEB-DL"
        elif "webrip" in name_lower or "web-rip" in name_lower:
            quality_type = "WEBRip"
        elif "hdtv" in name_lower:
            quality_type = "HDTV"
        elif "dvdrip" in name_lower or "dvd" in name_lower:
            quality_type = "DVDRip"
        elif re.search(r"\b(?:hd)?cam\b", name_lower):
            quality_type = "CAM"
        elif "web" in name_lower:
            quality_type = "WEB"

        # Combine resolution and type
        if resolution and quality_type:
            return f"{resolution} {quality_type}"
        elif resolution:
            return resolution
        elif quality_type:
            return quality_type
        return "Unknown"

    async def get_movie(self, movie: Movie) -> List[MovieResult]:
        """Return movie download links."""
        try:
            movie_entries = await self.get_movie_entries_by_name(movie.title)
            results = []
            for movie_entry in movie_entries:
                if movie_entry.name.endswith(VIDEO_EXTENSIONS):
                    logger.info(f"Movie entry: {movie_entry}")
                    results.append(
                        MovieResult(
                            title=movie.title,
                            quality=self.get_quality_from_name(movie_entry.name),
                            size=int(movie_entry.size),
                            download_url=movie_entry.path,
                            source_site=self.name,
                            filename=movie_entry.name,
                            provider_name=self.name,
                        )
                    )
            return results
        except Exception as e:
            logger.warning(f"Error fetching movie from {self.name}", exc_info=e)
            return []

    async def get_series_entries_by_name(self, name: str) -> List[FileEntry]:
        """Return list of series folder entries by name."""
        tv_entries = await self.get_tv_entries()
        name_lower = name.lower()

        for entry in tv_entries:
            entry_name_lower = entry.name.lower()

            if name_lower in entry_name_lower or self._normalize_name(
                name_lower
            ) in self._normalize_name(entry_name_lower):
                return [entry]

        return []

    async def get_episode_files(
        self,
        series_path: str,
        season: int,
        episode: int,
    ) -> List[FileEntry]:
        """Find episode files for a specific season and episode.

        Structure can be:
        1. /shows/Series Name/Season X/ - episodes in season folder
        2. /shows/Series Name/ - episodes directly in series folder
        """
        results = []
        folder_contents = await self.get_directory_contents(series_path)

        # Look for season folder first
        season_patterns = [
            f"season {season}",
            f"season {season:02d}",
            f"s{season:02d}",
            f"s{season}",
        ]

        for entry in folder_contents:
            entry_name_lower = entry.name.lower()

            # Check if this is a season folder
            is_season_folder = False
            for pattern in season_patterns:
                if pattern in entry_name_lower:
                    is_season_folder = True
                    # Found season folder, get episodes from it
                    season_contents = await self.get_directory_contents(entry.path)
                    for ep_entry in season_contents:
                        if self._matches_episode(ep_entry.name, season, episode):
                            results.append(ep_entry)
                    break

            if is_season_folder:
                continue

            # Also check if episodes are directly in series folder
            if entry.name.endswith(VIDEO_EXTENSIONS):
                if self._matches_episode(entry.name, season, episode):
                    results.append(entry)

        return results

    def _matches_episode(self, filename: str, season: int, episode: int) -> bool:
        """Check if filename matches the season and episode number."""
        filename_lower = filename.lower()

        # Common patterns: S01E01, s01e01, 1x01, etc.
        patterns = [
            rf"\bs{season:02d}e{episode:02d}\b",
            rf"\bs{season}e{episode}\b",
            rf"\b{season}x{episode:02d}\b",
            rf"\b{season}x{episode}\b",
            rf"\bseason\s*{season}\b.*\bepisode\s*{episode}\b",
        ]

        for pattern in patterns:
            if re.search(pattern, filename_lower):
                return True

        return False

    async def get_series_episode(
        self,
        series: TVSeries,
        season: int,
        episode: int,
    ) -> List[EpisodeResult]:
        """Return episode download links."""
        try:
            series_entries = await self.get_series_entries_by_name(series.title)

            if not series_entries:
                logger.info(f"Series not found: {series.title}")
                return []

            results = []
            for series_entry in series_entries:
                episode_files = await self.get_episode_files(
                    series_entry.path, season, episode
                )

                for ep_file in episode_files:
                    if ep_file.name.endswith(VIDEO_EXTENSIONS):
                        logger.info(f"Episode entry: {ep_file}")
                        results.append(
                            EpisodeResult(
                                title=f"{series.title} S{season:02d}E{episode:02d}",
                                season=season,
                                episode=episode,
                                quality=self.get_quality_from_name(ep_file.name),
                                size=int(ep_file.size) if ep_file.size else 0,
                                download_url=ep_file.path,
                                source_site=self.name,
                                filename=ep_file.name,
                                provider_name=self.name,
                            )
                        )

            return results
        except Exception as e:
            logger.warning(f"Error fetching episode from {self.name}", exc_info=e)
            return []
